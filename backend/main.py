"""
Test Otomasyon Platformu - FastAPI Backend
==========================================

Swagger UI: http://localhost:8000/docs

Endpoints:
- /api/auth/*       : Login, Register, Token
- /api/scenarios/*  : Senaryo CRUD
- /api/devices/*    : Cihaz yönetimi
- /api/web/*        : Web test
- /api/mobile/*     : Mobil test
"""

import sys
import os

# Path ayarı
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# Database
from database import init_db

# Routers
from routers.auth import router as auth_router
from routers.scenarios import router as scenarios_router
from routers.devices import router as devices_router
from routers.web import router as web_router
from routers.mobile import router as mobile_router


# ============ APP ============

app = FastAPI(
    title="Test Otomasyon Platformu API",
    description="""
## Test Otomasyon Platformu

Web, Mobil ve Desktop test otomasyonu yönetim sistemi.

### Özellikler:
- 🔐 **Kullanıcı Yönetimi**: Login/Register/JWT
- 📝 **Senaryo Yönetimi**: CRUD, kategorileme
- 📱 **Cihaz Yönetimi**: Emülatör/Fiziksel, kilitleme
- 🌐 **Web Test**: Selenium ile
- 📲 **Mobil Test**: Appium ile

### Kullanım:
1. `/api/auth/register` - Kayıt ol
2. `/api/auth/login` - Giriş yap, token al
3. Token'ı "Authorize" butonuyla ekle
4. Diğer endpoint'leri kullan
    """,
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ ROUTERS ============

app.include_router(auth_router)
app.include_router(scenarios_router)
app.include_router(devices_router)
app.include_router(web_router)
app.include_router(mobile_router)


# ============ ROOT ============

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Health"])
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    }


# ============ STARTUP ============

@app.on_event("startup")
async def startup():
    # Database tablolarını oluştur
    init_db()
    
    print("=" * 50)
    print("🚀 Test Otomasyon API v2.0 başlatıldı!")
    print("📖 Swagger: http://localhost:8000/docs")
    print("=" * 50)


# ============ MAIN ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)