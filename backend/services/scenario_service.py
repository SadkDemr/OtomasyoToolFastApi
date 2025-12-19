"""
Scenario Service - Senaryo Yonetimi (CRUD) + Tree Folder
FIXED: 'steps_json' attribute error removed
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from models.db_models import Scenario, Folder
from models.schemas import ScenarioCreate, ScenarioUpdate, FolderCreate

class ScenarioService:
    
    # --- FOLDER OPERATIONS ---
    
    def create_folder(self, db: Session, user_id: int, data: FolderCreate):
        folder = Folder(name=data.name, parent_id=data.parent_id, user_id=user_id)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return folder

    def get_folders_tree(self, db: Session, user_id: int):
        return db.query(Folder).filter(
            Folder.user_id == user_id, 
            Folder.parent_id == None
        ).all()
    
    def delete_folder(self, db: Session, user_id: int, folder_id: int):
        folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
        if folder:
            db.delete(folder)
            db.commit()
            return True
        return False

    # --- SCENARIO OPERATIONS ---

    def get_user_scenarios(self, db: Session, user_id: int, folder_id: int = None):
        query = db.query(Scenario).filter(Scenario.user_id == user_id)
        if folder_id is not None:
            query = query.filter(Scenario.folder_id == folder_id)
        return query.order_by(Scenario.updated_at.desc()).all()
    
    def get_user_scenario(self, db: Session, user_id: int, scenario_id: int) -> Optional[Scenario]:
        return db.query(Scenario).filter(
            Scenario.id == scenario_id,
            Scenario.user_id == user_id
        ).first()
    
    def create_scenario(self, db: Session, user_id: int, data: ScenarioCreate) -> dict:
        new_scenario = Scenario(
            user_id=user_id,
            name=data.name,
            description=data.description,
            type=data.type,
            folder_id=data.folder_id,
            natural_steps=data.natural_steps,
            steps_json=None, # <--- DUZELTİLDİ: data.steps_json yerine None
            config_json=data.config_json,
            is_active=True
        )
        
        db.add(new_scenario)
        db.commit()
        db.refresh(new_scenario)
        
        return {"success": True, "message": "Senaryo oluşturuldu", "scenario": new_scenario}
    
    def update_scenario(self, db: Session, user_id: int, scenario_id: int, data: ScenarioUpdate) -> dict:
        scenario = self.get_user_scenario(db, user_id, scenario_id)
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        if data.name is not None: scenario.name = data.name
        if data.description is not None: scenario.description = data.description
        if data.folder_id is not None: scenario.folder_id = data.folder_id
        if data.natural_steps is not None: scenario.natural_steps = data.natural_steps
        if data.steps_json is not None: scenario.steps_json = data.steps_json
        if data.config_json is not None: scenario.config_json = data.config_json
        
        scenario.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(scenario)
        
        return {"success": True, "message": "Senaryo güncellendi", "scenario": scenario}
    
    def delete_scenario(self, db: Session, user_id: int, scenario_id: int) -> dict:
        scenario = self.get_user_scenario(db, user_id, scenario_id)
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        db.delete(scenario)
        db.commit()
        
        return {"success": True, "message": "Senaryo kalıcı olarak silindi"}
    
    def get_scenario_stats(self, db: Session, user_id: int) -> dict:
        scenarios = self.get_user_scenarios(db, user_id)
        web_count = sum(1 for s in scenarios if s.type == "web")
        mobile_count = sum(1 for s in scenarios if s.type == "mobile")
        return {
            "total": len(scenarios),
            "web": web_count,
            "mobile": mobile_count
        }

scenario_service = ScenarioService()