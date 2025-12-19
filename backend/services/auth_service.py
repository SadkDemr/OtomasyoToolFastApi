"""
Auth Service - Authentication & JWT Token Yonetimi
FIXED: db_models uyumlulugu (hashed_password) ve is_active kontrolu
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from models.db_models import User
from models.schemas import UserRegister

# JWT Ayarları
SECRET_KEY = "test-platform-secret-key-change-in-production-2024"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Şifre hashleme
# Not: "bcrypt==4.0.1" kurulu olmalidir
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Authentication Servisi"""
    
    def hash_password(self, password: str) -> str:
        """Şifreyi hashle"""
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Şifreyi doğrula"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def create_access_token(self, user_id: int, username: str) -> str:
        """JWT token oluştur"""
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
        to_encode = {
            "sub": str(user_id),
            "username": username,
            "exp": expire
        }
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    def decode_token(self, token: str) -> Optional[dict]:
        """Token'ı decode et"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
    
    def get_user_by_username(self, db: Session, username: str) -> Optional[User]:
        """Kullanıcı adına göre getir"""
        return db.query(User).filter(User.username == username).first()
    
    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        """Email'e göre getir"""
        return db.query(User).filter(User.email == email).first()
    
    def get_user_by_id(self, db: Session, user_id: int) -> Optional[User]:
        """ID'ye göre getir"""
        return db.query(User).filter(User.id == user_id).first()
    
    def register(self, db: Session, user_data: UserRegister) -> dict:
        """Yeni kullanıcı kaydı"""
        
        # Username kontrolü
        if self.get_user_by_username(db, user_data.username):
            return {"success": False, "message": "Bu kullanıcı adı zaten kullanılıyor"}
        
        # Email kontrolü
        if self.get_user_by_email(db, user_data.email):
            return {"success": False, "message": "Bu email zaten kayıtlı"}
        
        # Kullanıcı oluştur
        # DUZELTME: password_hash yerine hashed_password kullanildi
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=self.hash_password(user_data.password), # DUZELTİLDİ
            full_name=user_data.full_name,
            role="user" # Varsayilan rol
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # Token oluştur
        token = self.create_access_token(new_user.id, new_user.username)
        
        return {
            "success": True,
            "message": "Kayıt başarılı",
            "access_token": token,
            "token_type": "bearer",
            "user": new_user
        }
    
    def login(self, db: Session, username: str, password: str) -> dict:
        """Kullanıcı girişi"""
        
        user = self.get_user_by_username(db, username)
        
        if not user:
            return {"success": False, "message": "Kullanıcı bulunamadı"}
        
        # DUZELTME: is_active kontrolu kaldirildi (DB'de yok)
        # if not user.is_active: ...
        
        # DUZELTME: password_hash yerine hashed_password ile dogrulama
        if not self.verify_password(password, user.hashed_password): # DUZELTİLDİ
            return {"success": False, "message": "Şifre hatalı"}
        
        # Son giris zamanini guncelle
        user.last_login = datetime.utcnow()
        db.commit()
        
        # Token oluştur
        token = self.create_access_token(user.id, user.username)
        
        return {
            "success": True,
            "message": "Giriş başarılı",
            "access_token": token,
            "token_type": "bearer",
            "user": user
        }
    
    def get_current_user(self, db: Session, token: str) -> Optional[User]:
        """Token'dan kullanıcıyı al"""
        
        payload = self.decode_token(token)
        if not payload:
            return None
        
        user_id = int(payload.get("sub"))
        return self.get_user_by_id(db, user_id)


# Singleton
auth_service = AuthService()