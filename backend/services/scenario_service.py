"""
Scenario Service - Senaryo ve Klasör Yönetimi
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime

from models.db_models import Scenario, Folder
from models.schemas import ScenarioCreate, ScenarioUpdate, FolderCreate, FolderResponse


class ScenarioService:
    
    def get_folders_tree(self, db: Session, user_id: int) -> List[FolderResponse]:
        """Klasör ağacını getir"""
        folders = db.query(Folder).filter(Folder.user_id == user_id).all()
        return self._build_folder_tree(folders, None)
    
    def _build_folder_tree(self, all_folders: List[Folder], parent_id: Optional[int]) -> List[FolderResponse]:
        """Recursive klasör ağacı oluştur"""
        result = []
        for folder in all_folders:
            if folder.parent_id == parent_id:
                children = self._build_folder_tree(all_folders, folder.id)
                result.append(FolderResponse(
                    id=folder.id,
                    name=folder.name,
                    parent_id=folder.parent_id,
                    children=children
                ))
        return result
    
    def create_folder(self, db: Session, user_id: int, data: FolderCreate) -> FolderResponse:
        """Yeni klasör oluştur"""
        folder = Folder(
            name=data.name,
            parent_id=data.parent_id,
            user_id=user_id
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return FolderResponse(id=folder.id, name=folder.name, parent_id=folder.parent_id, children=[])
    
    def delete_folder(self, db: Session, user_id: int, folder_id: int) -> bool:
        """Klasörü sil"""
        folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
        if not folder:
            return False
        
        # Alt klasörleri sil
        self._delete_children(db, user_id, folder_id)
        
        # Bu klasördeki senaryoları ana dizine taşı
        db.query(Scenario).filter(Scenario.folder_id == folder_id).update({"folder_id": None})
        
        db.delete(folder)
        db.commit()
        return True
    
    def _delete_children(self, db: Session, user_id: int, parent_id: int):
        """Alt klasörleri recursive sil"""
        children = db.query(Folder).filter(Folder.parent_id == parent_id, Folder.user_id == user_id).all()
        for child in children:
            self._delete_children(db, user_id, child.id)
            db.query(Scenario).filter(Scenario.folder_id == child.id).update({"folder_id": None})
            db.delete(child)
    
    def get_user_scenarios(self, db: Session, user_id: int, folder_id: Optional[int] = None) -> List[Scenario]:
        """Kullanıcının senaryolarını getir"""
        query = db.query(Scenario).filter(Scenario.user_id == user_id)
        if folder_id is not None:
            query = query.filter(Scenario.folder_id == folder_id)
        return query.order_by(Scenario.updated_at.desc()).all()
    
    def get_user_scenario(self, db: Session, user_id: int, scenario_id: int) -> Optional[Scenario]:
        """Tek senaryo getir"""
        return db.query(Scenario).filter(Scenario.id == scenario_id, Scenario.user_id == user_id).first()
    
    def create_scenario(self, db: Session, user_id: int, data: ScenarioCreate) -> Dict[str, Any]:
        """Yeni senaryo oluştur"""
        scenario = Scenario(
            name=data.name,
            description=data.description,
            type=data.type or "web",
            folder_id=data.folder_id,
            natural_steps=data.natural_steps,
            steps_json=data.steps_json,
            config_json=data.config_json,
            tags=data.tags,
            user_id=user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        return {"success": True, "scenario": scenario}
    
    def update_scenario(self, db: Session, user_id: int, scenario_id: int, data: ScenarioUpdate) -> Dict[str, Any]:
        """Senaryo güncelle"""
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id, Scenario.user_id == user_id).first()
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(scenario, key, value)
        
        scenario.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(scenario)
        return {"success": True, "scenario": scenario}
    
    def delete_scenario(self, db: Session, user_id: int, scenario_id: int) -> Dict[str, Any]:
        """Senaryo sil"""
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id, Scenario.user_id == user_id).first()
        if not scenario:
            return {"success": False, "message": "Senaryo bulunamadı"}
        
        db.delete(scenario)
        db.commit()
        return {"success": True, "message": "Silindi"}
    
    def get_scenario_stats(self, db: Session, user_id: int) -> Dict[str, Any]:
        """Senaryo istatistikleri"""
        total = db.query(Scenario).filter(Scenario.user_id == user_id).count()
        web_count = db.query(Scenario).filter(Scenario.user_id == user_id, Scenario.type == "web").count()
        mobile_count = db.query(Scenario).filter(Scenario.user_id == user_id, Scenario.type == "mobile").count()
        desktop_count = db.query(Scenario).filter(Scenario.user_id == user_id, Scenario.type == "desktop").count()
        
        return {
            "total": total,
            "web": web_count,
            "mobile": mobile_count,
            "desktop": desktop_count
        }


scenario_service = ScenarioService()