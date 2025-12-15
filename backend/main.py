"""
Test Otomasyon Platformu - FastAPI Backend v2.1
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import init_db

from routers.auth import router as auth_router
from routers.scenarios import router as scenarios_router
from routers.devices import router as devices_router
from routers.web import router as web_router
from routers.mobile import router as mobile_router
from routers.emulator import router as emulator_router


app = FastAPI(
    title="Test Otomasyon Platformu API",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(scenarios_router)
app.include_router(devices_router)
app.include_router(web_router)
app.include_router(mobile_router)
app.include_router(emulator_router)

web_ui = os.path.join(BASE_DIR, "WebArayuz")
if os.path.exists(web_ui):
    app.mount("/ui", StaticFiles(directory=web_ui, html=True), name="ui")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.1.0", "time": datetime.now().isoformat()}


@app.on_event("startup")
async def startup():
    init_db()
    print("=" * 50)
    print("Test Otomasyon API v2.1")
    print("Swagger: http://localhost:8000/docs")
    print("Web UI: http://localhost:8000/ui")
    print("=" * 50)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
