"""
Java Test Generator Router
===========================
Türkçe doğal dil test adımlarını Java Appium koduna çevirir.
Kural motoru + LLM fallback (Ollama gemma3:4b).
Sadece dönüşüm — çalıştırma yok.
"""

import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User
from services.java_generator_service import generate_step
from services.appium_codegen_service import build_android_template, build_ios_template

router = APIRouter(prefix="/api/java-gen", tags=["java-generator"])

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class JavaGenerateRequest(BaseModel):
    test_case:        str
    platform:         Optional[str]  = "android"
    appium_url:       Optional[str]  = "http://localhost:4723"
    platform_version: Optional[str]  = "15"
    device_name:      Optional[str]  = "Android Device"
    udid:             Optional[str]  = ""
    app_package:      Optional[str]  = ""
    app_activity:     Optional[str]  = ""
    bundle_id:        Optional[str]  = ""
    no_reset:         Optional[bool] = True
    class_name:       Optional[str]  = "GeneratedTest"


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1-3: KURAL MOTORU + ŞABLON
# (services/java_generator_service.py + services/appium_codegen_service.py —
#  BDD Generator ile paylaşılan ortak çekirdek)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4: LLM FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def _java_code_lines(block: str) -> list[str]:
    """LLM çıktısından gerçek Java satırlarını ayıklar.
    Önceki heuristic yalnızca sabit bir sınıf adı listesiyle (driver/Thread/
    WebElement/Map/...) başlayan satırları veya küçük harfle başlayan ';'
    satırlarını tutuyordu; bu yüzden `String x = ...;`, `By locator = ...;`,
    `List<WebElement> els = ...;` gibi büyük harfle başlayan GEÇERLİ Java
    değişken tanımları da "düz metin cümlesi" sanılıp siliniyor, üretilen kod
    eksik/derlenmez hale geliyordu (JMeter/IntelliJ'de "cannot find symbol").
    Artık satır sonundaki `;` / `{` / `}` zaten yeterli kod sinyali kabul
    edilir — düz metin (prose) genelde bu karakterlerle bitmez."""
    lines = []
    for l in block.splitlines():
        t = l.strip()
        if not t:
            continue
        if t.startswith("//") or t.endswith((';', '{', '}')):
            lines.append(l)
    return lines


async def _ask_llm_java(steps: list[str]) -> dict[str, str]:
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    prompt = f"""Write Java Appium code for each test step. Use AndroidDriver.
Output only Java statements + // comments. No imports, no class/method wrapper.
Rules:
- Click text/button: driver.findElement(By.xpath("//*[@text='X']")).click();
- Type text: driver.executeScript("mobile: type", Map.of("text", "VALUE")); then driver.hideKeyboard();
- Scroll/swipe: do NOT use driver.executeScript("mobile:...") — it is unreliable across driver versions. Output only: // TODO: manual scroll/swipe gesture needed
- Back key: driver.pressKey(new KeyEvent(AndroidKey.BACK));
- Thread.sleep(ms) only when step explicitly requires waiting
- Only use these types: driver, By, WebElement, Map, Thread, KeyEvent, AndroidKey. Do not declare or use any other class.

Steps:
{numbered}

Java code (one block per step, separated by blank lines):"""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            })
            raw = resp.json().get("response", "")
    except Exception:
        raw = ""

    result = {}
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    for i, step in enumerate(steps):
        if i < len(blocks):
            code_only = "\n".join(_java_code_lines(blocks[i]))
            result[step] = code_only if code_only else f"// TODO: {step}\nThread.sleep(1000);"
        else:
            result[step] = f"// TODO: {step}\nThread.sleep(1000);"
    return result


async def _ask_llm_ios(steps: list[str]) -> dict[str, str]:
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    prompt = f"""Write Java Appium code for each iOS test step. Use IOSDriver with XCUITest.
Output only Java statements + // comments. No imports, no class/method wrapper.
Variables already available: IOSDriver 'driver'.
Rules:
- Click element: driver.findElement(AppiumBy.xpath("//*[@name='X' or @label='X' or @value='X']")).click();
- Type text: driver.switchTo().activeElement().sendKeys("VALUE"); try {{ driver.hideKeyboard(); }} catch (Exception ignored) {{}}
- Assert visible: driver.findElement(AppiumBy.xpath("//*[@name='X' or @label='X' or @value='X']")).isDisplayed();
- Scroll/swipe: do NOT use driver.executeScript("mobile:...") — it is unreliable across driver versions. Output only: // TODO: manual scroll/swipe gesture needed
- Back: driver.navigate().back();
- Wait: Thread.sleep(ms);
- Only use these types: driver, AppiumBy, WebElement, Thread. Do not declare or use any other class.

Steps:
{numbered}

Java code (one block per step, separated by blank lines):"""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            })
            raw = resp.json().get("response", "")
    except Exception:
        raw = ""

    result = {}
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    for i, step in enumerate(steps):
        if i < len(blocks):
            code_only = "\n".join(_java_code_lines(blocks[i]))
            result[step] = code_only if code_only else f"// TODO: {step}\nThread.sleep(1000);"
        else:
            result[step] = f"// TODO: {step}\nThread.sleep(1000);"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT'LER
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
async def ollama_status():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return {"online": True, "model_available": any("gemma3" in m for m in models)}
    except Exception:
        pass
    return {"online": False, "model_available": False}


@router.post("/generate")
async def generate_java(req: JavaGenerateRequest, current_user: User = Depends(get_current_user)):
    raw_steps = [l.strip() for l in req.test_case.splitlines() if l.strip()]
    platform  = (req.platform or "android").lower()

    code_lines:   list[tuple] = []
    unrecognized: list[str]   = []
    report:       list[dict]  = []

    for step in raw_steps:
        parsed = generate_step(step, platform)
        if parsed:
            code_lines.append(("rule", step, "\n".join(parsed)))
        else:
            code_lines.append(("llm", step, ""))
            unrecognized.append(step)

    llm_results: dict[str, str] = {}
    if unrecognized:
        llm_results = await (_ask_llm_ios(unrecognized) if platform == "ios" else _ask_llm_java(unrecognized))

    final_lines: list[str] = []
    for kind, step, rule_code in code_lines:
        if kind == "rule":
            final_lines.append(rule_code)
            report.append({"step": step, "method": "rule"})
        else:
            llm_code = llm_results.get(step, "")
            if not llm_code:
                llm_code = f"// TODO (anlaşılamadı): {step}\nThread.sleep(1000);"
                method = "todo"
            else:
                llm_code = f"// {step}\n" + llm_code
                method = "llm"
            final_lines.append(llm_code)
            report.append({"step": step, "method": method})
        final_lines.append("")

    steps_code = "\n".join(final_lines)
    if platform == "ios":
        final_java = build_ios_template(
            steps_code=steps_code,
            bundle_id=req.bundle_id,
            udid=req.udid,
            device_name=req.device_name,
            platform_version=req.platform_version,
            appium_url=req.appium_url,
            no_reset=req.no_reset,
        )
    else:
        final_java = build_android_template(
            steps_code=steps_code,
            app_package=req.app_package,
            app_activity=req.app_activity,
            udid=req.udid,
            device_name=req.device_name,
            platform_version=req.platform_version,
            appium_url=req.appium_url,
            no_reset=req.no_reset,
        )

    warnings = [f"Anlaşılamayan adım: {r['step']}" for r in report if r["method"] == "todo"]

    return {
        "success":  True,
        "script":   final_java,
        "report":   report,
        "warnings": warnings,
    }
