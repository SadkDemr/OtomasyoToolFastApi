"""
Scenarios Router - /api/scenarios/*
Senaryo CRUD islemleri
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.schemas import (
    ScenarioCreate, ScenarioUpdate, ScenarioResponse, 
    ScenarioListResponse, ScenarioType
)
from services.scenario_service import scenario_service
from routers.auth import get_current_user

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])


# ============ ENDPOINTS ============

@router.get("", response_model=ScenarioListResponse)
async def list_scenarios(
    type: Optional[str] = Query(None, description="Filtre: web, mobile, desktop"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Kullanıcının senaryolarını listele
    
    - **type**: Opsiyonel filtre (web/mobile/desktop)
    """
    
    scenarios = scenario_service.get_user_scenarios(db, current_user.id, type)
    
    return ScenarioListResponse(
        total=len(scenarios),
        scenarios=[ScenarioResponse.model_validate(s) for s in scenarios]
    )


@router.get("/stats")
async def get_stats(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryo istatistikleri
    """
    return scenario_service.get_scenario_stats(db, current_user.id)


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryo detayı getir
    """
    
    scenario = scenario_service.get_user_scenario(db, current_user.id, scenario_id)
    
    if not scenario:
        raise HTTPException(status_code=404, detail="Senaryo bulunamadı")
    
    return ScenarioResponse.model_validate(scenario)


@router.post("", response_model=ScenarioResponse)
async def create_scenario(
    data: ScenarioCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Yeni senaryo oluştur
    
    - **name**: Senaryo adı
    - **description**: Açıklama (opsiyonel)
    - **type**: web, mobile, desktop
    - **natural_steps**: Türkçe test adımları
    - **config_json**: URL, app_package vs. (JSON string)
    """
    
    result = scenario_service.create_scenario(db, current_user.id, data)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return ScenarioResponse.model_validate(result["scenario"])


@router.put("/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(
    scenario_id: int,
    data: ScenarioUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryo güncelle
    """
    
    result = scenario_service.update_scenario(db, current_user.id, scenario_id, data)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return ScenarioResponse.model_validate(result["scenario"])


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryo sil
    """
    
    result = scenario_service.delete_scenario(db, current_user.id, scenario_id)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return result


@router.post("/{scenario_id}/duplicate", response_model=ScenarioResponse)
async def duplicate_scenario(
    scenario_id: int,
    new_name: Optional[str] = Query(None, description="Yeni senaryo adı"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Senaryoyu kopyala
    """
    
    result = scenario_service.duplicate_scenario(db, current_user.id, scenario_id, new_name)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return ScenarioResponse.model_validate(result["scenario"])
