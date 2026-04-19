"""
Java Test Generator Router
===========================
Türkçe doğal dil test adımlarını Java Appium koduna çevirir.
Kural motoru + LLM fallback (Ollama gemma3:4b).
Sadece dönüşüm — çalıştırma yok.
"""

import re
import textwrap
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User

router = APIRouter(prefix="/api/java-gen", tags=["java-generator"])

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class JavaGenerateRequest(BaseModel):
    test_case:        str
    appium_url:       Optional[str]  = "http://localhost:4723"
    platform_version: Optional[str]  = "15"
    device_name:      Optional[str]  = "Android Device"
    udid:             Optional[str]  = ""
    app_package:      Optional[str]  = ""
    app_activity:     Optional[str]  = ""
    no_reset:         Optional[bool] = True
    class_name:       Optional[str]  = "GeneratedTest"


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1: YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════════════════

def _clean_step(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^(adım|adim|step)\s*\d+\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*[→>]+\s*[Bb]eklenen:.*$', '', s)
    return s.strip()


def _extract_quoted(text: str) -> list[str]:
    return re.findall(
        r'["\u201c\u201d\u2018\u2019]([^"\u201c\u201d\u2018\u2019]+)["\u201c\u201d\u2018\u2019]',
        text
    )


def _je(s: str) -> str:
    """Java string literal için escape."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2: KURAL MOTORU  (Türkçe adım → Java satırları)
# ══════════════════════════════════════════════════════════════════════════════

def _rule_java(step: str) -> list[str] | None:
    s      = _clean_step(step)
    if not s:
        return None
    sl     = s.lower()
    quoted = _extract_quoted(s)

    CLICK_WORDS  = r'(?:t[iı]kla|tikla|bas|click|tap|se[cç]|a[cç]|dokun)'
    INPUT_WORDS  = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type|enter\b)'
    ASSERT_WORDS = r'(?:g[oö]r\b|do[gğ]rula|kontrol|assert|verify|var m[iı]|bekleniyor|görünmeli)'

    # ── Pasif Türkçe: "X butonuna tıklanır" ──────────────────────────────────
    _PC = re.search(
        r'^(.+?)\s+(?:butonu?na|elementine|alanına|üzerine|simgesine|ikonuna'
        r'|bağlantısına|sekmesin[ei]|linkine)\s+t[ıi]klan[ıi]r\.?\s*$',
        s, re.IGNORECASE
    )
    if _PC:
        text = _je(_PC.group(1).strip())
        return [
            f'// {s}',
            f'driver.findElement(By.xpath("//*[@text=\\"{text}\\"]")).click();',
            'Thread.sleep(800);',
        ]

    # ── "X açılır" ───────────────────────────────────────────────────────────
    _AC = re.search(r'^(.+?)\s+a[çc][ıi]l[ıi]r\.?\s*$', s, re.IGNORECASE)
    if _AC:
        text = _je(_AC.group(1).strip())
        return [
            f'// {s}',
            f'driver.findElement(By.xpath("//*[@text=\\"{text}\\"]")).click();',
            'Thread.sleep(1000);',
        ]

    # ── "bir X girilir" (değer belirtilmemiş, otomatik doldur) ───────────────
    if re.search(r'\bgirilir\b', sl) and not quoted:
        _GM = re.search(r'(?:bir\s+)?(.+?)\s+(?:alan[ıi]na\s+)?girilir\.?\s*$', s, re.IGNORECASE)
        if _GM:
            ctx   = _GM.group(1)
            is_pw = bool(re.search(r'şifre|sifre|password|pin|parola', ctx, re.IGNORECASE))
            value = '121212' if is_pw else '12345678901' if re.search(r'tc|kimlik', ctx, re.IGNORECASE) else 'test_degeri'
            xpath = '//android.widget.EditText[@password="true"]' if is_pw else '//android.widget.EditText[1]'
            return [
                f'// {s}  [otomatik değer: {value}]',
                f'{{ WebElement _f = driver.findElement(By.xpath("{xpath}"));',
                '  _f.click(); _f.clear();',
                f'  _f.sendKeys("{value}"); }}',
                'Thread.sleep(500);',
            ]

    # ── Tıklama ───────────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        text = _je(quoted[0])
        return [
            f'// {s}',
            f'driver.findElement(By.xpath("//*[@text=\\"{text}\\"]")).click();',
            'Thread.sleep(800);',
        ]

    # ── Doğrulama ─────────────────────────────────────────────────────────────
    if re.search(ASSERT_WORDS, sl) and quoted:
        text = _je(quoted[0])
        return [
            f'// {s}',
            f'assert driver.findElement(By.xpath("//*[@text=\\"{text}\\"]")).isDisplayed()',
            f'       : "Beklenen metin ekranda yok: {text}";',
        ]

    # ── Metin girişi: alan + değer (tek satır) ────────────────────────────────
    if re.search(INPUT_WORDS, sl) and len(quoted) >= 2:
        target = _je(quoted[0])
        value  = _je(quoted[-1])
        is_pw  = bool(re.search(r'şifre|sifre|password|pin|parola', sl))
        xpath  = '//android.widget.EditText[@password="true"]' if is_pw else '//android.widget.EditText[1]'
        return [
            f'// {s}',
            f'driver.findElement(By.xpath("//*[@text=\\"{target}\\"]")).click();',
            f'{{ WebElement _f = driver.findElement(By.xpath("{xpath}"));',
            '  _f.click(); _f.clear();',
            f'  _f.sendKeys("{value}"); }}',
            'Thread.sleep(500);',
        ]

    # ── Sadece yaz (tek quoted) ───────────────────────────────────────────────
    if re.search(INPUT_WORDS, sl) and len(quoted) == 1:
        value = _je(quoted[0])
        is_pw = bool(re.search(r'şifre|sifre|password|pin|parola', sl))
        xpath = '//android.widget.EditText[@password="true"]' if is_pw else '//android.widget.EditText[1]'
        return [
            f'// {s}',
            f'{{ WebElement _f = driver.findElement(By.xpath("{xpath}"));',
            '  _f.click(); _f.clear();',
            f'  _f.sendKeys("{value}"); }}',
            'Thread.sleep(500);',
        ]

    # ── Scroll ────────────────────────────────────────────────────────────────
    if re.search(r'a[sş]a[gğ][iı]\s*kaydır|scroll\s*down|swipe\s*down', sl):
        return [f'// {s}', 'driver.swipe(540, 1400, 540, 400, 800);', 'Thread.sleep(500);']
    if re.search(r'yukar[iı]\s*kaydır|scroll\s*up|swipe\s*up', sl):
        return [f'// {s}', 'driver.swipe(540, 400, 540, 1400, 800);', 'Thread.sleep(500);']
    if re.search(r'(?:kaydır|scroll|swipe)', sl):
        return [f'// {s}', 'driver.swipe(540, 1400, 540, 400, 800);', 'Thread.sleep(500);']

    # ── Geri ──────────────────────────────────────────────────────────────────
    if re.search(r'geri\s*d[oö]n|geri\s*git|back\b', sl):
        return [f'// {s}', 'driver.navigate().back();', 'Thread.sleep(500);']

    # ── Bekle ─────────────────────────────────────────────────────────────────
    if re.search(r'bekle|wait|sleep', sl):
        m  = re.search(r'(\d+)', s)
        ms = int(m.group(1)) * 1000 if m else 2000
        return [f'// {s}', f'Thread.sleep({ms});']

    return None  # Tanınmadı → LLM


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3: ŞABLON
# ══════════════════════════════════════════════════════════════════════════════

def _build_java_template(req: JavaGenerateRequest, steps_code: str) -> str:
    pkg      = req.app_package      or ""
    act      = req.app_activity     or ""
    udid     = req.udid             or ""
    device   = req.device_name      or "Android Device"
    version  = req.platform_version or "15"
    appium   = req.appium_url       or "http://localhost:4723"
    no_reset = "true" if req.no_reset else "false"
    cls_name = re.sub(r'[^a-zA-Z0-9_]', '', req.class_name or "GeneratedTest") or "GeneratedTest"

    udid_line = f'\n        caps.setCapability("udid", "{udid}");'             if udid else ""
    act_line  = f'\n        caps.setCapability("appActivity", "{act}");'       if act  else ""
    pkg_line  = f'\n        caps.setCapability("appPackage", "{pkg}");'        if pkg  else ""
    act_start = f'driver.activateApp("{pkg}");'                                if pkg  else "// app_package girilmedi"
    act_end   = f'driver.terminateApp("{pkg}");'                               if pkg  else ""

    body = textwrap.indent(steps_code.rstrip(), "        ")

    return f"""\
import io.appium.java_client.android.AndroidDriver;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import java.net.URL;
import java.time.Duration;

public class {cls_name} {{

    public static void main(String[] args) throws Exception {{

        // ── CONFIG ────────────────────────────────────────────────────────
        DesiredCapabilities caps = new DesiredCapabilities();
        caps.setCapability("platformName", "Android");
        caps.setCapability("platformVersion", "{version}");
        caps.setCapability("deviceName", "{device}");{udid_line}
        caps.setCapability("automationName", "UiAutomator2");{pkg_line}{act_line}
        caps.setCapability("appium:noReset", {no_reset});

        AndroidDriver driver = new AndroidDriver(new URL("{appium}"), caps);
        driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));
        // ── CONFIG END ────────────────────────────────────────────────────

        // Uygulamayı başlat / ön plana getir
        {act_start}
        Thread.sleep(2000);

        // ── TEST ADIMLARI ─────────────────────────────────────────────────
{body}

        // ── TEST SONU ─────────────────────────────────────────────────────
        {act_end}
        driver.quit();
    }}
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4: LLM FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

async def _ask_llm_java(steps: list[str]) -> dict[str, str]:
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    prompt = f"""Write Java Appium code for each test step. Use AndroidDriver.
Output only Java statements + // comments. No imports, no class/method wrapper.
Use: driver.findElement(By.xpath(...)).click(); | .sendKeys("x"); | Thread.sleep(ms);
For text elements use: By.xpath("//*[@text=\\"X\\"]")
For inputs use: driver.findElement(By.className("android.widget.EditText")).sendKeys("x");

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
            code_only = "\n".join(
                l for l in blocks[i].splitlines()
                if l.strip().startswith("//") or
                   re.match(r'^\s*(driver|Thread|assert|WebElement|\{)', l.strip())
            )
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

    code_lines:   list[tuple] = []
    unrecognized: list[str]   = []
    report:       list[dict]  = []

    for step in raw_steps:
        parsed = _rule_java(step)
        if parsed:
            code_lines.append(("rule", step, "\n".join(parsed)))
        else:
            code_lines.append(("llm", step, ""))
            unrecognized.append(step)

    llm_results: dict[str, str] = {}
    if unrecognized:
        llm_results = await _ask_llm_java(unrecognized)

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
    final_java  = _build_java_template(req, steps_code)

    warnings = [f"Anlaşılamayan adım: {r['step']}" for r in report if r["method"] == "todo"]

    return {
        "success":  True,
        "script":   final_java,
        "report":   report,
        "warnings": warnings,
    }
