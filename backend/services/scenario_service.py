"""
Scenario Service - Senaryo Yonetimi (CRUD)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional
from sqlalchemy.orm import Session

from models.db_models import Scenario, TestResult
from models.schemas import ScenarioCreate, ScenarioUpdate


class ScenarioService:
    """Senaryo Yönetim Servisi"""
    
    def get_user_scenarios(self, db: Session, user_id: int, scenario_type: str = None) -> List[Scenario]:
        """Kullanıcının senaryolarını getir"""
        query = db.query(Scenario).filter(
            Scenario.user_id == user_id,
            Scenario.is_active == True
        )
        
        if scenario_type:
            query = query.filter(Scenario.type == scenario_type)
        
        return query.order_by(Scenario.updated_at.desc()).all()
    
    def get_scenario_by_id(self, db: Session, scenario_id: int) -> Optional[Scenario]:
        """ID ile senaryo getir"""
        return db.query(Scenario).filter(Scenario.id == scenario_id).first()
    
    def get_user_scenario(self, db: Session, user_id: int, scenario_id: int) -> Optional[Scenario]:
        """Kullanıcının belirli senaryosunu getir"""
        return db.query(Scenario).filter(
            Scenario.id == scenario_id,
            Scenario.user_id == user_id,
            Scenario.is_active == True
        ).first()
    
    def create_scenario(self, db: Session, user_id: int, data: ScenarioCreate) -> dict:
        """Yeni senaryo oluştur"""
        
        new_scenario = Scenario(
            user_id=user_id,
            name=data.name,
            description=data.description,
            type=data.type.value,
            natural_steps=data.natural_steps,
            steps_json=data.steps_json,
            config_json=data.config_json
        )
        
        db.add(new_scenario)
        db.commit()
        db.refresh(new_scenario)
        
        return {"success": True, "message": "Senaryo oluşturuldu", "scenario": new_scenario}
    
    def update_scenario(self, db: Session, user_id: int, scenario_id: int, data: ScenarioUpdate) -> dict:
        """Senaryo güncelle"""
        
        scenario = self.get_user_scenario(db, user_id, scenario_id)
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        if data.name is not None:
            scenario.name = data.name
        if data.description is not None:
            scenario.description = data.description
        if data.natural_steps is not None:
            scenario.natural_steps = data.natural_steps
        if data.steps_json is not None:
            scenario.steps_json = data.steps_json
        if data.config_json is not None:
            scenario.config_json = data.config_json
        
        db.commit()
        db.refresh(scenario)
        
        return {"success": True, "message": "Senaryo güncellendi", "scenario": scenario}
    
    def delete_scenario(self, db: Session, user_id: int, scenario_id: int) -> dict:
        """Senaryo sil (soft delete)"""
        
        scenario = self.get_user_scenario(db, user_id, scenario_id)
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        scenario.is_active = False
        db.commit()
        
        return {"success": True, "message": "Senaryo silindi"}
    
    def duplicate_scenario(self, db: Session, user_id: int, scenario_id: int, new_name: str = None) -> dict:
        """Senaryoyu kopyala"""
        
        original = self.get_user_scenario(db, user_id, scenario_id)
        if not original:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        new_scenario = Scenario(
            user_id=user_id,
            name=new_name or f"{original.name} (Kopya)",
            description=original.description,
            type=original.type,
            natural_steps=original.natural_steps,
            steps_json=original.steps_json,
            config_json=original.config_json
        )
        
        db.add(new_scenario)
        db.commit()
        db.refresh(new_scenario)
        
        return {"success": True, "message": "Senaryo kopyalandı", "scenario": new_scenario}
    
    def get_scenario_stats(self, db: Session, user_id: int) -> dict:
        """Kullanıcının senaryo istatistikleri"""
        
        scenarios = self.get_user_scenarios(db, user_id)
        
        web_count = sum(1 for s in scenarios if s.type == "web")
        mobile_count = sum(1 for s in scenarios if s.type == "mobile")
        desktop_count = sum(1 for s in scenarios if s.type == "desktop")
        
        return {
            "total": len(scenarios),
            "web": web_count,
            "mobile": mobile_count,
            "desktop": desktop_count
        }


# Singleton
scenario_service = ScenarioService()
