"""
Advanced Editor Router - Desktop/Web-Desktop Automation
--------------------------------------------------------
Image-based scenario editing için API endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import json
import base64

from database import get_db
from routers.auth import get_current_user
from models.db_models import User

# Services
try:
    from services.image_service import image_service
    IMAGE_SERVICE = True
except ImportError:
    IMAGE_SERVICE = False
    print("[ADVANCED] ImageService yüklenemedi")


router = APIRouter(prefix="/api/advanced-editor", tags=["advanced-editor"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IMAGE UPLOAD & PROCESSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    max_width: int = Form(800),
    current_user: User = Depends(get_current_user)
):
    """
    Screenshot yükle ve optimize et.
    
    Returns:
        {
            "data": "base64_string",
            "format": "png",
            "width": 600,
            "height": 400,
            "size_kb": 45.2,
            "captured_at": "2024-01-15T10:30:00"
        }
    """
    if not IMAGE_SERVICE:
        raise HTTPException(500, "ImageService kullanılamıyor")
    
    # Dosyayı oku
    try:
        contents = await file.read()
        
        # Encode ve optimize et
        result = image_service.encode_image_to_base64(
            contents,
            max_width=max_width
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(500, f"Image işleme hatası: {str(e)}")


@router.post("/create-thumbnail")
async def create_thumbnail(
    base64_data: str = Form(...),
    width: int = Form(150),
    height: int = Form(150),
    current_user: User = Depends(get_current_user)
):
    """Thumbnail oluştur."""
    if not IMAGE_SERVICE:
        raise HTTPException(500, "ImageService kullanılamıyor")
    
    try:
        thumbnail = image_service.create_thumbnail(
            base64_data,
            size=(width, height)
        )
        return {"thumbnail": thumbnail}
    except Exception as e:
        raise HTTPException(500, f"Thumbnail oluşturulamadı: {str(e)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCENARIO CRUD (Workspace-based)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/scenarios/{workspace_id}")
async def list_scenarios(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Workspace'deki advanced scenario'ları listele.
    
    Returns:
        {
            "scenarios": [
                {
                    "id": 1234567890,
                    "name": "Desktop_Login_Test",
                    "type": "desktop",
                    "step_count": 5,
                    "total_size_kb": 150.5,
                    "created_at": "2024-01-15T10:30:00"
                }
            ]
        }
    """
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    # Workspace path'inden scenario dosyalarını oku
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    scenarios_dir = workspace_path / "scenarios"
    
    if not scenarios_dir.exists():
        return {"scenarios": []}
    
    scenarios = []
    for file in scenarios_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
            
            # AdvancedScenario formatında mı?
            if "steps" in data and isinstance(data.get("steps"), list):
                step_count = len(data.get("steps", []))
                assets = data.get("assets", {})
                
                scenarios.append({
                    "id": data.get("id", 0),
                    "name": data.get("name", file.stem),
                    "type": data.get("type", "desktop"),
                    "step_count": step_count,
                    "total_size_kb": assets.get("total_size_kb", 0),
                    "created_at": data.get("created_at"),
                    "file_path": str(file.relative_to(workspace_path))
                })
        except:
            continue
    
    return {"scenarios": scenarios}


@router.get("/scenario/{workspace_id}/{scenario_name}")
async def get_scenario(
    workspace_id: int,
    scenario_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Scenario'yu getir.
    
    Returns:
        Full AdvancedScenario JSON
    """
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    # Dosyayı oku
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    file_path = workspace_path / "scenarios" / f"{scenario_name}.json"
    
    if not file_path.exists():
        raise HTTPException(404, "Scenario dosyası bulunamadı")
    
    try:
        data = json.loads(file_path.read_text(encoding='utf-8'))
        return data
    except Exception as e:
        raise HTTPException(500, f"Dosya okunamadı: {str(e)}")


@router.post("/scenario/{workspace_id}")
async def create_scenario(
    workspace_id: int,
    scenario_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Yeni scenario oluştur.
    
    Body:
        AdvancedScenario JSON
    
    Returns:
        {"success": true, "file_path": "scenarios/..."}
    """
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    # Dosya adı oluştur
    scenario_name = scenario_data.get("name", "New_Scenario")
    safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in scenario_name)
    
    # Timestamp ekle
    timestamp = int(datetime.utcnow().timestamp())
    filename = f"{timestamp}_{safe_name}.json"
    
    # Kaydet
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    scenarios_dir = workspace_path / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)
    
    file_path = scenarios_dir / filename
    
    try:
        # ID ve timestamp ekle
        scenario_data["id"] = timestamp
        scenario_data["created_at"] = datetime.utcnow().isoformat()
        scenario_data["updated_at"] = datetime.utcnow().isoformat()
        
        # Asset istatistiklerini hesapla
        if IMAGE_SERVICE:
            stats = image_service.calculate_scenario_size(scenario_data)
            scenario_data["assets"] = stats
        
        file_path.write_text(
            json.dumps(scenario_data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        
        return {
            "success": True,
            "file_path": str(file_path.relative_to(workspace_path)),
            "id": timestamp
        }
        
    except Exception as e:
        raise HTTPException(500, f"Dosya kaydedilemedi: {str(e)}")


@router.put("/scenario/{workspace_id}/{scenario_name}")
async def update_scenario(
    workspace_id: int,
    scenario_name: str,
    scenario_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Scenario güncelle."""
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    # Dosyayı güncelle
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    file_path = workspace_path / "scenarios" / f"{scenario_name}.json"
    
    if not file_path.exists():
        raise HTTPException(404, "Scenario dosyası bulunamadı")
    
    try:
        # Updated timestamp ekle
        scenario_data["updated_at"] = datetime.utcnow().isoformat()
        
        # Asset istatistiklerini güncelle
        if IMAGE_SERVICE:
            stats = image_service.calculate_scenario_size(scenario_data)
            scenario_data["assets"] = stats
        
        file_path.write_text(
            json.dumps(scenario_data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        
        return {"success": True, "message": "Scenario güncellendi"}
        
    except Exception as e:
        raise HTTPException(500, f"Güncelleme hatası: {str(e)}")


@router.delete("/scenario/{workspace_id}/{scenario_name}")
async def delete_scenario(
    workspace_id: int,
    scenario_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Scenario sil."""
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    # Dosyayı sil
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    file_path = workspace_path / "scenarios" / f"{scenario_name}.json"
    
    if not file_path.exists():
        raise HTTPException(404, "Scenario dosyası bulunamadı")
    
    try:
        file_path.unlink()
        return {"success": True, "message": "Scenario silindi"}
    except Exception as e:
        raise HTTPException(500, f"Silme hatası: {str(e)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/step/validate")
async def validate_step(
    step_data: dict,
    current_user: User = Depends(get_current_user)
):
    """
    Step'i validate et.
    
    Returns:
        {"valid": bool, "errors": [...]}
    """
    errors = []
    
    # Required fields
    if not step_data.get("id"):
        errors.append("Step ID gerekli")
    if not step_data.get("action"):
        errors.append("Action gerekli")
    if not step_data.get("strategy"):
        errors.append("Strategy gerekli")
    if not step_data.get("description"):
        errors.append("Description gerekli")
    
    # Strategy-based validation
    strategy = step_data.get("strategy")
    if strategy == "image":
        if not step_data.get("image"):
            errors.append("Image-based step için screenshot gerekli")
        elif not isinstance(step_data.get("image"), dict):
            errors.append("Image verisi geçersiz")
    
    if strategy == "locator":
        if not step_data.get("locator"):
            errors.append("Locator-based step için locator gerekli")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/actions")
async def get_available_actions():
    """
    Kullanılabilir action'ları listele.
    
    Returns:
        {
            "actions": [
                {"type": "click", "label": "Tıkla", "requires_image": true},
                {"type": "type", "label": "Yaz", "requires_image": false},
                ...
            ]
        }
    """
    actions = [
        {"type": "click", "label": "Tıkla", "requires_image": True, "has_params": ["confidence", "timeout"]},
        {"type": "double_click", "label": "Çift Tıkla", "requires_image": True, "has_params": ["confidence"]},
        {"type": "right_click", "label": "Sağ Tıkla", "requires_image": True, "has_params": ["confidence"]},
        {"type": "type", "label": "Yaz", "requires_image": False, "has_params": ["text"]},
        {"type": "wait", "label": "Bekle", "requires_image": False, "has_params": ["seconds"]},
        {"type": "assert_exists", "label": "Doğrula", "requires_image": True, "has_params": ["timeout"]},
        {"type": "launch_app", "label": "Uygulama Aç", "requires_image": False, "has_params": ["app_path"]},
        {"type": "press_key", "label": "Tuş Bas", "requires_image": False, "has_params": ["key"]},
        {"type": "scroll", "label": "Kaydır", "requires_image": False, "has_params": ["scroll_amount"]},
        {"type": "manual", "label": "Manuel Adım", "requires_image": False, "has_params": []},
    ]
    
    return {"actions": actions}


@router.get("/stats/{workspace_id}")
async def get_workspace_stats(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Workspace istatistikleri.
    
    Returns:
        {
            "total_scenarios": 5,
            "total_steps": 25,
            "total_images": 20,
            "total_size_kb": 1500.5
        }
    """
    # Workspace kontrolü
    from models.db_models import UserWorkspace
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == workspace_id,
        UserWorkspace.user_id == current_user.id
    ).first()
    
    if not workspace:
        raise HTTPException(404, "Workspace bulunamadı")
    
    from pathlib import Path
    workspace_path = Path(workspace.local_path)
    scenarios_dir = workspace_path / "scenarios"
    
    if not scenarios_dir.exists():
        return {
            "total_scenarios": 0,
            "total_steps": 0,
            "total_images": 0,
            "total_size_kb": 0
        }
    
    total_scenarios = 0
    total_steps = 0
    total_images = 0
    total_size = 0
    
    for file in scenarios_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
            if "steps" in data:
                total_scenarios += 1
                total_steps += len(data.get("steps", []))
                
                assets = data.get("assets", {})
                total_images += assets.get("total_images", 0)
                total_size += assets.get("total_size_kb", 0)
        except:
            continue
    
    return {
        "total_scenarios": total_scenarios,
        "total_steps": total_steps,
        "total_images": total_images,
        "total_size_kb": round(total_size, 2)
    }
