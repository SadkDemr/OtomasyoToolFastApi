"""
Admin Router - Repository Management
-------------------------------------
Admin kullanıcılar için repository CRUD işlemleri.
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional

from database import get_db
from models.db_models import Repository, User
from routers.auth import get_current_user, require_admin


router = APIRouter(prefix="/admin/repositories", tags=["admin-repositories"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Mobil iOS, Web, etc.")
    repo_url: str = Field(..., description="Azure Repos / GitHub URL")
    repo_type: str = Field(..., description="mobile-ios | mobile-android | web | desktop | api")
    description: Optional[str] = Field(default="", max_length=500)
    git_username: Optional[str] = None
    git_token: Optional[str] = None


class RepositoryUpdate(BaseModel):
    name: Optional[str] = None
    repo_url: Optional[str] = None
    description: Optional[str] = None
    git_username: Optional[str] = None
    git_token: Optional[str] = None


class RepositoryResponse(BaseModel):
    id: int
    name: str
    repo_url: str
    repo_type: str
    description: str
    created_by: int
    created_at: str
    workspace_count: int = 0  # Kaç kullanıcı clone'ladı
    
    class Config:
        from_attributes = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/", status_code=201)
async def create_repository(
    body: RepositoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)  # Admin kontrolü
):
    """
    Yeni repository ekle (sadece admin).
    
    Örnek:
    {
        "name": "Mobil iOS Testleri",
        "repo_url": "https://dev.azure.com/company/project/_git/ios-tests",
        "repo_type": "mobile-ios",
        "description": "iOS uygulaması senaryoları",
        "git_username": "service-account",
        "git_token": "pat_token_here"
    }
    """
    # Duplicate kontrolü
    existing = db.query(Repository).filter_by(name=body.name).first()
    if existing:
        raise HTTPException(400, detail=f"Repository '{body.name}' zaten mevcut")
    
    existing_url = db.query(Repository).filter_by(repo_url=body.repo_url).first()
    if existing_url:
        raise HTTPException(400, detail="Bu URL zaten kayıtlı")
    
    # Tip kontrolü
    valid_types = ["mobile-ios", "mobile-android", "web", "desktop", "api"]
    if body.repo_type not in valid_types:
        raise HTTPException(400, detail=f"Geçersiz tip. Seçenekler: {valid_types}")
    
    repo = Repository(
        name=body.name,
        repo_url=body.repo_url,
        repo_type=body.repo_type,
        description=body.description,
        git_username=body.git_username,
        git_token=body.git_token,  # ⚠️ Production'da encrypt et!
        created_by=current_user.id
    )
    
    db.add(repo)
    db.commit()
    db.refresh(repo)
    
    return {
        "id": repo.id,
        "name": repo.name,
        "repo_url": repo.repo_url,
        "repo_type": repo.repo_type,
        "created_at": repo.created_at.isoformat()
    }


@router.get("/")
async def list_repositories(
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """
    Tüm repository'leri listele (sadece admin).
    """
    repos = db.query(Repository).all()
    
    result = []
    for repo in repos:
        result.append({
            "id": repo.id,
            "name": repo.name,
            "repo_url": repo.repo_url,
            "repo_type": repo.repo_type,
            "description": repo.description,
            "created_by": repo.created_by,
            "created_at": repo.created_at.isoformat(),
            "workspace_count": len(repo.workspaces)  # Kaç kullanıcı clone'ladı
        })
    
    return {"repositories": result}


@router.get("/{repo_id}")
async def get_repository(
    repo_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Tek repository detay."""
    repo = db.query(Repository).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, detail="Repository bulunamadı")
    
    return {
        "id": repo.id,
        "name": repo.name,
        "repo_url": repo.repo_url,
        "repo_type": repo.repo_type,
        "description": repo.description,
        "git_username": repo.git_username,
        "created_by": repo.created_by,
        "created_at": repo.created_at.isoformat(),
        "workspace_count": len(repo.workspaces)
    }


@router.put("/{repo_id}")
async def update_repository(
    repo_id: int,
    body: RepositoryUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Repository bilgilerini güncelle."""
    repo = db.query(Repository).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, detail="Repository bulunamadı")
    
    if body.name is not None:
        # Duplicate kontrolü
        existing = db.query(Repository).filter(
            Repository.name == body.name,
            Repository.id != repo_id
        ).first()
        if existing:
            raise HTTPException(400, detail="Bu isim zaten kullanılıyor")
        repo.name = body.name
    
    if body.repo_url is not None:
        repo.repo_url = body.repo_url
    if body.description is not None:
        repo.description = body.description
    if body.git_username is not None:
        repo.git_username = body.git_username
    if body.git_token is not None:
        repo.git_token = body.git_token
    
    from datetime import datetime, timezone
    repo.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(repo)
    
    return {"message": "Repository güncellendi", "id": repo.id}


@router.delete("/{repo_id}")
async def delete_repository(
    repo_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """
    Repository sil.
    ⚠️ Tüm kullanıcı workspace'leri de silinecek (cascade).
    """
    repo = db.query(Repository).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, detail="Repository bulunamadı")
    
    workspace_count = len(repo.workspaces)
    
    db.delete(repo)
    db.commit()
    
    return {
        "message": "Repository silindi",
        "deleted_workspaces": workspace_count
    }


@router.get("/{repo_id}/users")
async def get_repository_users(
    repo_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Bu repository'yi kullanan kullanıcıları listele."""
    repo = db.query(Repository).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, detail="Repository bulunamadı")
    
    users = []
    for ws in repo.workspaces:
        users.append({
            "user_id": ws.user_id,
            "username": ws.user.username,
            "branch": ws.branch_name,
            "cloned_at": ws.cloned_at.isoformat() if ws.cloned_at else None,
            "last_pushed": ws.last_pushed.isoformat() if ws.last_pushed else None,
            "has_changes": ws.has_changes
        })
    
    return {"users": users}