"""
Test Otomasyon Platformu - FastAPI Backend v2.1
"""
import sys
import os
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import init_db

# Router Importları
from routers.auth import router as auth_router
from routers.web import router as web_router
from routers.mobile import router as mobile_router
from routers.emulator import router as emulator_router
from routers.desktop_router import router as desktop_router

# Git Integration
from routers.admin_repositories_router import router as admin_repos_router
from routers.admin_users_router import router as admin_users_router
from routers.workspace_router import router as workspace_router
# ✅ Advanced Editor (Desktop/Web-Desktop)
from routers.advanced_editor_router import router as advanced_editor_router
# 🤖 AI Test Generator (Ollama / gemma3:4b)
from routers.ai_test_generator_router import router as ai_gen_router
# ☕ Java Test Generator (Ollama / gemma3:4b)
from routers.java_generator_router import router as java_gen_router
# 🥒 BDD Generator
from routers.bdd_generator_router import router as bdd_gen_router

app = FastAPI(title="Test Otomasyon Platformu API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(web_router)
app.include_router(mobile_router)
app.include_router(emulator_router)
# Git Integration
app.include_router(admin_repos_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(desktop_router, prefix="/api")
# ✅ Advanced Editor
app.include_router(advanced_editor_router)
# 🤖 AI Test Generator
app.include_router(ai_gen_router)
# ☕ Java Test Generator
app.include_router(java_gen_router)
# 🥒 BDD Generator
app.include_router(bdd_gen_router)

web_ui = os.path.join(BASE_DIR, "WebArayuz")
if os.path.exists(web_ui):
    app.mount("/ui", StaticFiles(directory=web_ui, html=True), name="ui")

@app.get("/", include_in_schema=False)
async def root(): return RedirectResponse(url="/docs")

@app.get("/health")
async def health(): return {"status": "ok", "time": datetime.now().isoformat()}


# ──────────────────────────────────────────────────────
# Admin: AI Config (Gemini API Key yönetimi)
# ──────────────────────────────────────────────────────
from fastapi import Depends
from pydantic import BaseModel as _BM
from routers.auth import get_current_user as _get_user
from services.ai_service import get_ai_config, save_ai_config, get_gemini_key

class AIConfigBody(_BM):
    gemini_api_key: str = ""

@app.get("/api/admin/ai-config", tags=["Admin"])
async def get_ai_config_endpoint(current_user=Depends(_get_user)):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    cfg = get_ai_config()
    # Key'i maskele (son 4 karakter göster)
    key = cfg.get("gemini_api_key", "")
    masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else ("*" * len(key))
    return {"configured": bool(key), "masked_key": masked}

@app.post("/api/admin/ai-config", tags=["Admin"])
async def set_ai_config_endpoint(body: AIConfigBody, current_user=Depends(_get_user)):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    cfg = get_ai_config()
    if body.gemini_api_key:
        cfg["gemini_api_key"] = body.gemini_api_key
    save_ai_config(cfg)
    return {"success": True, "message": "AI yapılandırması kaydedildi"}

@app.on_event("startup")
async def startup_event():
    print("="*50)
    print("--- 🔄 SİSTEM BAŞLATILIYOR ---")
    init_db()
    print("Swagger: http://localhost:8000/docs")
    print("Web UI: http://localhost:8000/ui")
    print("="*50)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)