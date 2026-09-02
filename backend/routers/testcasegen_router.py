"""
TestCaseGen Router
-------------------
Ekran görüntüsü -> başlık çıkarma -> önceliklendirme -> test case üretimi -> ADO xlsx export.
Veritabanı YOK — state dosya tabanlı (services/testcasegen_service.py).
"""

import base64
import io
import json as _json
import logging
import re
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user, require_admin
from models.db_models import User, KnowledgeEntry
from services import ai_service, testcasegen_service as svc, knowledge_service

router = APIRouter(prefix="/api/testcasegen", tags=["testcasegen"])

logger = logging.getLogger(__name__)

# session_id her zaman create_session() icinde str(uuid.uuid4()) ile uretilir.
# Bu sekle uymayan her deger (path traversal, '..', backslash, vb.) reddedilir —
# aksi halde DATA_DIR / user_id / session_id join'i dosya sistemi disina tasabilir.
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(404, "Oturum bulunamadı")


def _sse(event: str, data: str) -> str:
    result = f"event: {event}\n"
    for line in data.split("\n"):
        result += f"data: {line}\n"
    return result + "\n"


def _load_or_404(user_id: int, session_id: str) -> dict:
    _validate_session_id(session_id)
    try:
        return svc.load_session(user_id, session_id)
    except FileNotFoundError:
        raise HTTPException(404, "Oturum bulunamadı")


# ── Oturumlar ────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(current_user: User = Depends(get_current_user)):
    return svc.create_session(current_user.id)


@router.get("/sessions")
async def list_sessions(current_user: User = Depends(get_current_user)):
    return {"sessions": svc.list_sessions(current_user.id)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: User = Depends(get_current_user)):
    return _load_or_404(current_user.id, session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    svc.delete_session(current_user.id, session_id)
    return {"ok": True}


# ── Ekranlar (Adım 1) ───────────────────────────────────────────────────

@router.post("/sessions/{session_id}/screens/upload")
async def upload_screens(
    session_id: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(current_user.id, session_id)
    session = None
    for f in files:
        content = await f.read()
        ext = "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".png"
        session = svc.add_screen(current_user.id, session_id, content, ext=ext)
    return session


class CaptureIn(BaseModel):
    image_b64: str
    note: str = ""


@router.post("/sessions/{session_id}/screens/capture")
async def capture_screen(session_id: str, body: CaptureIn, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    try:
        image_bytes = base64.b64decode(body.image_b64, validate=True)
    except Exception:
        raise HTTPException(400, "Geçersiz görsel verisi (base64 decode edilemedi)")
    return svc.add_screen(current_user.id, session_id, image_bytes, ext=".png", note=body.note)


class ReorderIn(BaseModel):
    order: list[int]


@router.put("/sessions/{session_id}/screens/reorder")
async def reorder_screens(session_id: str, body: ReorderIn, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    try:
        return svc.reorder_screens(current_user.id, session_id, body.order)
    except ValueError as e:
        raise HTTPException(400, str(e))


class NoteIn(BaseModel):
    note: Optional[str] = None
    flow_id: Optional[str] = None
    flow_name: Optional[str] = None


@router.put("/sessions/{session_id}/screens/{idx}")
async def edit_screen_note(session_id: str, idx: int, body: NoteIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(400, "Güncellenecek alan belirtilmedi")
    kwargs = {}
    if "note" in provided:
        kwargs["note"] = provided["note"]
    if "flow_id" in provided:
        kwargs["flow_id"] = provided["flow_id"]
    if "flow_name" in provided:
        kwargs["flow_name"] = provided["flow_name"]
    return svc.update_screen_note(current_user.id, session_id, idx, **kwargs)


@router.delete("/sessions/{session_id}/screens/{idx}")
async def delete_screen(session_id: str, idx: int, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    return svc.delete_screen(current_user.id, session_id, idx)


@router.get("/sessions/{session_id}/screens/{idx}/image")
async def get_screen_image(session_id: str, idx: int, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    screen = session["screens"][idx]
    path = svc.screen_image_path(current_user.id, session_id, idx, screen["image_ext"])
    if not path.exists():
        raise HTTPException(404, "Görsel dosyası bulunamadı")
    return FileResponse(path)


# ── Analiz Dökümanı (Adım 1 alternatifi) ────────────────────────────────

_ALLOWED_DOC_EXTS = {".docx", ".xlsx"}


@router.post("/sessions/{session_id}/document/upload")
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, "Sadece .docx veya .xlsx desteklenir")

    content = await file.read()
    try:
        if ext == ".docx":
            text, truncated = svc.extract_text_from_docx(content)
            embedded_images = svc.extract_images_from_docx(content)
        else:
            text, truncated = svc.extract_text_from_xlsx(content)
            embedded_images = svc.extract_images_from_xlsx(content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not text.strip():
        raise HTTPException(400, "Dökümandan metin çıkarılamadı, dosya boş görünüyor")

    session["document"] = {
        "filename": file.filename,
        "ext": ext,
        "extracted_text": text,
        "truncated": truncated,
        "candidate_titles": [],
    }
    svc.save_session(current_user.id, session_id, session)

    # Dökümanın içine gömülü ekran görüntüleri varsa, mevcut vision tabanlı
    # başlık çıkarma / test case üretimi akışının kullanabilmesi için
    # normal ekran görüntüsü gibi kaydedilir (screens listesine eklenir).
    for image_bytes, image_ext in embedded_images:
        svc.add_screen(
            current_user.id, session_id, image_bytes, image_ext,
            note=f"'{file.filename}' içinden çıkarıldı",
        )

    try:
        await knowledge_service.add_entry(
            db, "document", file.filename, text,
            user_id=current_user.id, source_ref=session_id,
        )
    except Exception as e:
        logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
        db.rollback()

    return svc.load_session(current_user.id, session_id)


@router.delete("/sessions/{session_id}/document")
async def delete_document(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["document"] = None
    svc.save_session(current_user.id, session_id, session)
    return session


@router.post("/sessions/{session_id}/document/extract-titles")
async def extract_titles_from_document(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    document = session.get("document")
    if not document:
        raise HTTPException(400, "Önce bir analiz dökümanı yükleyin")

    try:
        context = await knowledge_service.search(db, document["extracted_text"][:1000], top_k=8, entry_types=["rule"])
    except Exception as e:
        logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
        context = []
    context_block = knowledge_service.format_context_block(context)

    prompt = context_block + svc.build_document_title_extraction_prompt(document["extracted_text"])
    try:
        raw = await ai_service.ollama_generate_text(prompt, num_ctx=ai_service.OLLAMA_NUM_CTX_LARGE)
    except Exception as e:
        raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")

    parsed = svc.extract_json_object(raw)
    candidates = parsed.get("titles", []) if parsed else []
    document["candidate_titles"] = [
        {"text": c.get("text", ""), "excerpt": c.get("excerpt", "")}
        for c in candidates if c.get("text")
    ]
    svc.save_session(current_user.id, session_id, session)
    return session


# ── Başlık çıkarma (Adım 2) ─────────────────────────────────────────────

@router.post("/sessions/{session_id}/extract-titles")
async def extract_titles(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    screens = session["screens"]
    if not screens:
        raise HTTPException(400, "Önce en az bir ekran görüntüsü ekleyin")

    async def stream():
        prev_note, prev_summary = "", ""
        for screen in screens:
            image_path = svc.screen_image_path(current_user.id, session_id, screen["index"], screen["image_ext"])
            image_b64 = base64.b64encode(image_path.read_bytes()).decode()
            prompt = svc.build_title_extraction_prompt(screen.get("user_note", ""), prev_note, prev_summary)
            try:
                raw = await ai_service.ollama_generate_vision(prompt, [image_b64])
            except Exception as e:
                yield _sse("error", f"Ollama servisine ulaşılamadı: {e}")
                return

            parsed = svc.extract_json_object(raw)
            try:
                entries = parsed.get("screen_titles") if parsed else None
                entry = entries[0] if entries else None
                if entry is None:
                    raise ValueError("screen_titles girdisi yok")
                screen["candidate_titles"] = entry.get("candidate_titles", [])
                screen["screen_summary"] = entry.get("screen_summary", "")
                screen["parse_error"] = False
            except Exception:
                screen["candidate_titles"] = []
                screen["screen_summary"] = raw
                screen["parse_error"] = True

            prev_note = screen.get("user_note", "")
            prev_summary = screen["screen_summary"]
            svc.save_session(current_user.id, session_id, session)

            yield _sse("screen_done", _json.dumps({
                "screen_index": screen["index"],
                "candidate_titles": screen["candidate_titles"],
                "screen_summary": screen["screen_summary"],
                "parse_error": screen["parse_error"],
            }, ensure_ascii=False))

        yield _sse("complete", "")

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class TitleIn(BaseModel):
    text: str
    screen_indices: list[int] = []
    doc_excerpt: Optional[str] = None


@router.post("/sessions/{session_id}/titles")
async def add_title(session_id: str, body: TitleIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if not body.screen_indices and not body.doc_excerpt:
        raise HTTPException(400, "Ekran veya döküman alıntısı belirtilmeli")
    source = "document" if body.doc_excerpt else "screens"
    session["titles"].append({
        "id": str(uuid.uuid4()),
        "source": source,
        "screen_indices": body.screen_indices,
        "doc_excerpt": body.doc_excerpt,
        "text": body.text,
        "score": None,
        "level": None,
        "level_source": None,
        "rationale": "",
    })
    svc.save_session(current_user.id, session_id, session)
    return session


class TitleTextIn(BaseModel):
    text: str


@router.put("/sessions/{session_id}/titles/{title_id}")
async def edit_title(session_id: str, title_id: str, body: TitleTextIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for title in session["titles"]:
        if title["id"] == title_id:
            title["text"] = body.text
            break
    else:
        raise HTTPException(404, "Başlık bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return session


@router.delete("/sessions/{session_id}/titles/{title_id}")
async def delete_title(session_id: str, title_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["titles"] = [t for t in session["titles"] if t["id"] != title_id]
    svc.save_session(current_user.id, session_id, session)
    return session


# ── Önceliklendirme (Adım 3) ────────────────────────────────────────────

@router.post("/sessions/{session_id}/prioritize")
async def prioritize(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    screens_by_index = {s["index"]: s for s in session["screens"]}

    for title in session["titles"]:
        if title.get("level_source") == "manual":
            continue  # kullanıcı elle ayarladı, otomatik hesaplama ezmez

        indices = title["screen_indices"]
        if title.get("source") == "document":
            combined_note = title.get("doc_excerpt") or ""
            depth_index = 0
        else:
            combined_note = " ".join(
                screens_by_index[i]["user_note"] for i in indices if i in screens_by_index and screens_by_index[i].get("user_note")
            )
            depth_index = indices[-1] if indices else 0
        score, level = svc.score_title(title["text"], combined_note, depth_index)
        title["score"] = score
        title["level"] = level
        title["level_source"] = "rule"

        prompt = svc.build_rationale_prompt(title["text"], level, score)
        try:
            rationale = await ai_service.ollama_generate_text(prompt)
            title["rationale"] = rationale.strip() or "Gerekçe üretilemedi."
        except Exception:
            title["rationale"] = "Gerekçe üretilemedi (Ollama servisine ulaşılamadı), skor kural motorundan geldi."

        # Her başlık skorlandıktan sonra hemen kaydet — istek yarıda kesilirse
        # (sayfa yenileme, ağ kopması) o ana kadarki ilerleme kaybolmaz.
        svc.save_session(current_user.id, session_id, session)

    return session


class PriorityIn(BaseModel):
    level: Literal["high", "medium", "low"]


@router.put("/sessions/{session_id}/titles/{title_id}/priority")
async def set_priority(session_id: str, title_id: str, body: PriorityIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for title in session["titles"]:
        if title["id"] == title_id:
            title["level"] = body.level
            title["level_source"] = "manual"
            break
    else:
        raise HTTPException(404, "Başlık bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return session


# ── Test case üretimi (Adım 4) ──────────────────────────────────────────

class GenerateTestcasesIn(BaseModel):
    title_ids: list[str]


@router.post("/sessions/{session_id}/generate-testcases")
async def generate_testcases(
    session_id: str,
    body: GenerateTestcasesIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    titles_by_id = {t["id"]: t for t in session["titles"]}
    screens_by_index = {s["index"]: s for s in session["screens"]}

    example_rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.entry_type == "example")
        .order_by(KnowledgeEntry.created_at.desc())
        .limit(svc.MAX_PROMPT_EXAMPLES)
        .all()
    )
    examples = [{"title": r.title, "content": r.content} for r in example_rows]

    created = []
    for title_id in body.title_ids:
        title = titles_by_id.get(title_id)
        if not title:
            continue

        try:
            context = await knowledge_service.search(db, title["text"], top_k=8)
        except Exception as e:
            logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
            context = []
        context_block = knowledge_service.format_context_block(context)

        if title.get("source") == "document":
            prompt = context_block + svc.build_testcase_prompt_from_document(
                title["text"], title.get("doc_excerpt") or "", examples=examples,
            )
            try:
                raw = await ai_service.ollama_generate_text(prompt)
            except Exception as e:
                raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")
        else:
            screens = [
                {
                    "index": i,
                    "summary": screens_by_index[i].get("screen_summary", ""),
                    "note": screens_by_index[i].get("user_note", ""),
                }
                for i in title["screen_indices"] if i in screens_by_index
            ]
            images_b64 = []
            for i in title["screen_indices"]:
                screen = screens_by_index.get(i)
                if not screen:
                    continue
                image_path = svc.screen_image_path(current_user.id, session_id, i, screen["image_ext"])
                if image_path.exists():
                    images_b64.append(base64.b64encode(image_path.read_bytes()).decode())

            prompt = context_block + svc.build_testcase_prompt(title["text"], screens, examples=examples)
            try:
                if images_b64:
                    raw = await ai_service.ollama_generate_vision(prompt, images_b64)
                else:
                    raw = await ai_service.ollama_generate_text(prompt)
            except Exception as e:
                raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")

        parsed = svc.extract_json_object(raw)
        raw_steps = parsed.get("steps", []) if parsed else []
        steps = svc.validate_steps(raw_steps)
        testcase = {"id": str(uuid.uuid4()), "title_id": title_id, "steps": steps}
        session["testcases"].append(testcase)
        created.append(testcase)

    svc.save_session(current_user.id, session_id, session)
    return {"testcases": created}


class StepIn(BaseModel):
    step_action: str
    step_expected: str


@router.put("/sessions/{session_id}/testcases/{tc_id}/steps/{idx}")
async def edit_step(
    session_id: str,
    tc_id: str,
    idx: int,
    body: StepIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    old_step = None
    target_tc = None
    for tc in session["testcases"]:
        if tc["id"] == tc_id:
            old_step = tc["steps"][idx]
            validated = svc.validate_steps([{"step_action": body.step_action, "step_expected": body.step_expected}])
            tc["steps"][idx] = validated[0]
            target_tc = tc
            break
    else:
        raise HTTPException(404, "Test case bulunamadı")
    svc.save_session(current_user.id, session_id, session)

    new_step = target_tc["steps"][idx]
    if (old_step["step_action"], old_step["step_expected"]) != (new_step["step_action"], new_step["step_expected"]):
        titles_by_id = {t["id"]: t for t in session["titles"]}
        title = titles_by_id.get(target_tc["title_id"])
        title_text = title["text"] if title else ""
        correction_text = (
            f"Eski: {old_step['step_action']} → {old_step['step_expected']}\n"
            f"Doğrusu: {new_step['step_action']} → {new_step['step_expected']}"
        )
        try:
            await knowledge_service.add_entry(
                db, "correction", title_text, correction_text,
                user_id=current_user.id, source_ref=tc_id,
            )
        except Exception as e:
            logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
            db.rollback()

    return {"testcases": session["testcases"]}


# ── Export Varsayılanları ────────────────────────────────────────────────

class TcgDefaultsOut(BaseModel):
    area_path: str
    assigned_to: str
    state: str


def _tcg_defaults_dict(user: User) -> dict:
    return {
        "area_path": user.tcg_area_path or "",
        "assigned_to": user.tcg_assigned_to or user.full_name or user.username,
        "state": user.tcg_state or "Design",
    }


@router.get("/defaults", response_model=TcgDefaultsOut)
async def get_tcg_defaults(current_user: User = Depends(get_current_user)):
    return _tcg_defaults_dict(current_user)


class TcgDefaultsIn(BaseModel):
    area_path: str = ""
    assigned_to: str = ""
    state: Literal["Design", "Ready", "Closed"] = "Design"


@router.put("/defaults", response_model=TcgDefaultsOut)
async def set_tcg_defaults(
    body: TcgDefaultsIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.tcg_area_path = body.area_path
    current_user.tcg_assigned_to = body.assigned_to
    current_user.tcg_state = body.state
    db.commit()
    db.refresh(current_user)
    return _tcg_defaults_dict(current_user)


# ── Export ───────────────────────────────────────────────────────────────

class ExportIn(BaseModel):
    testcase_ids: list[str]


@router.post("/sessions/{session_id}/export")
async def export_testcases(
    session_id: str,
    body: ExportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    if not body.testcase_ids:
        raise HTTPException(400, "Dışa aktarılacak test case seçilmedi")

    titles_by_id = {t["id"]: t for t in session["titles"]}
    testcases = [tc for tc in session["testcases"] if tc["id"] in body.testcase_ids]
    if not testcases:
        raise HTTPException(400, "Seçilen test case'ler bulunamadı")

    for tc in testcases:
        title = titles_by_id.get(tc["title_id"])
        title_text = title["text"] if title else ""
        steps_text = "\n".join(
            f"Adım: {s['step_action']} → Beklenen: {s['step_expected']}" for s in tc["steps"]
        )
        try:
            await knowledge_service.add_entry(
                db, "scenario", title_text, steps_text,
                user_id=current_user.id, source_ref=tc["id"],
            )
        except Exception as e:
            logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
            db.rollback()

    defaults = _tcg_defaults_dict(current_user)
    wb = svc.build_export_workbook(
        testcases, titles_by_id,
        defaults["area_path"], defaults["assigned_to"], defaults["state"],
    )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="testcases_{session_id[:8]}.xlsx"'},
    )


# ── Bilgi Tabanı (Admin) ────────────────────────────────────────────────

class KnowledgeRuleIn(BaseModel):
    title: str
    content: str


@router.post("/knowledge/rules")
async def add_knowledge_rule(
    body: KnowledgeRuleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    added = await knowledge_service.add_entry(db, "rule", body.title, body.content, user_id=current_user.id)
    if added == 0:
        raise HTTPException(503, "Embedding modeli kullanılamıyor, kural kaydedilemedi")
    return {"status": "ok", "chunks": added}


@router.get("/knowledge/rules")
async def list_knowledge_rules(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.entry_type == "rule")
        .order_by(KnowledgeEntry.created_at.desc())
        .all()
    )
    return {"rules": [
        {"id": r.id, "title": r.title, "content": r.content, "created_at": r.created_at.isoformat()}
        for r in rows
    ]}


@router.delete("/knowledge/rules/{entry_id}")
async def delete_knowledge_rule(
    entry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.entry_type == "rule")
        .first()
    )
    if not row:
        raise HTTPException(404, "Kural bulunamadı")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


# ── Bilgi Tabanı (Admin) — Format Örnekleri ─────────────────────────────
# "rule" kayıtlarından farkı: embedding YOK, benzerlik aramasıyla filtrelenmez —
# generate-testcases her seferinde en yeni MAX_PROMPT_EXAMPLES tanesini prompt'a
# few-shot olarak ekler (bkz. svc._format_examples_block).

class KnowledgeExampleIn(BaseModel):
    title: str
    content: str


@router.post("/knowledge/examples")
async def add_knowledge_example(
    body: KnowledgeExampleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(400, "Başlık ve içerik gerekli")
    knowledge_service.add_example(db, title, content, user_id=current_user.id)
    return {"status": "ok"}


@router.get("/knowledge/examples")
async def list_knowledge_examples(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.entry_type == "example")
        .order_by(KnowledgeEntry.created_at.desc())
        .all()
    )
    return {"examples": [
        {"id": r.id, "title": r.title, "content": r.content, "created_at": r.created_at.isoformat()}
        for r in rows
    ]}


@router.delete("/knowledge/examples/{entry_id}")
async def delete_knowledge_example(
    entry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.entry_type == "example")
        .first()
    )
    if not row:
        raise HTTPException(404, "Örnek bulunamadı")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@router.get("/knowledge/status")
async def knowledge_status(current_user: User = Depends(require_admin)):
    embedding = await ai_service.ollama_embed("ping")
    return {"embedding_model_available": embedding is not None}


# ── Bilgi Tabanı Sohbet (tüm kullanıcılar) ──────────────────────────────

class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    message: str
    history: list[ChatMessageIn] = []


@router.post("/chat")
async def chat(
    body: ChatIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.message.strip():
        raise HTTPException(400, "Mesaj boş olamaz")

    try:
        context = await knowledge_service.search(db, body.message, top_k=8)
    except Exception as e:
        logger.warning(f"Bilgi tabanı işlemi başarısız: {e}")
        context = []
    context_block = knowledge_service.format_context_block(context)

    history = [{"role": m.role, "content": m.content} for m in body.history]
    prompt = svc.build_chat_prompt(context_block, history, body.message)

    async def stream():
        try:
            async for piece in ai_service.ollama_generate_text_stream(prompt):
                yield _sse("token", piece)
            yield _sse("complete", "")
        except Exception as e:
            yield _sse("error", f"Ollama servisine ulaşılamadı: {e}")

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
