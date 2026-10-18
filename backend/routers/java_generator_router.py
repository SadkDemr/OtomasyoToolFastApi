"""
Java Test Generator Router
===========================
Türkçe doğal dil test adımlarını Java Appium koduna çevirir.
Kural motoru + LLM fallback (Ollama gemma3:4b).
Sadece dönüşüm — çalıştırma yok.
"""

from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User
from services.ai_service import get_ollama_config
from services.java_generator_service import (
    generate_step, is_custom_step, expand_multi_target_step,
    is_full_login_script, build_from_login_script,
    use_locators, track_locator_hits,
)
from services import locator_service
from services.appium_codegen_service import build_android_template, build_ios_template
from services.java_step_template_service import find_step_override, get_active_login

router = APIRouter(prefix="/api/java-gen", tags=["java-generator"])


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
    use_ai_fallback:  Optional[bool] = True
    include_default_login: Optional[bool] = True
    locator_file:     Optional[str]  = ""   # workspace/locators/<isim>.json (kayıt modu XPath'leri)


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
        if not t or t.startswith("```"):
            continue
        if t.startswith("//") or t.endswith((';', '{', '}')):
            lines.append(l)
    if lines:
        return lines
    # Sıkı filtre hiçbir satırı geçiremediyse (küçük model markdown/serbest
    # metin formatına kayabiliyor) — boş TODO placeholder'a düşmek yerine
    # LLM'in ham çıktısını (fence satırları hariç) olduğu gibi kullan;
    # hiç yoktan iyi ve kullanıcı elle düzeltebilir.
    return [l for l in block.splitlines() if l.strip() and not l.strip().startswith("```")]


_JAVA_STEP_RULES = """Rules:
- Click text/button: driver.findElement(By.xpath("//*[@text='X']")).click();
- Type text: driver.executeScript("mobile: type", Map.of("text", "VALUE")); then driver.hideKeyboard();
- Scroll/swipe: do NOT use driver.executeScript("mobile:...") — it is unreliable across driver versions. Output only: // TODO: manual scroll/swipe gesture needed
- Back key: driver.pressKey(new KeyEvent(AndroidKey.BACK));
- Thread.sleep(ms) only when step explicitly requires waiting
- Only use these types: driver, By, WebElement, Map, Thread, KeyEvent, AndroidKey. Do not declare or use any other class."""

_IOS_STEP_RULES = """Rules:
- Click element: driver.findElement(AppiumBy.xpath("//*[@name='X' or @label='X' or @value='X']")).click();
- Type text: driver.switchTo().activeElement().sendKeys("VALUE"); try { driver.hideKeyboard(); } catch (Exception ignored) {}
- Assert visible: driver.findElement(AppiumBy.xpath("//*[@name='X' or @label='X' or @value='X']")).isDisplayed();
- Scroll/swipe: do NOT use driver.executeScript("mobile:...") — it is unreliable across driver versions. Output only: // TODO: manual scroll/swipe gesture needed
- Back: driver.navigate().back();
- Wait: Thread.sleep(ms);
- Only use these types: driver, AppiumBy, WebElement, Thread. Do not declare or use any other class."""


async def _ask_llm_step(client: httpx.AsyncClient, step: str, header: str, rules: str) -> str:
    """Tek bir adım için LLM'e ayrı istek atar.
    Önceki sürüm tüm tanınmayan adımları TEK bir prompt'ta topluca gönderip
    yanıtı boş satırlarla (\\n\\n) adımlara bölüyordu — küçük model (gemma3:4b)
    bu ayraç formatını her zaman tutturamadığı için 2., 3. ... adımlar kendi
    bloğunu bulamıyor ve LLM hiç çalıştırılmamış gibi TODO/sleep placeholder'a
    düşüyordu. Adım başına ayrı istek, hizalama riskini tamamen kaldırır."""
    prompt = f"""{header}
Output only Java statements + // comments, nothing else (no markdown fences, no explanation).
{rules}

Step: {step}

Java code:"""
    try:
        cfg = get_ollama_config()
        resp = await client.post(cfg["url"], json={
            "model": cfg["model"],
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 200}
        })
        raw = resp.json().get("response", "")
    except Exception:
        raw = ""
    code_only = "\n".join(_java_code_lines(raw))
    return code_only if code_only else f"// TODO: {step}\nThread.sleep(1000);"


async def _ask_llm_java(steps: list[str]) -> dict[str, str]:
    header = "Write Java Appium code for this single test step. Use AndroidDriver."
    result = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for step in steps:
            result[step] = await _ask_llm_step(client, step, header, _JAVA_STEP_RULES)
    return result


async def _ask_llm_ios(steps: list[str]) -> dict[str, str]:
    header = "Write Java Appium code for this single iOS test step. Use IOSDriver with XCUITest. Variable already available: IOSDriver 'driver'."
    result = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for step in steps:
            result[step] = await _ask_llm_step(client, step, header, _IOS_STEP_RULES)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT'LER
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
async def ollama_status():
    cfg = get_ollama_config()
    tags_url = cfg["url"].replace("/api/generate", "/api/tags")
    configured_model_base = cfg["model"].split(":")[0]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(tags_url)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                model_available = any(m.split(":")[0] == configured_model_base for m in models)
                return {"online": True, "model_available": model_available, "configured_model": cfg["model"]}
    except Exception:
        pass
    return {"online": False, "model_available": False, "configured_model": cfg["model"]}


@router.post("/generate")
async def generate_java(
    req: JavaGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_steps: list[str] = []
    for l in req.test_case.splitlines():
        l = l.strip()
        if not l:
            continue
        # Virgül/noktalı virgülle ayrılmış çoklu hedefli tek satır varsa
        # (örn. "X","Y","Z" kartının olduğu görülür) her hedef ayrı adım
        # olarak işlensin diye burada genişletilir.
        raw_steps.extend(expand_multi_target_step(l))
    platform  = (req.platform or "android").lower()

    code_lines:   list[tuple] = []
    unrecognized: list[str]   = []
    report:       list[dict]  = []
    loc_warnings: list[str]   = []

    lookup = None
    if (req.locator_file or "").strip():
        if platform != "android":
            loc_warnings.append("Locator dosyası Android kaydından üretilir — iOS'ta kullanılmadı.")
        else:
            from routers.ai_test_generator_router import _get_user_workspace
            ws = _get_user_workspace(current_user.id, db)
            try:
                if not ws:
                    raise FileNotFoundError("Git workspace bulunamadı")
                lookup = locator_service.load_lookup(ws.local_path, req.locator_file.strip())
            except (FileNotFoundError, ValueError) as e:
                loc_warnings.append(f"Locator dosyası kullanılamadı: {e}")

    locator_steps: dict[str, list] = {}
    with use_locators(lookup):
        for step in raw_steps:
            # Admin'in tanımladığı kalıp step eşleşmesi kural motorundan ÖNCE
            # kontrol edilir — tam eşleşirse kural motorunu/LLM'i tamamen bypass eder.
            override = find_step_override(db, step, platform)
            if override:
                code_lines.append(("override", step, "\n".join(override)))
                continue
            with track_locator_hits() as hits:
                parsed = generate_step(step, platform)
            if hits:
                locator_steps[step] = hits
            if parsed:
                # "(Fonksiyon gerekli)" ile işaretlenen adımlar raporda ayrı gösterilir —
                # kod üretilmediği, kullanıcının elle fonksiyon yazacağı adımlardır.
                kind = "custom" if is_custom_step(step) else "rule"
                code_lines.append((kind, step, "\n".join(parsed)))
            else:
                code_lines.append(("llm", step, ""))
                unrecognized.append(step)

    llm_results: dict[str, str] = {}
    if unrecognized and req.use_ai_fallback:
        llm_results = await (_ask_llm_ios(unrecognized) if platform == "ios" else _ask_llm_java(unrecognized))

    final_lines: list[str] = []
    for kind, step, rule_code in code_lines:
        if kind in ("rule", "custom", "override"):
            final_lines.append(rule_code)
            entry = {"step": step, "method": kind}
            if step in locator_steps:
                entry["locator"] = True
            report.append(entry)
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

    login_code = get_active_login(db, platform) if req.include_default_login else ""
    scenario_code = "// ── SENARYO ADIMLARI ──────────────────────────────────────────────\n" + "\n".join(final_lines)
    steps_code = (login_code.rstrip() + "\n\n" if login_code else "") + scenario_code

    if login_code and is_full_login_script(login_code):
        # Login betiği config + driver dahil tam betik: çıktının başı birebir o
        # betik olur, senaryo adımları altına eklenir (request'teki cihaz/appium
        # alanları kullanılmaz — betik bunları vars.get(...) ile alıyor).
        final_java = build_from_login_script(login_code, scenario_code)
    elif platform == "ios":
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

    warnings = loc_warnings + [f"Anlaşılamayan adım: {r['step']}" for r in report if r["method"] == "todo"]

    return {
        "success":  True,
        "script":   final_java,
        "report":   report,
        "warnings": warnings,
    }
