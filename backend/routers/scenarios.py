"""
Scenarios Router - /api/scenarios/*
FIXED: Type filtresi ve Folder Tree desteği
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlalchemy.orm import Session
from typing import Optional, List

from database import get_db
from models.schemas import (
    ScenarioCreate, ScenarioUpdate, ScenarioResponse,
    ScenarioListResponse, FolderCreate, FolderResponse
)
from services.scenario_service import scenario_service
from routers.auth import get_current_user
from models.db_models import Scenario

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])


# --- FOLDER ENDPOINTS ---

@router.get("/folders", response_model=List[FolderResponse])
async def get_folders(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Klasör ağacını getirir"""
    return scenario_service.get_folders_tree(db, current_user.id)


@router.post("/folders", response_model=FolderResponse)
async def create_folder(
    data: FolderCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Yeni klasör oluşturur"""
    return scenario_service.create_folder(db, current_user.id, data)


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Klasörü ve içindekileri siler"""
    success = scenario_service.delete_folder(db, current_user.id, folder_id)
    if not success:
        raise HTTPException(404, "Klasör bulunamadı")
    return {"success": True}


# --- SCENARIO ENDPOINTS ---

@router.get("", response_model=ScenarioListResponse)
async def list_scenarios(
    response: Response,
    folder_id: Optional[int] = Query(None, description="Klasör ID"),
    type: Optional[str] = Query(None, description="Senaryo tipi: web, mobile, desktop"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryoları listeler
    
    - folder_id: Belirli bir klasördeki senaryolar
    - type: web, mobile veya desktop filtrelemesi
    """
    # Cache busting
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    # Tüm senaryoları al
    scenarios = scenario_service.get_user_scenarios(db, current_user.id, folder_id)
    
    # Type filtresi uygula
    if type:
        type_lower = type.lower()
        scenarios = [s for s in scenarios if s.type and s.type.lower() == type_lower]
    
    return ScenarioListResponse(
        total=len(scenarios),
        scenarios=[ScenarioResponse.model_validate(s) for s in scenarios]
    )


@router.get("/stats")
async def get_stats(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Senaryo istatistiklerini döner"""
    return scenario_service.get_scenario_stats(db, current_user.id)


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Tek senaryo detayı"""
    scenario = scenario_service.get_user_scenario(db, current_user.id, scenario_id)
    if not scenario:
        raise HTTPException(404, "Senaryo bulunamadı")
    return ScenarioResponse.model_validate(scenario)


@router.post("", response_model=ScenarioResponse)
async def create_scenario(
    data: ScenarioCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Yeni senaryo oluştur"""
    result = scenario_service.create_scenario(db, current_user.id, data)
    return ScenarioResponse.model_validate(result["scenario"])


@router.put("/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(
    scenario_id: int,
    data: ScenarioUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Senaryo güncelle"""
    result = scenario_service.update_scenario(db, current_user.id, scenario_id, data)
    if not result["success"]:
        raise HTTPException(404, result["message"])
    return ScenarioResponse.model_validate(result["scenario"])


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Senaryo sil"""
    result = scenario_service.delete_scenario(db, current_user.id, scenario_id)
    if not result["success"]:
        raise HTTPException(404, result["message"])
    return result