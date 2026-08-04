"""
TestCaseGen Service
--------------------
Ekran görüntülerinden test case başlığı çıkarma, kural tabanlı
önceliklendirme, adım doğrulama ve ADO formatlı Excel export.
Veritabanı YOK — state dosya tabanlı (bkz. session_* fonksiyonları).
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────
# JSON temizleme / parse
# ──────────────────────────────────────────────────────

def clean_json_text(text: str) -> str:
    """Markdown code fence'leri (```json ... ``` veya ``` ... ```) temizler."""
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> Optional[dict]:
    """LLM çıktısından ilk JSON nesnesini çıkarır. Parse edilemezse None döner."""
    if not text:
        return None
    cleaned = clean_json_text(text)
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = cleaned[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


# ──────────────────────────────────────────────────────
# Oturum/Ekran Depolama (Dosya Tabanlı)
# ──────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "testcasegen_data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_dir(user_id: int, session_id: str) -> Path:
    return DATA_DIR / str(user_id) / session_id


def _session_json_path(user_id: int, session_id: str) -> Path:
    return _session_dir(user_id, session_id) / "session.json"


def _screens_dir(user_id: int, session_id: str) -> Path:
    return _session_dir(user_id, session_id) / "screenshots"


def create_session(user_id: int) -> dict:
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "user_id": user_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "current_step": 1,
        "screens": [],
        "titles": [],
        "testcases": [],
    }
    _session_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    _screens_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    save_session(user_id, session_id, session)
    return session


def list_sessions(user_id: int) -> list:
    base = DATA_DIR / str(user_id)
    if not base.exists():
        return []
    sessions = []
    for entry in sorted(base.iterdir()):
        json_path = entry / "session.json"
        if json_path.exists():
            try:
                sessions.append(load_session(user_id, entry.name))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions


def load_session(user_id: int, session_id: str) -> dict:
    json_path = _session_json_path(user_id, session_id)
    if not json_path.exists():
        raise FileNotFoundError(f"Oturum bulunamadı: {session_id}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(user_id: int, session_id: str, session: dict) -> None:
    session["updated_at"] = _now_iso()
    json_path = _session_json_path(user_id, session_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def delete_session(user_id: int, session_id: str) -> None:
    import shutil
    d = _session_dir(user_id, session_id)
    if d.exists():
        shutil.rmtree(d)


def screen_image_path(user_id: int, session_id: str, index: int, ext: str = ".png") -> Path:
    return _screens_dir(user_id, session_id) / f"{index}{ext}"


def add_screen(user_id: int, session_id: str, image_bytes: bytes, ext: str = ".png", note: str = "") -> dict:
    session = load_session(user_id, session_id)
    index = len(session["screens"])
    _screens_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    screen_image_path(user_id, session_id, index, ext).write_bytes(image_bytes)
    session["screens"].append({
        "index": index,
        "image_ext": ext,
        "user_note": note,
        "candidate_titles": [],
        "screen_summary": "",
        "parse_error": False,
    })
    save_session(user_id, session_id, session)
    return session


def _reindex_and_rename_screens(user_id: int, session_id: str, session: dict) -> None:
    """Ekranlar yer değiştirdikten sonra dosya adlarını da yeni index'e göre yeniden adlandırır."""
    tmp_paths = []
    for new_idx, screen in enumerate(session["screens"]):
        old_path = screen_image_path(user_id, session_id, screen["index"], screen["image_ext"])
        tmp_path = old_path.with_suffix(old_path.suffix + f".tmp{new_idx}")
        old_path.rename(tmp_path)
        tmp_paths.append((tmp_path, new_idx))
    for tmp_path, new_idx in tmp_paths:
        screen = session["screens"][new_idx]
        final_path = screen_image_path(user_id, session_id, new_idx, screen["image_ext"])
        tmp_path.rename(final_path)
        screen["index"] = new_idx


def reorder_screens(user_id: int, session_id: str, order: list) -> dict:
    session = load_session(user_id, session_id)
    if sorted(order) != list(range(len(session["screens"]))):
        raise ValueError("Geçersiz sıralama: her index tam olarak bir kez geçmeli")
    session["screens"] = [session["screens"][i] for i in order]
    _reindex_and_rename_screens(user_id, session_id, session)
    save_session(user_id, session_id, session)
    return session


def update_screen_note(user_id: int, session_id: str, index: int, note: str) -> dict:
    session = load_session(user_id, session_id)
    session["screens"][index]["user_note"] = note
    save_session(user_id, session_id, session)
    return session


def delete_screen(user_id: int, session_id: str, index: int) -> dict:
    session = load_session(user_id, session_id)
    screen = session["screens"][index]
    screen_image_path(user_id, session_id, index, screen["image_ext"]).unlink(missing_ok=True)
    del session["screens"][index]
    _reindex_and_rename_screens(user_id, session_id, session)
    save_session(user_id, session_id, session)
    return session
