"""
Scenarios Router - /api/scenarios/*
FIXED: Folder Tree Support & ID-based Filtering
"""

from models.db_models import Scenario
from routers.auth import get_current_user
from services.scenario_service import scenario_service
from models.schemas import (
    ScenarioCreate, ScenarioUpdate, ScenarioResponse,
    ScenarioListResponse, FolderCreate, FolderResponse
)
from database import get_db
from typing import Optional, List
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Depends, Query, Response
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])

# --- FOLDER ENDPOINTS (YENI) ---

@router.get("/folders", response_model=List[FolderResponse])
async def get_folders(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Klasor agacini getirir"""
    return scenario_service.get_folders_tree(db, current_user.id)

@router.post("/folders", response_model=FolderResponse)
async def create_folder(data: FolderCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Yeni klasor olusturur"""
    return scenario_service.create_folder(db, current_user.id, data)

@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Klasoru ve icindekileri siler"""
    success = scenario_service.delete_folder(db, current_user.id, folder_id)
    if not success: raise HTTPException(404, "Klasor bulunamadi")
    return {"success": True}


# --- SCENARIO ENDPOINTS ---

@router.get("", response_model=ScenarioListResponse)
async def list_scenarios(
    response: Response,
    folder_id: Optional[int] = Query(None), # String type yerine ID ile filtreleme
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Cache busting
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    scenarios = scenario_service.get_user_scenarios(db, current_user.id, folder_id)
    
    return ScenarioListResponse(
        total=len(scenarios),
        scenarios=[ScenarioResponse.model_validate(s) for s in scenarios]
    )


@router.get("/stats")
async def get_stats(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return scenario_service.get_scenario_stats(db, current_user.id)


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    scenario = scenario_service.get_user_scenario(
        db, current_user.id, scenario_id)
    if not scenario:
        raise HTTPException(404, "Senaryo bulunamadi")
    return ScenarioResponse.model_validate(scenario)


@router.post("", response_model=ScenarioResponse)
async def create_scenario(data: ScenarioCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    result = scenario_service.create_scenario(db, current_user.id, data)
    return ScenarioResponse.model_validate(result["scenario"])


@router.put("/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(scenario_id: int, data: ScenarioUpdate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    result = scenario_service.update_scenario(
        db, current_user.id, scenario_id, data)
    if not result["success"]:
        raise HTTPException(404, result["message"])
    return ScenarioResponse.model_validate(result["scenario"])


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    result = scenario_service.delete_scenario(db, current_user.id, scenario_id)
    if not result["success"]:
        raise HTTPException(404, result["message"])
    return result