"""
BDD Generator Router
====================
Gherkin BDD senaryolarını Java Appium koduna çevirir.
JSON mapping dosyasındaki XPath'leri kullanır.
"""

import re
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User
from services.bdd_generator_service import generate_bdd_java, parse_java_custom_steps
from services.appium_codegen_service import (
    build_ios_template,
    build_android_template,
)

router = APIRouter(prefix="/api/bdd-gen", tags=["bdd-generator"])

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class BDDGenerateRequest(BaseModel):
    bdd_scenario:     str
    mappings:         dict             # {"pageName": {"elementKey": "//xpath...", ...}}
    platform:         Optional[str]  = "ios"
    appium_url:       Optional[str]  = "http://localhost:4723"
    platform_version: Optional[str]  = "18"
    device_name:      Optional[str]  = "iPhone Device"
    udid:             Optional[str]  = ""
    app_package:      Optional[str]  = ""
    app_activity:     Optional[str]  = ""
    bundle_id:        Optional[str]  = ""
    no_reset:         Optional[bool] = True
    class_name:       Optional[str]  = "BDDGeneratedTest"
    custom_steps_java: Optional[str] = None   # MySteps.java içeriği


# ══════════════════════════════════════════════════════════════════════════════
# ŞABLONLAR
# (appium_codegen_service.build_ios_template / build_android_template — Java
#  Generator ile paylaşılıyor)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_page_mapping(raw: dict) -> dict:
    """
    {"parent":..., "loadTimeout":..., "elements":{...}} formatını çözer.
    Boş key / value'ları filtreler.
    """
    if "elements" in raw and isinstance(raw["elements"], dict):
        raw = raw["elements"]
    return {k: v for k, v in raw.items() if k and v}


class AIFillRequest(BaseModel):
    todo_steps: List[str]
    platform:   Optional[str] = "ios"


async def _llm_fill_todos(todo_steps: List[str], platform: str) -> dict:
    """Ollama ile 'todo' adımlar için Java Appium kodu üret."""
    if not todo_steps:
        return {}

    is_ios = platform.lower() != "android"
    if is_ios:
        api_hint = (
            'driver.findElement(AppiumBy.xpath("//*[@name=\'X\']")).click();\n'
            'driver.findElement(AppiumBy.xpath("//*[@name=\'X\']")).isDisplayed();\n'
            '// scroll/swipe: do NOT use driver.executeScript("mobile:...") — unreliable across driver versions.\n'
            '// Output only: // TODO: manual scroll/swipe gesture needed\n'
            'Thread.sleep(1000);'
        )
    else:
        api_hint = (
            'driver.findElement(By.xpath("//*[@text=\'X\']")).click();\n'
            'assertTrue(driver.findElement(By.xpath("//*[@text=\'X\']")).isDisplayed());\n'
            '// scroll/swipe: do NOT use driver.executeScript("mobile:...") — unreliable across driver versions.\n'
            '// Output only: // TODO: manual scroll/swipe gesture needed\n'
            'Thread.sleep(1000);'
        )

    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(todo_steps))
    prompt = (
        f"Write Java Appium code for each test step ({('iOS XCUITest' if is_ios else 'Android')}). "
        f"Output ONLY code lines and // comments. No explanations, no imports.\n\n"
        f"Available API:\n{api_hint}\n\n"
        f"Steps:\n{numbered}\n\n"
        f"Java code (one block per step, separated by blank lines):"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":   OLLAMA_MODEL,
                "prompt":  prompt,
                "stream":  False,
                "options": {"temperature": 0.2, "num_predict": 600},
            })
            raw = resp.json().get("response", "").strip()
    except Exception:
        return {}

    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    result = {}
    for i, step in enumerate(todo_steps):
        block = blocks[i] if i < len(blocks) else ""
        java_lines = [
            ln for ln in block.splitlines()
            if ln.strip().startswith("//")
            or re.match(r'^\s*(driver|Thread|assertTrue|assert|\{)', ln)
        ]
        result[step] = "\n".join(java_lines)
    return result


@router.post("/ai-fill-todos")
async def ai_fill_todos(
    req:          AIFillRequest,
    current_user: User = Depends(get_current_user),
):
    codes = await _llm_fill_todos(req.todo_steps, req.platform or "ios")
    return {"success": True, "codes": codes}


@router.post("/generate")
async def generate_bdd(
    req:          BDDGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    normalized_mappings = {
        page: _normalize_page_mapping(mapping)
        for page, mapping in req.mappings.items()
        if isinstance(mapping, dict)
    }

    custom_steps = parse_java_custom_steps(req.custom_steps_java) if req.custom_steps_java else []

    result = generate_bdd_java(
        bdd_text     = req.bdd_scenario,
        mappings     = normalized_mappings,
        platform     = (req.platform or "ios").lower(),
        custom_steps = custom_steps,
    )

    platform = (req.platform or "ios").lower()
    if platform == "android":
        final_code = build_android_template(
            steps_code=result["steps_code"],
            app_package=req.app_package,
            app_activity=req.app_activity,
            udid=req.udid,
            device_name=req.device_name,
            platform_version=req.platform_version,
            appium_url=req.appium_url,
            no_reset=req.no_reset,
        )
    else:
        final_code = build_ios_template(
            steps_code=result["steps_code"],
            bundle_id=req.bundle_id,
            udid=req.udid,
            device_name=req.device_name,
            platform_version=req.platform_version,
            appium_url=req.appium_url,
            no_reset=req.no_reset,
        )

    return {
        "success":            True,
        "script":             final_code,
        "report":             result["report"],
        "warnings":           result["warnings"],
        "custom_steps_count": len(custom_steps),
    }
