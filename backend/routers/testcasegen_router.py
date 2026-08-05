"""
TestCaseGen Router
-------------------
Ekran görüntüsü -> başlık çıkarma -> önceliklendirme -> test case üretimi -> ADO xlsx export.
Veritabanı YOK — state dosya tabanlı (services/testcasegen_service.py).
"""

import base64
import io
import json as _json
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User
from services import ai_service, testcasegen_service as svc

router = APIRouter(prefix="/api/testcasegen", tags=["testcasegen"])


def _sse(event: str, data: str) -> str:
    result = f"event: {event}\n"
    for line in data.split("\n"):
        result += f"data: {line}\n"
    return result + "\n"


def _load_or_404(user_id: int, session_id: str) -> dict:
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
    note: str


@router.put("/sessions/{session_id}/screens/{idx}")
async def edit_screen_note(session_id: str, idx: int, body: NoteIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    return svc.update_screen_note(current_user.id, session_id, idx, body.note)


@router.delete("/sessions/{session_id}/screens/{idx}")
async def delete_screen(session_id: str, idx: int, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    return svc.delete_screen(current_user.id, session_id, idx)


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
    screen_index: int
    text: str


@router.post("/sessions/{session_id}/titles")
async def add_title(session_id: str, body: TitleIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["titles"].append({
        "id": str(uuid.uuid4()),
        "screen_index": body.screen_index,
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
        screen = screens_by_index.get(title["screen_index"], {})
        score, level = svc.score_title(title["text"], screen.get("user_note", ""), title["screen_index"])
        title["score"] = score
        title["level"] = level
        title["level_source"] = "rule"

        prompt = svc.build_rationale_prompt(title["text"], level, score)
        try:
            rationale = await ai_service.ollama_generate_text(prompt)
            title["rationale"] = rationale.strip() or "Gerekçe üretilemedi."
        except Exception:
            title["rationale"] = "Gerekçe üretilemedi (Ollama servisine ulaşılamadı), skor kural motorundan geldi."

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
async def generate_testcases(session_id: str, body: GenerateTestcasesIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    titles_by_id = {t["id"]: t for t in session["titles"]}
    screens_by_index = {s["index"]: s for s in session["screens"]}

    created = []
    for title_id in body.title_ids:
        title = titles_by_id.get(title_id)
        if not title:
            continue
        screen = screens_by_index.get(title["screen_index"], {})
        prompt = svc.build_testcase_prompt(title["text"], screen.get("screen_summary", ""), screen.get("user_note", ""))
        try:
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
async def edit_step(session_id: str, tc_id: str, idx: int, body: StepIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for tc in session["testcases"]:
        if tc["id"] == tc_id:
            validated = svc.validate_steps([{"step_action": body.step_action, "step_expected": body.step_expected}])
            tc["steps"][idx] = validated[0]
            break
    else:
        raise HTTPException(404, "Test case bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return {"testcases": session["testcases"]}
