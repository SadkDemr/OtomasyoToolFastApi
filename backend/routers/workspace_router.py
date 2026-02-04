"""
User Workspace Router
---------------------
Kullanıcıların repository'leri clone etmesi, commit/push yapması.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from database import get_db
from models.db_models import Repository, UserWorkspace, User, Scenario
from routers.auth import get_current_user
from services import git_service
import json


# Action mapper için import
import sys
from pathlib import Path as PathLib
sys.path.insert(0, str(PathLib(__file__).parent.parent / "services"))
try:
    from action_mapper import (
        get_available_actions,
        get_locator_types,
        step_to_display,
        validate_step,
        generate_selenium_code
    )
except ImportError:
    # Fallback - action_mapper service'i bulunamazsa
    get_available_actions = lambda **kwargs: []
    get_locator_types = lambda **kwargs: []
    step_to_display = lambda step, lang: str(step)
    validate_step = lambda step: {"valid": True, "errors": []}
    generate_selenium_code = lambda steps, lang: ""


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CloneRequest(BaseModel):
    repository_id: int = Field(..., description="Clone edilecek repository ID")


class CommitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=200, description="Commit mesajı")


class WorkspaceResponse(BaseModel):
    id: int
    repository_id: int
    repository_name: str
    repository_type: str
    branch_name: str
    is_cloned: bool
    has_changes: bool
    cloned_at: Optional[str]
    last_pulled: Optional[str]
    last_pushed: Optional[str]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/catalog")
async def get_repository_catalog(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Repository kataloğu (herkes görebilir).
    Hangi repo'ların mevcut olduğunu ve kullanıcının clone'layıp clone'lamadığını gösterir.
    """
    all_repos = db.query(Repository).all()
    user_workspaces = db.query(UserWorkspace).filter_by(user_id=current_user.id).all()
    
    # User workspace map
    ws_map = {ws.repository_id: ws for ws in user_workspaces}
    
    catalog = []
    for repo in all_repos:
        ws = ws_map.get(repo.id)
        
        catalog.append({
            "id": repo.id,
            "name": repo.name,
            "repo_url": repo.repo_url,
            "repo_type": repo.repo_type,
            "description": repo.description,
            "is_cloned_by_me": ws is not None and ws.is_cloned,
            "my_workspace_id": ws.id if ws else None,
            "my_branch": ws.branch_name if ws else None,
            "has_changes": ws.has_changes if ws else False
        })
    
    return {"catalog": catalog}


@router.get("/my")
async def get_my_workspaces(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Kullanıcının clone'ladığı repository'ler."""
    workspaces = db.query(UserWorkspace).filter_by(user_id=current_user.id).all()
    
    result = []
    for ws in workspaces:
        result.append({
            "id": ws.id,
            "repository_id": ws.repository_id,
            "repository_name": ws.repository.name,
            "repository_type": ws.repository.repo_type,
            "branch_name": ws.branch_name,
            "is_cloned": ws.is_cloned,
            "has_changes": ws.has_changes,
            "cloned_at": ws.cloned_at.isoformat() if ws.cloned_at else None,
            "last_pulled": ws.last_pulled.isoformat() if ws.last_pulled else None,
            "last_pushed": ws.last_pushed.isoformat() if ws.last_pushed else None
        })
    
    return {"workspaces": result}


@router.post("/clone", status_code=201)
async def clone_repository(
    body: CloneRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Repository'yi kullanıcının workspace'ine clone et.
    
    İşlemler:
    1. Repo'yu clone et
    2. user-{username} branch'i oluştur
    3. DB'ye kaydet
    """
    # Repo var mı?
    repo = db.query(Repository).filter_by(id=body.repository_id).first()
    if not repo:
        raise HTTPException(404, detail="Repository bulunamadı")
    
    # Zaten clone'ladı mı?
    existing = db.query(UserWorkspace).filter_by(
        user_id=current_user.id,
        repository_id=body.repository_id
    ).first()
    
    if existing:
        raise HTTPException(400, detail="Bu repository zaten clone'landı")
    
    # Local path oluştur: /workspaces/{user_id}/{repo_name}/
    import re
    repo_slug = re.sub(r"[^a-z0-9\-]", "", repo.name.lower().replace(" ", "-"))
    local_path = Path(git_service.WORKSPACES_BASE) / str(current_user.id) / repo_slug
    
    if local_path.exists():
        raise HTTPException(400, detail="Bu klasör zaten mevcut")
    
    # Branch adı: user-{username}
    branch_name = f"user-{current_user.username}"
    
    # Workspace kaydı oluştur (önce DB'ye)
    workspace = UserWorkspace(
        user_id=current_user.id,
        repository_id=repo.id,
        local_path=str(local_path),
        branch_name=branch_name,
        is_cloned=False,
        has_changes=False
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    
    # Clone işlemi (background task)
    def clone_task():
        try:
            # Clone (boş repo desteği ile)
            result = git_service.clone_repository(
                repo_url=repo.repo_url,
                local_path=local_path,
                branch="main",  # Otomatik tespit edilecek
                username=repo.git_username,
                token=repo.git_token
            )
            
            # User branch oluştur
            git_service.create_user_branch(local_path, branch_name)
            
            # DB güncelle
            workspace.is_cloned = True
            workspace.cloned_at = datetime.now(timezone.utc)
            db.commit()
            
            print(f"Clone successful: {result}")
            
        except Exception as e:
            # Hata olursa workspace kaydını sil
            db.delete(workspace)
            db.commit()
            print(f"Clone error: {e}")
    
    background_tasks.add_task(clone_task)
    
    return {
        "message": "Clone işlemi başlatıldı",
        "workspace_id": workspace.id,
        "branch": branch_name
    }


@router.get("/{workspace_id}/status")
async def get_workspace_status(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Workspace git status."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    if not ws.is_cloned:
        return {
            "is_cloned": False,
            "message": "Clone işlemi devam ediyor..."
        }
    
    local_path = Path(ws.local_path)
    
    try:
        status = git_service.get_status(local_path)
        
        # DB güncelle
        ws.has_changes = status["has_changes"]
        db.commit()
        
        return {
            "is_cloned": True,
            "branch": git_service.get_current_branch(local_path),
            **status
        }
    except git_service.GitError as e:
        raise HTTPException(500, detail=str(e))


@router.post("/{workspace_id}/pull")
async def pull_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Main branch'ten pull yap (merge).
    ⚠️ Push öncesi mutlaka pull yapılmalı!
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı veya clone edilmedi")
    
    local_path = Path(ws.local_path)
    
    try:
        result = git_service.pull_from_main(local_path, main_branch="main")
        
        if result["success"]:
            ws.last_pulled = datetime.now(timezone.utc)
            db.commit()
        
        return result
    
    except git_service.GitError as e:
        raise HTTPException(500, detail=str(e))


@router.post("/{workspace_id}/commit")
async def commit_workspace(
    workspace_id: int,
    body: CommitRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Değişiklikleri commit et."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    
    try:
        # Commit
        author = f"{current_user.username} <{current_user.email or 'no-email@test.com'}>"
        git_service.commit_changes(local_path, body.message, author=author)
        
        # Status güncelle
        status = git_service.get_status(local_path)
        ws.has_changes = status["has_changes"]
        db.commit()
        
        return {"message": "Değişiklikler commit edildi"}
    
    except git_service.GitError as e:
        raise HTTPException(500, detail=str(e))


@router.post("/{workspace_id}/push")
async def push_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Commit'leri remote'a push et.
    ⚠️ Önce pull yapılmalı!
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    repo = ws.repository
    local_path = Path(ws.local_path)
    
    try:
        # Push
        git_service.push_branch(
            local_path,
            ws.branch_name,
            username=repo.git_username,
            token=repo.git_token
        )
        
        # Timestamp güncelle
        ws.last_pushed = datetime.now(timezone.utc)
        ws.has_changes = False
        db.commit()
        
        return {"message": f"Branch '{ws.branch_name}' push edildi"}
    
    except git_service.GitError as e:
        raise HTTPException(500, detail=str(e))


@router.get("/{workspace_id}/history")
async def get_workspace_history(
    workspace_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Commit history."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    
    try:
        commits = git_service.get_commit_history(local_path, limit=limit)
        return {"commits": commits}
    except git_service.GitError as e:
        raise HTTPException(500, detail=str(e))


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Workspace'i sil (lokal klasör + DB kaydı).
    ⚠️ Uncommitted değişiklikler kaybolur!
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    # Klasörü sil
    local_path = Path(ws.local_path)
    if local_path.exists():
        git_service.delete_workspace(local_path)
    
    # DB'den sil
    db.delete(ws)
    db.commit()
    
    return {"message": "Workspace silindi"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FILE OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{workspace_id}")
async def get_workspace_info(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Workspace bilgilerini getir (repository tipi dahil).
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    return {
        "id": ws.id,
        "repository_id": ws.repository_id,
        "repository_name": ws.repository.name,
        "repository_type": ws.repository.repo_type,
        "branch_name": ws.branch_name,
        "is_cloned": ws.is_cloned,
        "has_changes": ws.has_changes
    }


@router.get("/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Workspace'deki dosyaları tree yapısında listele.
    
    Returns:
        {
            "tree": [
                {"name": "scenarios", "type": "folder", "children": [...]},
                {"name": "README.md", "type": "file", "path": "README.md"}
            ]
        }
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    
    def build_tree(dir_path: Path, relative_to: Path):
        """Recursive tree builder"""
        items = []
        
        try:
            for item in sorted(dir_path.iterdir()):
                # .git klasörünü atla
                if item.name.startswith('.'):
                    continue
                
                rel_path = str(item.relative_to(relative_to)).replace('\\', '/')
                
                if item.is_dir():
                    items.append({
                        "name": item.name,
                        "type": "folder",
                        "path": rel_path,
                        "children": build_tree(item, relative_to)
                    })
                else:
                    # Sadece .json, .md, .txt dosyalarını göster
                    if item.suffix in ['.json', '.md', '.txt']:
                        items.append({
                            "name": item.name,
                            "type": "file",
                            "path": rel_path,
                            "size": item.stat().st_size
                        })
        except PermissionError:
            pass
        
        return items
    
    tree = build_tree(local_path, local_path)
    
    return {
        "workspace_id": workspace_id,
        "tree": tree
    }


class FileContentRequest(BaseModel):
    path: str = Field(..., description="Dosya yolu (relative)")


@router.post("/{workspace_id}/files/read")
async def read_workspace_file(
    workspace_id: int,
    body: FileContentRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Workspace'deki bir dosyayı oku.
    
    Args:
        path: Relative dosya yolu (örn: "scenarios/1_Login.json")
    
    Returns:
        {"content": "...", "path": "..."}
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    file_path = local_path / body.path
    
    # Security: Path traversal attack önleme
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(local_path.resolve())):
            raise HTTPException(403, detail="Geçersiz dosya yolu")
    except:
        raise HTTPException(403, detail="Geçersiz dosya yolu")
    
    if not file_path.exists():
        raise HTTPException(404, detail="Dosya bulunamadı")
    
    if not file_path.is_file():
        raise HTTPException(400, detail="Bu bir dosya değil")
    
    try:
        content = file_path.read_text(encoding='utf-8')
        return {
            "path": body.path,
            "content": content,
            "size": len(content)
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Dosya okunamadı: {str(e)}")


class FileWriteRequest(BaseModel):
    path: str = Field(..., description="Dosya yolu (relative)")
    content: str = Field(..., description="Dosya içeriği")


@router.post("/{workspace_id}/files/write")
async def write_workspace_file(
    workspace_id: int,
    body: FileWriteRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Workspace'deki bir dosyaya yaz (auto-save).
    
    Args:
        path: Relative dosya yolu
        content: Dosya içeriği
    
    Returns:
        {"success": true, "message": "..."}
    """
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    file_path = local_path / body.path
    
    # Security: Path traversal attack önleme
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(local_path.resolve())):
            raise HTTPException(403, detail="Geçersiz dosya yolu")
    except:
        raise HTTPException(403, detail="Geçersiz dosya yolu")
    
    # Parent klasörü oluştur
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        file_path.write_text(body.content, encoding='utf-8')
        
        # Git status güncelle
        status = git_service.get_status(local_path)
        ws.has_changes = status["has_changes"]
        db.commit()
        
        return {
            "success": True,
            "message": "Dosya kaydedildi",
            "has_changes": status["has_changes"]
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Dosya yazılamadı: {str(e)}")


class FileDeleteRequest(BaseModel):
    path: str = Field(..., description="Silinecek dosya/klasör yolu")


@router.post("/{workspace_id}/files/delete")
async def delete_workspace_file(
    workspace_id: int,
    body: FileDeleteRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Workspace'deki bir dosyayı veya klasörü sil."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    target_path = local_path / body.path
    
    # Security check
    try:
        target_path = target_path.resolve()
        if not str(target_path).startswith(str(local_path.resolve())):
            raise HTTPException(403, detail="Geçersiz dosya yolu")
    except:
        raise HTTPException(403, detail="Geçersiz dosya yolu")
    
    if not target_path.exists():
        raise HTTPException(404, detail="Dosya/klasör bulunamadı")
    
    try:
        import shutil
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
        
        # Git status güncelle
        status = git_service.get_status(local_path)
        ws.has_changes = status["has_changes"]
        db.commit()
        
        return {
            "success": True,
            "message": "Silindi"
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Silinemedi: {str(e)}")


class FileRenameRequest(BaseModel):
    old_path: str = Field(..., description="Eski dosya yolu")
    new_name: str = Field(..., description="Yeni dosya/klasör adı")


@router.post("/{workspace_id}/files/rename")
async def rename_workspace_file(
    workspace_id: int,
    body: FileRenameRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Workspace'deki bir dosyayı veya klasörü yeniden adlandır."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    old_path = local_path / body.old_path
    
    # Security check
    try:
        old_path = old_path.resolve()
        if not str(old_path).startswith(str(local_path.resolve())):
            raise HTTPException(403, detail="Geçersiz dosya yolu")
    except:
        raise HTTPException(403, detail="Geçersiz dosya yolu")
    
    if not old_path.exists():
        raise HTTPException(404, detail="Dosya/klasör bulunamadı")
    
    # Yeni path oluştur
    new_path = old_path.parent / body.new_name
    
    if new_path.exists():
        raise HTTPException(400, detail="Bu isimde bir dosya/klasör zaten var")
    
    try:
        old_path.rename(new_path)
        
        # Git status güncelle
        status = git_service.get_status(local_path)
        ws.has_changes = status["has_changes"]
        db.commit()
        
        return {
            "success": True,
            "message": "Yeniden adlandırıldı",
            "new_path": str(new_path.relative_to(local_path)).replace('\\', '/')
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Yeniden adlandırılamadı: {str(e)}")


class FolderCreateRequest(BaseModel):
    path: str = Field(..., description="Oluşturulacak klasör yolu")


@router.post("/{workspace_id}/folders/create")
async def create_workspace_folder(
    workspace_id: int,
    body: FolderCreateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Workspace'de yeni klasör oluştur."""
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı")
    
    local_path = Path(ws.local_path)
    folder_path = local_path / body.path
    
    # Security check
    try:
        folder_path = folder_path.resolve()
        if not str(folder_path).startswith(str(local_path.resolve())):
            raise HTTPException(403, detail="Geçersiz klasör yolu")
    except:
        raise HTTPException(403, detail="Geçersiz klasör yolu")
    
    if folder_path.exists():
        raise HTTPException(400, detail="Bu klasör zaten var")
    
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
        
        # .gitkeep ekle (boş klasörler git'te takip edilmiyor)
        (folder_path / ".gitkeep").touch()
        
        return {
            "success": True,
            "message": "Klasör oluşturuldu"
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Klasör oluşturulamadı: {str(e)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACTION MAPPER ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/actions")
async def get_actions_list(
    lang: str = "tr",
    type: Optional[str] = None
):
    """
    Kullanılabilir action'ları listele.
    
    Args:
        lang: tr veya en
        type: web, mobile veya None
    
    Returns:
        {"actions": [...], "locators": [...]}
    """
    return {
        "actions": get_available_actions(lang=lang, filter_type=type),
        "locators": get_locator_types(lang=lang)
    }


class StepValidateRequest(BaseModel):
    step: Dict[str, Any] = Field(..., description="Validate edilecek step")


@router.post("/actions/validate")
async def validate_action_step(body: StepValidateRequest):
    """Step'i validate et."""
    return validate_step(body.step)


class CodeGenerateRequest(BaseModel):
    steps: List[Dict[str, Any]] = Field(..., description="Step listesi")
    lang: str = Field(default="python", description="Kod dili")
    type: str = Field(default="selenium", description="selenium veya appium")


@router.post("/actions/generate-code")
async def generate_code(body: CodeGenerateRequest):
    """
    JSON steps'lerden Selenium/Appium kodu üret.
    
    Returns:
        {"code": "...", "language": "python"}
    """
    code = generate_selenium_code(body.steps, lang=body.lang)
    
    return {
        "code": code,
        "language": body.lang,
        "type": body.type
    }


@router.post("/{workspace_id}/sync-scenarios")
async def sync_scenarios_to_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Database'deki tüm senaryoları workspace'e JSON dosyalar olarak aktar.
    
    İşlemler:
    1. scenarios/ klasörü oluştur
    2. Her senaryoyu {scenario_id}_{scenario_name}.json olarak kaydet
    3. Commit & Push yap
    """
    # Workspace kontrolü
    ws = db.query(UserWorkspace).filter_by(
        id=workspace_id,
        user_id=current_user.id
    ).first()
    
    if not ws or not ws.is_cloned:
        raise HTTPException(404, detail="Workspace bulunamadı veya clone edilmedi")
    
    local_path = Path(ws.local_path)
    scenarios_dir = local_path / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)
    
    # Kullanıcının tüm senaryolarını al
    scenarios = db.query(Scenario).filter_by(user_id=current_user.id).all()
    
    if not scenarios:
        raise HTTPException(400, detail="Hiç senaryo bulunamadı")
    
    synced_count = 0
    
    try:
        for scenario in scenarios:
            # Dosya adı: {id}_{name}.json
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in scenario.name)
            file_name = f"{scenario.id}_{safe_name}.json"
            file_path = scenarios_dir / file_name
            
            # Senaryo verisini hazırla
            scenario_data = {
                "id": scenario.id,
                "name": scenario.name,
                "description": scenario.description or "",
                "type": scenario.type or "web",
                "natural_steps": scenario.natural_steps or [],
                "steps_json": scenario.steps_json or {},
                "config_json": scenario.config_json or {},
                "tags": getattr(scenario, 'tags', []) or [],  # tags field'i yoksa []
                "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
                "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None
            }
            
            # JSON dosyası olarak kaydet
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(scenario_data, f, indent=2, ensure_ascii=False)
            
            synced_count += 1
        
        # README.md güncelle
        readme_path = local_path / "README.md"
        readme_content = f"""# Test Automation Scenarios

Bu repository {synced_count} adet test senaryosu içermektedir.

## Senaryolar

`scenarios/` klasöründe JSON formatında saklanmaktadır.

### Senaryo Formatı

```json
{{
  "id": 1,
  "name": "Senaryo Adı",
  "description": "Açıklama",
  "type": "web|mobile|desktop",
  "natural_steps": ["Adım 1", "Adım 2"],
  "steps_json": {{}},
  "config_json": {{}},
  "tags": ["tag1", "tag2"]
}}
```

Son güncelleme: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        readme_path.write_text(readme_content, encoding='utf-8')
        
        # Commit
        author = f"{current_user.username} <{current_user.email or 'no-email@test.com'}>"
        git_service.commit_changes(
            local_path,
            f"Sync {synced_count} scenarios from database",
            author=author
        )
        
        # Push
        repo = ws.repository
        git_service.push_branch(
            local_path,
            ws.branch_name,
            username=repo.git_username,
            token=repo.git_token
        )
        
        # DB güncelle
        ws.last_pushed = datetime.now(timezone.utc)
        ws.has_changes = False
        db.commit()
        
        return {
            "success": True,
            "message": f"{synced_count} senaryo başarıyla sync edildi",
            "synced_count": synced_count,
            "branch": ws.branch_name
        }
        
    except git_service.GitError as e:
        raise HTTPException(500, detail=f"Git hatası: {str(e)}")
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Sync error: {error_detail}")
        raise HTTPException(500, detail=f"Sync hatası: {str(e)}")