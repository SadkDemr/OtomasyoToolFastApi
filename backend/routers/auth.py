"""
Auth Router - /api/auth/*
Login, Register, Token Dogrulama
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.schemas import UserRegister, UserLogin, UserResponse, TokenResponse
from services.auth_service import auth_service

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Bearer token security
security = HTTPBearer(auto_error=False)


# ============ DEPENDENCY ============

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Token'dan kullanıcıyı al - Dependency"""
    
    if not credentials:
        raise HTTPException(status_code=401, detail="Token gerekli")
    
    token = credentials.credentials
    user = auth_service.get_current_user(db, token)
    
    if not user:
        raise HTTPException(status_code=401, detail="Geçersiz token")
    
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Hesap devre dışı")
    
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Opsiyonel kullanıcı - Token yoksa None döner"""
    
    if not credentials:
        return None
    
    token = credentials.credentials
    return auth_service.get_current_user(db, token)


# ============ ENDPOINTS ============

@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Yeni kullanıcı kaydı
    
    - **username**: Kullanıcı adı (min 3, max 50 karakter)
    - **email**: Email adresi
    - **password**: Şifre (min 6 karakter)
    - **full_name**: Ad Soyad (opsiyonel)
    """
    
    result = auth_service.register(db, user_data)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return TokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        user=UserResponse.model_validate(result["user"])
    )


@router.post("/login", response_model=TokenResponse)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    Kullanıcı girişi
    
    - **username**: Kullanıcı adı
    - **password**: Şifre
    """
    
    result = auth_service.login(db, user_data.username, user_data.password)
    
    if not result["success"]:
        raise HTTPException(status_code=401, detail=result["message"])
    
    return TokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        user=UserResponse.model_validate(result["user"])
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user = Depends(get_current_user)):
    """
    Mevcut kullanıcı bilgilerini getir
    
    Authorization: Bearer {token} gerekli
    """
    return UserResponse.model_validate(current_user)


@router.post("/verify")
async def verify_token(current_user = Depends(get_current_user)):
    """
    Token geçerliliğini kontrol et
    """
    return {
        "valid": True,
        "user_id": current_user.id,
        "username": current_user.username
    }


@router.post("/logout")
async def logout(current_user = Depends(get_current_user)):
    """
    Çıkış yap (client-side token silme için)
    
    Not: JWT stateless olduğu için server-side logout yok.
    Client token'ı silmeli.
    """
    return {"success": True, "message": "Çıkış yapıldı"}
