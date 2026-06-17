"""
Admin Users Router
------------------
Kullanici yonetimi (CRUD) + proje bazli yetkilendirme.
Sadece admin kullanicilar erisebilir.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from database import get_db
from models.db_models import User, Repository, UserWorkspace, UserProjectPermission, ScenarioSharePermission, Scenario
from routers.auth import require_admin
from services.auth_service import auth_service
from services import git_service

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=4)
    full_name: Optional[str] = None
    role: str = Field(default="user")  # user | admin


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


class PermissionSet(BaseModel):
    repository_id: int
    permission: str = Field(default="view")  # view | edit


class ScenarioShareSet(BaseModel):
    owner_user_id: int            # senaryosu paylaşılacak kullanıcı
    permission: str = Field(default="view_run")  # view_run | view_edit_run


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _user_dict(u: User, db: Session) -> dict:
    ws_count = db.query(UserWorkspace).filter_by(user_id=u.id).count()
    perms = db.query(UserProjectPermission).filter_by(user_id=u.id).all()
    return {
        "id":            u.id,
        "username":      u.username,
        "email":         u.email,
        "full_name":     u.full_name,
        "role":          u.role,
        "created_at":    u.created_at.isoformat() if u.created_at else None,
        "last_login":    u.last_login.isoformat() if u.last_login else None,
        "workspace_count": ws_count,
        "permissions":   [
            {
                "repository_id":   p.repository_id,
                "repository_name": p.repository.name if p.repository else "?",
                "permission":      p.permission,
            }
            for p in perms
        ],
    }


def _setup_workspaces_for_user(user_id: int, username: str, db_url: str):
    """
    Yeni kullanicinin tum repolar icin workspace'ini olustur.
    BackgroundTask olarak calisir.
    """
    from database import SessionLocal
    db = SessionLocal()
    try:
        repos = db.query(Repository).all()
        for repo in repos:
            # Zaten varsa atla
            existing = db.query(UserWorkspace).filter_by(
                user_id=user_id, repository_id=repo.id
            ).first()
            if existing and existing.is_cloned:
                continue

            branch_name = f"user-{username}"
            local_path  = Path(git_service.WORKSPACES_BASE) / str(user_id) / _slug(repo.name)

            try:
                git_service.clone_repository(
                    repo_url=repo.repo_url,
                    local_path=local_path,
                    username=repo.git_username,
                    token=repo.git_token,
                )
                git_service.create_user_branch(local_path, branch_name)

                if not existing:
                    ws = UserWorkspace(
                        user_id=user_id,
                        repository_id=repo.id,
                        local_path=str(local_path),
                        branch_name=branch_name,
                        is_cloned=True,
                        cloned_at=datetime.utcnow(),
                    )
                    db.add(ws)
                else:
                    existing.is_cloned  = True
                    existing.local_path = str(local_path)
                    existing.branch_name = branch_name
                    existing.cloned_at  = datetime.utcnow()
                db.commit()
                print(f"[workspace] {username} / {repo.name} hazir")
            except Exception as e:
                print(f"[workspace] {username} / {repo.name} HATA: {e}")
    finally:
        db.close()


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9_-]", "-", name.lower())[:64]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/")
async def list_users(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    users = db.query(User).order_by(User.created_at).all()
    return {"users": [_user_dict(u, db) for u in users]}


@router.post("/", status_code=201)
async def create_user(
    body: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(400, "Bu kullanici adi zaten kullaniliyor")
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "Bu e-posta zaten kayitli")
    if body.role not in ("user", "admin"):
        raise HTTPException(400, "Rol 'user' veya 'admin' olmali")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=auth_service.hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Workspace'leri arka planda olustur
    background_tasks.add_task(_setup_workspaces_for_user, user.id, user.username, "")

    return {"success": True, "user": _user_dict(user, db)}


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")

    if body.email is not None:
        conflict = db.query(User).filter(
            User.email == body.email, User.id != user_id
        ).first()
        if conflict:
            raise HTTPException(400, "Bu e-posta zaten kullaniliyor")
        user.email = body.email

    if body.full_name is not None:
        user.full_name = body.full_name

    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(400, "Gecersiz rol")
        user.role = body.role

    if body.password:
        user.hashed_password = auth_service.hash_password(body.password)

    db.commit()
    db.refresh(user)
    return {"success": True, "user": _user_dict(user, db)}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")
    if user.role == "admin":
        # En az bir admin kalmali
        admin_count = db.query(User).filter_by(role="admin").count()
        if admin_count <= 1:
            raise HTTPException(400, "Son admin silinemez")

    db.delete(user)
    db.commit()
    return {"success": True}


# ─── Workspace Setup ──────────────────────────────────────────────────────────

@router.post("/{user_id}/setup-workspace")
async def setup_workspace(
    user_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")
    background_tasks.add_task(_setup_workspaces_for_user, user.id, user.username, "")
    return {"success": True, "message": f"{user.username} icin workspace kurulumu baslatildi"}


# ─── Permissions ──────────────────────────────────────────────────────────────

@router.get("/{user_id}/permissions")
async def get_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")

    perms = db.query(UserProjectPermission).filter_by(user_id=user_id).all()
    repos = db.query(Repository).all()

    return {
        "user_id": user_id,
        "username": user.username,
        "permissions": [
            {
                "repository_id":   p.repository_id,
                "repository_name": p.repository.name if p.repository else "?",
                "permission":      p.permission,
                "granted_at":      p.granted_at.isoformat() if p.granted_at else None,
            }
            for p in perms
        ],
        "all_repositories": [
            {"id": r.id, "name": r.name, "repo_type": r.repo_type}
            for r in repos
        ],
    }


@router.post("/{user_id}/permissions")
async def set_permission(
    user_id: int,
    body: PermissionSet,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")

    repo = db.query(Repository).filter_by(id=body.repository_id).first()
    if not repo:
        raise HTTPException(404, "Repository bulunamadi")

    if body.permission not in ("view", "edit"):
        raise HTTPException(400, "Yetki 'view' veya 'edit' olmali")

    existing = db.query(UserProjectPermission).filter_by(
        user_id=user_id, repository_id=body.repository_id
    ).first()

    if existing:
        existing.permission = body.permission
        existing.granted_at = datetime.utcnow()
        existing.granted_by = admin.id
    else:
        perm = UserProjectPermission(
            user_id=user_id,
            repository_id=body.repository_id,
            permission=body.permission,
            granted_by=admin.id,
            granted_at=datetime.utcnow(),
        )
        db.add(perm)

    db.commit()
    return {"success": True, "permission": body.permission}


@router.delete("/{user_id}/permissions/{repo_id}")
async def revoke_permission(
    user_id: int,
    repo_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    perm = db.query(UserProjectPermission).filter_by(
        user_id=user_id, repository_id=repo_id
    ).first()
    if not perm:
        raise HTTPException(404, "Yetki bulunamadi")
    db.delete(perm)
    db.commit()
    return {"success": True}


# ─── Senaryo Paylaşım Yetkileri ───────────────────────────────────────────────

@router.get("/{user_id}/scenario-access")
async def get_scenario_access(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Kullanıcının hangi diğer kullanıcıların senaryolarına erişimi var."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "Kullanici bulunamadi")

    shares = db.query(ScenarioSharePermission).filter_by(grantee_user_id=user_id).all()
    all_users = db.query(User).filter(User.id != user_id).all()

    return {
        "user_id": user_id,
        "username": user.username,
        "accesses": [
            {
                "id":            s.id,
                "owner_user_id": s.owner_user_id,
                "owner_username": s.owner.username if s.owner else "?",
                "permission":    s.permission,
                "granted_at":    s.granted_at.isoformat() if s.granted_at else None,
            }
            for s in shares
        ],
        "all_users": [{"id": u.id, "username": u.username, "full_name": u.full_name} for u in all_users],
    }


@router.post("/{user_id}/scenario-access")
async def set_scenario_access(
    user_id: int,
    body: ScenarioShareSet,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Kullanıcıya başka bir kullanıcının senaryolarına erişim ver."""
    if db.query(User).filter_by(id=user_id).first() is None:
        raise HTTPException(404, "Kullanici bulunamadi")
    if db.query(User).filter_by(id=body.owner_user_id).first() is None:
        raise HTTPException(404, "Hedef kullanici bulunamadi")
    if user_id == body.owner_user_id:
        raise HTTPException(400, "Kullanici kendi senaryolarina zaten erisebilir")
    if body.permission not in ("view_run", "view_edit_run"):
        raise HTTPException(400, "Yetki 'view_run' veya 'view_edit_run' olmali")

    existing = db.query(ScenarioSharePermission).filter_by(
        grantee_user_id=user_id, owner_user_id=body.owner_user_id
    ).first()
    if existing:
        existing.permission = body.permission
        existing.granted_at = datetime.utcnow()
        existing.granted_by = admin.id
    else:
        db.add(ScenarioSharePermission(
            granted_by=admin.id,
            grantee_user_id=user_id,
            owner_user_id=body.owner_user_id,
            permission=body.permission,
            granted_at=datetime.utcnow(),
        ))
    db.commit()
    return {"success": True}


@router.delete("/{user_id}/scenario-access/{access_id}")
async def revoke_scenario_access(
    user_id: int,
    access_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    share = db.query(ScenarioSharePermission).filter_by(
        id=access_id, grantee_user_id=user_id
    ).first()
    if not share:
        raise HTTPException(404, "Erisim yetkisi bulunamadi")
    db.delete(share)
    db.commit()
    return {"success": True}
