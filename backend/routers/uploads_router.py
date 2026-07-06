"""
Uploads Router - /api/uploads
Kullanicilarin foto/video yuklemesi icin genel dosya alani (bug ekran goruntusu/kaydi).
"""
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User, UploadedFile as UploadedFileModel
from services.upload_validation import validate_upload

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOADS_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "uploads"


def _safe_name(filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "dosya")
    return base[-80:] or "dosya"


def _file_dict(f: "UploadedFileModel") -> dict:
    return {
        "id":                f.id,
        "user_id":           f.user_id,
        "username":          f.user.username if f.user else "?",
        "original_filename": f.original_filename,
        "file_type":         f.file_type,
        "mime_type":         f.mime_type,
        "size_bytes":        f.size_bytes,
        "note":              f.note,
        "uploaded_at":       f.uploaded_at.isoformat() if f.uploaded_at else None,
    }


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        file_type, mime_type = validate_upload(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    user_dir = UPLOADS_DIR / str(current_user.id)
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid.uuid4().hex}_{_safe_name(file.filename)}"
        dest = user_dir / stored_filename
        with open(dest, "wb") as f:
            f.write(content)
    except Exception:
        raise HTTPException(500, "Dosya kaydedilemedi")

    record = UploadedFileModel(
        user_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_type=file_type,
        mime_type=mime_type,
        size_bytes=len(content),
        note=note or None,
        uploaded_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"success": True, "file": _file_dict(record)}


@router.get("/")
async def list_uploads(
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(UploadedFileModel)
    if current_user.role == "admin":
        if user_id is not None:
            query = query.filter(UploadedFileModel.user_id == user_id)
    else:
        query = query.filter(UploadedFileModel.user_id == current_user.id)
    files = query.order_by(UploadedFileModel.uploaded_at.desc()).all()
    return {"files": [_file_dict(f) for f in files]}


@router.get("/{upload_id}/file")
async def get_upload_file(
    upload_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(UploadedFileModel).filter_by(id=upload_id).first()
    if not record:
        raise HTTPException(404, "Dosya bulunamadi")
    if record.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Bu dosyaya erisim yetkiniz yok")

    path = UPLOADS_DIR / str(record.user_id) / record.stored_filename
    if not path.exists():
        raise HTTPException(404, "Dosya diskte bulunamadi")
    return FileResponse(path, media_type=record.mime_type, filename=record.original_filename,
                         content_disposition_type="inline")


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(UploadedFileModel).filter_by(id=upload_id).first()
    if not record:
        raise HTTPException(404, "Dosya bulunamadi")
    if record.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Bu dosyayi silme yetkiniz yok")

    path = UPLOADS_DIR / str(record.user_id) / record.stored_filename
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass

    db.delete(record)
    db.commit()
    return {"success": True}
