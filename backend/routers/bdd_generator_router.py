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
# ══════════════════════════════════════════════════════════════════════════════

def _safe_class(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]', '', name or "BDDGeneratedTest") or "BDDGeneratedTest"


def _build_ios_template(req: BDDGenerateRequest, steps_code: str) -> str:
    bundle_id = req.bundle_id        or ""
    udid      = req.udid             or ""
    device    = req.device_name      or "iPhone Device"
    version   = req.platform_version or "18"
    appium    = req.appium_url       or "http://localhost:4723"
    no_reset  = "true" if req.no_reset else "false"
    cls_name  = _safe_class(req.class_name)

    udid_line   = f'\ncapabilities.setCapability("udid", "{udid}");'          if udid      else ""
    bundle_line = f'\ncapabilities.setCapability("bundleId", "{bundle_id}");' if bundle_id else ""
    restart     = (
        f'driver.terminateApp("{bundle_id}");\n    driver.activateApp("{bundle_id}");'
        if bundle_id else "// bundle_id girilmedi"
    )
    terminate = f'driver.terminateApp("{bundle_id}");' if bundle_id else ""

    return f"""\
import io.appium.java_client.AppiumBy;
import io.appium.java_client.ios.IOSDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.WebDriverWait;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "iOS");
capabilities.setCapability("platformVersion", "{version}");
capabilities.setCapability("deviceName", "{device}");{udid_line}
capabilities.setCapability("automationName", "XCUITest");{bundle_line}
capabilities.setCapability("noReset", {no_reset});
// ── CONFIG END ────────────────────────────────────────────────────

IOSDriver driver = null;

try {{
    driver = new IOSDriver(new URL("{appium}"), capabilities);
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(5));
    WebDriverWait wait = new WebDriverWait(driver, Duration.ofSeconds(20));

    {restart}
    Thread.sleep(2000);

// ── TEST ADIMLARI ─────────────────────────────────────────────────
{steps_code}

// ── TEST SONU ─────────────────────────────────────────────────────
}} catch (Exception e) {{
    throw e;
}} finally {{
    if (driver != null) {{
        try {{ {terminate} }} catch (Exception ignored) {{}}
        driver.quit();
    }}
}}
"""


def _build_android_template(req: BDDGenerateRequest, steps_code: str) -> str:
    pkg      = req.app_package      or ""
    act      = req.app_activity     or ""
    udid     = req.udid             or ""
    device   = req.device_name      or "Android Device"
    version  = req.platform_version or "15"
    appium   = req.appium_url       or "http://localhost:4723"
    no_reset = "true" if req.no_reset else "false"
    cls_name = _safe_class(req.class_name)

    udid_line = f'\ncapabilities.setCapability("udid", "{udid}");'         if udid else ""
    act_line  = f'\ncapabilities.setCapability("appActivity", "{act}");'   if act  else ""
    pkg_line  = f'\ncapabilities.setCapability("appPackage", "{pkg}");'    if pkg  else ""
    restart   = (
        f'driver.terminateApp("{pkg}");\ndriver.activateApp("{pkg}");'
        if pkg else "// app_package girilmedi"
    )
    terminate = f'driver.terminateApp("{pkg}");' if pkg else ""

    return f"""\
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.nativekey.AndroidKey;
import io.appium.java_client.android.nativekey.KeyEvent;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import org.junit.Assert.*;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import com.google.common.collect.ImmutableMap;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "Android");
capabilities.setCapability("platformVersion", "{version}");
capabilities.setCapability("deviceName", "{device}");{udid_line}
capabilities.setCapability("automationName", "UiAutomator2");{pkg_line}{act_line}
capabilities.setCapability("appium:noReset", {no_reset});
// ── CONFIG END ────────────────────────────────────────────────────

AndroidDriver driver = new AndroidDriver(new URL("{appium}"), capabilities);
driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));

{restart}
Thread.sleep(2000);

// ── TEST ADIMLARI ─────────────────────────────────────────────────
{steps_code}

// ── TEST SONU ─────────────────────────────────────────────────────
{terminate}
driver.quit();
"""


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
            'wait.until(ExpectedConditions.elementToBeClickable(AppiumBy.xpath("//*[@name=\'X\']"))).click();\n'
            'wait.until(ExpectedConditions.visibilityOfElementLocated(AppiumBy.xpath("//*[@name=\'X\']"))).isDisplayed();\n'
            'driver.executeScript("mobile: scroll", Map.of("direction", "down"));\n'
            'Thread.sleep(1000);'
        )
    else:
        api_hint = (
            'driver.findElement(By.xpath("//*[@text=\'X\']")).click();\n'
            'assertTrue(driver.findElement(By.xpath("//*[@text=\'X\']")).isDisplayed());\n'
            'driver.executeScript("mobile:scroll", ImmutableMap.of("direction", "down"));\n'
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
            or re.match(r'^\s*(wait|driver|Thread|assertTrue|assert|\{)', ln)
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
        final_code = _build_android_template(req, result["steps_code"])
    else:
        final_code = _build_ios_template(req, result["steps_code"])

    return {
        "success":            True,
        "script":             final_code,
        "report":             result["report"],
        "warnings":           result["warnings"],
        "custom_steps_count": len(custom_steps),
    }
