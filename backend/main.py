"""
Test Otomasyon Platformu - FastAPI Backend v2.1
"""
import sys
import os
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import init_db

# Router Importları
from routers.auth import router as auth_router
from routers.emulator import router as emulator_router

# Git Integration
from routers.admin_repositories_router import router as admin_repos_router
from routers.admin_users_router import router as admin_users_router
from routers.admin_java_templates_router import router as admin_java_templates_router
from routers.workspace_router import router as workspace_router
# ✅ Advanced Editor (Desktop/Web-Desktop)
from routers.advanced_editor_router import router as advanced_editor_router
# 🤖 AI Test Generator (Ollama / gemma3:4b)
from routers.ai_test_generator_router import router as ai_gen_router
# ☕ Java Test Generator (Ollama / gemma3:4b)
from routers.java_generator_router import router as java_gen_router
# 🥒 BDD Generator
from routers.bdd_generator_router import router as bdd_gen_router
# 🗓️ AI Test Generator - Job sistemi (Faz 1: Mobil)
from routers.ai_job_router import router as ai_job_router
# 🧪 TestCaseGen (ekran -> baslik -> onceliklendirme -> test case + ADO export)
from routers.testcasegen_router import router as testcasegen_router
# 🔁 AI Test Generator - idle oturum reaper
from routers.ai_test_generator_router import _session_idle_reaper
# 🗓️ AI Job Sistemi - zamanlayici + baslangic temizligi
from services.ai_job_service import ai_job_scheduler_loop, cleanup_interrupted_runs

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("="*50)
    print("--- SISTEM BASLATILIYOR ---")
    init_db()
    asyncio.create_task(_session_idle_reaper())
    cleanup_interrupted_runs()
    asyncio.create_task(ai_job_scheduler_loop())
    print("Swagger: http://localhost:8000/docs")
    print("Web UI: http://localhost:8000/ui")
    print("="*50)
    yield

app = FastAPI(title="Test Otomasyon Platformu API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(emulator_router)
# Git Integration
app.include_router(admin_repos_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(admin_java_templates_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
# ✅ Advanced Editor
app.include_router(advanced_editor_router)
# 🤖 AI Test Generator
app.include_router(ai_gen_router)
# ☕ Java Test Generator
app.include_router(java_gen_router)
# 🥒 BDD Generator
app.include_router(bdd_gen_router)
# 🗓️ AI Job Sistemi
app.include_router(ai_job_router)
# 🧪 TestCaseGen
app.include_router(testcasegen_router)

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
    ollama_url:     str = ""
    ollama_model:   str = ""

@app.get("/api/admin/ai-config", tags=["Admin"])
async def get_ai_config_endpoint(current_user=Depends(_get_user)):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    cfg = get_ai_config()
    key = cfg.get("gemini_api_key", "")
    masked = ("*" * (len(key) - 4) + key[-4:]) if len(key) > 4 else ("*" * len(key))
    return {
        "configured":   bool(key),
        "masked_key":   masked,
        "ollama_url":   cfg.get("ollama_url",   "http://localhost:11434/api/generate"),
        "ollama_model": cfg.get("ollama_model", "gemma3:4b"),
    }

@app.post("/api/admin/ai-config", tags=["Admin"])
async def set_ai_config_endpoint(body: AIConfigBody, current_user=Depends(_get_user)):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    cfg = get_ai_config()
    if body.gemini_api_key:
        cfg["gemini_api_key"] = body.gemini_api_key
    if body.ollama_url:
        cfg["ollama_url"] = body.ollama_url
    if body.ollama_model:
        cfg["ollama_model"] = body.ollama_model
    save_ai_config(cfg)
    return {"success": True, "message": "AI yapılandırması kaydedildi"}


# ── Admin: Senaryolara Genel Bakış - workspace dosyalarından okur (Feature 1) ──
@app.get("/api/admin/scenarios-overview", tags=["Admin"])
async def scenarios_overview(current_user=Depends(_get_user)):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    import json as _json
    from pathlib import Path
    from database import get_db as _gdb
    from models.db_models import User as _User, UserWorkspace as _UW

    db = next(_gdb())
    try:
        users = {u.id: u for u in db.query(_User).order_by(_User.username).all()}
        workspaces = db.query(_UW).filter_by(is_cloned=True).all()

        # user_id → { repo_name, scenarios_by_platform }
        user_data: dict = {}

        for ws in workspaces:
            uid = ws.user_id
            u = users.get(uid)
            if not u:
                continue
            if uid not in user_data:
                user_data[uid] = {
                    "user_id":   uid,
                    "username":  u.username,
                    "full_name": u.full_name,
                    "role":      u.role,
                    "scenarios": {"web": [], "mobile": [], "desktop": []},
                }

            ai_scenarios_dir = Path(ws.local_path) / "ai_scenarios"
            if not ai_scenarios_dir.exists():
                continue

            for folder in sorted(ai_scenarios_dir.iterdir()):
                if not folder.is_dir():
                    continue
                steps_file = folder / "steps.json"
                if not steps_file.exists():
                    continue
                try:
                    data = _json.loads(steps_file.read_text(encoding="utf-8"))
                    plat = data.get("platform", "web")
                    if plat not in ("web", "mobile", "desktop"):
                        plat = "web"
                    user_data[uid]["scenarios"][plat].append({
                        "id":         folder.name,
                        "name":       data.get("name", folder.name),
                        "folder":     folder.name,
                        "updated_at": None,
                        "workspace":  ws.repository.name if ws.repository else "",
                    })
                except Exception:
                    pass

        result = []
        for uid in sorted(user_data, key=lambda x: user_data[x]["username"]):
            d = user_data[uid]
            total = sum(len(v) for v in d["scenarios"].values())
            d["total"] = total
            result.append(d)

        return {"users": result}
    finally:
        db.close()


# ── Admin: Koşum İstatistikleri (Feature 4) ───────────────────────────────────
@app.get("/api/admin/run-stats", tags=["Admin"])
async def run_stats(
    date_from: str = None,
    date_to:   str = None,
    current_user=Depends(_get_user)
):
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin yetkisi gerekli")
    import json as _json
    from pathlib import Path
    from datetime import datetime as _dt
    from database import get_db as _gdb
    from models.db_models import User as _User, UserWorkspace as _UW

    db = next(_gdb())
    try:
        users = {u.id: u.username for u in db.query(_User).all()}
        workspaces = db.query(_UW).filter_by(is_cloned=True).all()

        # Tarih filtresi sınırları
        dt_from = _dt.fromisoformat(date_from) if date_from else None
        dt_to   = _dt.fromisoformat(date_to)   if date_to   else None

        stats_by_user: dict = {}
        all_runs: list = []

        for ws in workspaces:
            log_dir = Path(ws.local_path) / "ai_run_logs"
            if not log_dir.exists():
                continue
            uid = ws.user_id
            uname = users.get(uid, f"user_{uid}")
            if uid not in stats_by_user:
                stats_by_user[uid] = {
                    "username": uname, "total": 0,
                    "passed": 0, "failed": 0,
                    "platforms": {"web": 0, "mobile": 0, "desktop": 0},
                    "total_duration_sec": 0,
                }
            for f in log_dir.glob("*.json"):
                try:
                    d = _json.loads(f.read_text(encoding="utf-8"))
                    # Tarih filtresi uygula
                    started_raw = d.get("started_at")
                    if started_raw and (dt_from or dt_to):
                        try:
                            started_dt = _dt.fromisoformat(started_raw.replace("Z",""))
                            if dt_from and started_dt < dt_from:
                                continue
                            if dt_to and started_dt > dt_to:
                                continue
                        except Exception:
                            pass

                    s = stats_by_user[uid]
                    s["total"] += 1
                    plat = d.get("platform", "web")
                    s["platforms"][plat] = s["platforms"].get(plat, 0) + 1
                    ok = d.get("exit_code", 1) == 0 and d.get("failed", 1) == 0
                    if ok:
                        s["passed"] += 1
                    else:
                        s["failed"] += 1
                    try:
                        dur = (_dt.fromisoformat(d["ended_at"]) - _dt.fromisoformat(d["started_at"])).seconds
                        s["total_duration_sec"] += dur
                    except Exception:
                        pass
                    all_runs.append({
                        "username":     uname,
                        "scenario":     d.get("scenario_name", "?"),
                        "platform":     plat,
                        "started_at":   started_raw,
                        "exit_code":    d.get("exit_code", -1),
                        "total_steps":  d.get("total_steps", 0),
                        "passed":       d.get("passed", 0),
                        "failed_steps": d.get("failed", 0),
                        "status":       "passed" if ok else "failed",
                    })
                except Exception:
                    pass

        all_runs.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        return {
            "by_user":  list(stats_by_user.values()),
            "all_runs": all_runs,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn, os as _os_main
    # Geliştirme modunda auto-reload istiyorsanız: DEV_RELOAD=1 python main.py
    # Prodüksiyonda reload=False — senaryo script.py kaydedince sunucu düşmesin
    _dev_reload = _os_main.environ.get("DEV_RELOAD", "0") == "1"
    if _dev_reload and sys.platform == "win32":
        # uvicorn reload=True Windows'ta SelectorEventLoop'u zorlar; asyncio subprocess
        # orada desteklenmez, AI Job hucreleri thread havuzlu yedek yola duser.
        print("[UYARI] DEV_RELOAD=1: AI Job hucreleri thread havuzlu yedek yolu kullanacak.")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=_dev_reload,
    )