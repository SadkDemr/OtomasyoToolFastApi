"""
Java Step Templates Router
============================
Java Generator için admin tanımlı kalıp step->komut eşleşmeleri ve platform
bazlı login blokları. GET herkese (login olmuş kullanıcı) açık — normal
kullanıcılar sadece görüntüleyebilsin diye; POST/PUT/DELETE admin'e özel.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user, require_admin
from models.db_models import User, JavaStepTemplate
from services.java_step_template_service import (
    ensure_login_seeds, build_java_from_xpath, deactivate_conflicts,
)

router = APIRouter(prefix="/admin/java-templates", tags=["admin-java-templates"])

_VALID_PLATFORMS = ("android", "ios")
_VALID_KINDS = ("step", "login")
_VALID_ACTIONS = ("click", "assert", "clear", "type", "long_press")


class JavaTemplateIn(BaseModel):
    platform:     str
    kind:         str = "step"
    trigger_text: Optional[str] = None
    input_mode:   str = "code"    # "code" | "xpath" (sadece kind="step" icin anlamli)
    java_code:    Optional[str] = None
    xpath:        Optional[str] = None
    action:       Optional[str] = "click"
    value:        Optional[str] = None
    note:         Optional[str] = None
    is_active:    bool = True


def _serialize(row: JavaStepTemplate) -> dict:
    return {
        "id":            row.id,
        "platform":      row.platform,
        "kind":          row.kind,
        "trigger_text":  row.trigger_text,
        "java_code":     row.java_code,
        "note":          row.note,
        "is_active":     row.is_active,
        "created_at":    row.created_at.isoformat() if row.created_at else None,
        "updated_at":    row.updated_at.isoformat() if row.updated_at else None,
    }


def _resolve_java_code(body: JavaTemplateIn) -> tuple[str, Optional[str]]:
    """(java_code, trigger_text) döner. Doğrulama + xpath modunda kod üretimi."""
    if body.platform not in _VALID_PLATFORMS:
        raise HTTPException(400, "platform 'android' veya 'ios' olmalı")
    if body.kind not in _VALID_KINDS:
        raise HTTPException(400, "kind 'step' veya 'login' olmalı")

    if body.kind == "login":
        if not body.java_code or not body.java_code.strip():
            raise HTTPException(400, "Login bloğu için java_code gerekli")
        return body.java_code.strip(), None

    # kind == "step"
    trigger = (body.trigger_text or "").strip()
    if not trigger:
        raise HTTPException(400, "Kalıp step için trigger_text (adım metni) gerekli")

    if body.input_mode == "xpath":
        xpath = (body.xpath or "").strip()
        if not xpath:
            raise HTTPException(400, "xpath modu için xpath gerekli")
        action = body.action or "click"
        if action not in _VALID_ACTIONS:
            raise HTTPException(400, f"Geçersiz action, biri olmalı: {', '.join(_VALID_ACTIONS)}")
        if action == "type" and not (body.value or "").strip():
            raise HTTPException(400, "'type' aksiyonu için value (yazılacak değer) gerekli")
        code = build_java_from_xpath(action, xpath, body.value, trigger, body.platform)
        return code, trigger

    if not body.java_code or not body.java_code.strip():
        raise HTTPException(400, "java_code modu için java_code gerekli")
    return body.java_code.strip(), trigger


@router.get("")
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Herkes görebilir (admin dahil normal kullanıcılar) — düzenleme yok."""
    ensure_login_seeds(db)
    rows = db.query(JavaStepTemplate).order_by(
        JavaStepTemplate.platform, JavaStepTemplate.kind, JavaStepTemplate.trigger_text
    ).all()
    return {"templates": [_serialize(r) for r in rows]}


@router.post("")
async def create_template(
    body: JavaTemplateIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    java_code, trigger_text = _resolve_java_code(body)
    row = JavaStepTemplate(
        platform=body.platform,
        kind=body.kind,
        trigger_text=trigger_text,
        java_code=java_code,
        note=(body.note or "").strip() or None,
        is_active=body.is_active,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if row.is_active:
        deactivate_conflicts(db, row.platform, row.kind, row.trigger_text, exclude_id=row.id)
    return _serialize(row)


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    body: JavaTemplateIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(JavaStepTemplate).filter(JavaStepTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Kayıt bulunamadı")
    java_code, trigger_text = _resolve_java_code(body)
    row.platform = body.platform
    row.kind = body.kind
    row.trigger_text = trigger_text
    row.java_code = java_code
    row.note = (body.note or "").strip() or None
    row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    if row.is_active:
        deactivate_conflicts(db, row.platform, row.kind, row.trigger_text, exclude_id=row.id)
    return _serialize(row)


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(JavaStepTemplate).filter(JavaStepTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Kayıt bulunamadı")
    db.delete(row)
    db.commit()
    return {"success": True}
