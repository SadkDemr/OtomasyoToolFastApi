"""
Locator Service — kayıt modunda dokunulan elemanların XPath'lerini kullanıcının
oluşturduğu locator dosyasına (workspace/locators/<isim>.json) yazar; kayıttaki
adımları Java Generator'ın içe aktardığı ADO Excel formatına çevirir.

XPath önceliği: resource-id > content-desc > sınıf+metin > metin > (kırılgan) index.
Her aday sayfa kaynağında TEK elemana denk geliyorsa kabul edilir. Rakam içeren
(bakiye, isim, tarih gibi kişiye/veriye bağlı) metinler XPath'e yazılmaz.
"""

import json
import re
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

LOCATOR_DIR = "locators"

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_file_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ── XPath üretimi ───────────────────────────────────────────────────────────

def _q(v: str) -> str:
    """XPath string literal (tek/çift tırnak içerebilir)."""
    if "'" not in v:
        return f"'{v}'"
    if '"' not in v:
        return f'"{v}"'
    parts = v.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def _stable_text(v: str) -> bool:
    """XPath'e yazılabilir mi: boş değil, kısa, rakamsız (veriye bağlı değil)."""
    v = (v or "").strip()
    return bool(v) and len(v) <= 60 and not re.search(r"\d", v)


def _cls(el) -> str:
    return el.get("class") or el.tag


# ── iOS sayfa kaynağı → Android benzeri öznitelikler ────────────────────────
# Kayıt modu, harita ve locator üretimi Android sayfa kaynağına göre yazıldı
# (bounds="[x1,y1][x2,y2]", text, resource-id, clickable). XCUITest kaynağında bunlar
# x/y/width/height, label/value/name olarak gelir; kaynak alındığı anda bu öznitelikler
# eklenir (etiketler XCUIElementType... olarak kalır) → aynı ayrıştırıcılar iPhone'da da
# çalışır. Üretilen XPath'ler (@text, @resource-id, @hint) koşumda iOS uyum katmanıyla
# (@label/@value/@name, @placeholderValue) yeniden çevrilir. Koordinatlar nokta (point).
IOS_INPUT_CLASSES = {"XCUIElementTypeTextField", "XCUIElementTypeSecureTextField",
                     "XCUIElementTypeSearchField", "XCUIElementTypeTextView"}
_IOS_CLICKABLE = IOS_INPUT_CLASSES | {
    "XCUIElementTypeButton", "XCUIElementTypeCell", "XCUIElementTypeLink", "XCUIElementTypeSwitch",
    "XCUIElementTypeTab", "XCUIElementTypeSegmentedControl", "XCUIElementTypeMenuItem",
    "XCUIElementTypeStepper", "XCUIElementTypeSlider", "XCUIElementTypeKey",
    "XCUIElementTypePickerWheel", "XCUIElementTypeToggle"}


def is_input_class(cls: str) -> bool:
    """Yazı alanı mı (Android EditText / iOS TextField...)?"""
    return "EditText" in (cls or "") or cls in IOS_INPUT_CLASSES


def normalize_ios_source(source_xml: Optional[str]) -> Optional[str]:
    if not source_xml or "XCUIElementType" not in source_xml:
        return source_xml
    try:
        root = ET.fromstring(source_xml)
    except Exception:
        return source_xml
    for el in root.iter():
        typ = el.get("type") or el.tag
        el.set("class", typ)
        try:
            x, y, w, h = (int(float(el.get(k))) for k in ("x", "y", "width", "height"))
        except (TypeError, ValueError):
            continue
        if el.get("visible") != "false" and w > 0 and h > 0:   # görünmeyen eleman dokunulamaz
            el.set("bounds", f"[{x},{y}][{x + w},{y + h}]")
        label, value, name = ((el.get(k) or "").strip() for k in ("label", "value", "name"))
        placeholder = (el.get("placeholderValue") or "").strip()
        if typ in IOS_INPUT_CLASSES:
            text = value if value and value != placeholder else ""   # alana yazılmış değer
        else:
            text = label or value
        el.set("text", text)
        el.set("hint", placeholder)
        # name, label'dan farklıysa gerçek erişilebilirlik kimliğidir (Android resource-id karşılığı)
        if name and name != label and name != text and _stable_text(name):
            el.set("resource-id", name)
        el.set("clickable", "true" if typ in _IOS_CLICKABLE else "false")
    return ET.tostring(root, encoding="unicode")


def _parse(source_xml: str):
    """→ (elemanlar [(el, (x1,y1,x2,y2))], parent haritası)"""
    root = ET.fromstring(source_xml)
    parent = {c: p for p in root.iter() for c in p}
    els = []
    for el in root.iter():
        m = _BOUNDS_RE.match(el.get("bounds") or "")
        if m:
            els.append((el, tuple(map(int, m.groups()))))
    return els, parent


def _abs_path(el, parent) -> str:
    """Kırılgan son çare: kökten sınıf+sıra ile tam yol."""
    parts = []
    cur = el
    while cur in parent:
        p = parent[cur]
        same = [c for c in p if c.tag == cur.tag]
        parts.append(f"{cur.tag}[{same.index(cur) + 1}]" if len(same) > 1 else cur.tag)
        cur = p
    return "/" + "/".join([cur.tag] + parts[::-1])


def _candidates(el, kind: str) -> list[tuple[str, Callable]]:
    """(xpath, eşleşme fonksiyonu) — sağlamdan zayıfa."""
    rid = (el.get("resource-id") or "").strip()
    desc = (el.get("content-desc") or "").strip()
    text = (el.get("text") or "").strip()
    hint = (el.get("hint") or "").strip()
    cls = _cls(el)
    out = []
    if rid:
        out.append((f"//*[@resource-id={_q(rid)}]", lambda e: e.get("resource-id") == rid))
    if _stable_text(desc):
        out.append((f"//*[@content-desc={_q(desc)}]", lambda e: e.get("content-desc") == desc))
    if kind == "input":
        # Yazı alanının text'i girilen değerdir → kullanılmaz; ipucu (hint) kullanılır
        if _stable_text(hint):
            out.append((f"//{cls}[@hint={_q(hint)}]", lambda e: _cls(e) == cls and e.get("hint") == hint))
    elif _stable_text(text):
        out.append((f"//{cls}[@text={_q(text)}]", lambda e: _cls(e) == cls and e.get("text") == text))
        out.append((f"//*[@text={_q(text)}]", lambda e: e.get("text") == text))
        if rid:
            out.append((f"//*[@resource-id={_q(rid)} and @text={_q(text)}]",
                        lambda e: e.get("resource-id") == rid and e.get("text") == text))
    return out


def _indexed(el, els, kind: str) -> Optional[str]:
    """(//X)[n] — sayfadaki sıraya bağlı, kırılgan. Aynı yazılı birden fazla eleman
    varsa ("Devam" ×2) sıra, yazıyla birlikte verilir."""
    rid = (el.get("resource-id") or "").strip()
    text = (el.get("text") or "").strip()
    cls = _cls(el)
    if rid:
        pred, base = (lambda e: e.get("resource-id") == rid), f"//*[@resource-id={_q(rid)}]"
    elif kind != "input" and _stable_text(text):
        pred, base = (lambda e: _cls(e) == cls and e.get("text") == text), f"//{cls}[@text={_q(text)}]"
    else:
        pred, base = (lambda e: _cls(e) == cls), f"//{cls}"
    same = [e for e, _ in els if pred(e)]
    if el in same:
        return f"({base})[{same.index(el) + 1}]"
    return None


def _label_xpath(el, els, label: str) -> Optional[str]:
    """Yazı alanı için: etiketin ardından gelen ilk aynı sınıflı alan
    (//*[@text='TC Kimlik']/following::android.widget.EditText[1])."""
    if not _stable_text(label):
        return None
    order = [e for e, _ in els]
    labels = [e for e in order if (e.get("text") or "").strip() == label or
              (e.get("content-desc") or "").strip() == label]
    if len(labels) != 1:
        return None
    cls = _cls(el)
    after = order[order.index(labels[0]) + 1:]
    first = next((e for e in after if _cls(e) == cls), None)
    if first is not el:
        return None
    attr = "text" if (labels[0].get("text") or "").strip() == label else "content-desc"
    return f"//*[@{attr}={_q(label)}]/following::{cls}[1]"


def _xpaths_for(el, els, parent, kind: str, label: str = "") -> dict:
    unique = []
    for xp, pred in _candidates(el, kind):
        if sum(1 for e, _ in els if pred(e)) == 1:
            unique.append(xp)
    if kind == "input":
        lx = _label_xpath(el, els, label)
        if lx:
            unique.append(lx)
    fragile = not unique
    if fragile:
        idx = _indexed(el, els, kind)
        unique = [idx] if idx else []
        unique.append(_abs_path(el, parent))
    return {
        "xpath": unique[0],
        "alternatives": unique[1:3],
        "fragile": fragile,
        "resource_id": el.get("resource-id") or "",
        "class": _cls(el),
        "desc": (el.get("content-desc") or "").strip(),
        "text": (el.get("text") or "").strip(),   # iOS ikonlarının label'ı (OCR okuyamasa da)
    }


def locate(source_xml: Optional[str], x: int, y: int, kind: str, label: str = "") -> Optional[dict]:
    """Sayfa kaynağında (x, y) noktasındaki elemanın XPath'leri.
    kind: tap | input | verify; label: yazı alanının adı (input)"""
    if not source_xml:
        return None
    try:
        els, parent = _parse(source_xml)
    except Exception:
        return None
    hits = [(el, b) for el, b in els if b[0] <= x <= b[2] and b[1] <= y <= b[3]]
    if not hits:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    hits.sort(key=lambda h: area(h[1]))
    smallest = hits[0][0]

    order = [smallest]
    if kind == "input":
        edits = [el for el, _ in hits if is_input_class(_cls(el))]
        order = edits[:1] or order
    elif kind == "tap":
        # Yazının içine tıklanmış olabilir → tıklanabilir ilk üst eleman (buton) öncelikli;
        # ekranın yarısından büyük kapsayıcılar (liste, sayfa) atlanır
        screen = max(area(b) for _, b in els) or 1
        cur = smallest
        while cur is not None and cur.get("clickable") != "true":
            cur = parent.get(cur)
        if cur is not None and cur is not smallest:
            b = next((b for e, b in els if e is cur), None)
            if b and area(b) <= screen * 0.5:
                order = [cur, smallest]

    best = None
    for el in order:
        r = _xpaths_for(el, els, parent, kind, label)
        if not r["fragile"]:
            return r
        best = best or r
    return best


# ── Locator dosyası ─────────────────────────────────────────────────────────

def sanitize_name(name: str) -> str:
    n = re.sub(r"\.json$", "", (name or "").strip(), flags=re.IGNORECASE)
    n = re.sub(r"[^\w\s-]", "", n, flags=re.UNICODE)
    n = re.sub(r"\s+", "_", n.strip())
    return n[:64]


def _dir(ws_path: str) -> Path:
    return Path(ws_path) / LOCATOR_DIR


def file_path(ws_path: str, name: str) -> Path:
    n = sanitize_name(name)
    if not n:
        raise ValueError("Geçersiz dosya adı")
    return _dir(ws_path) / f"{n}.json"


def _lock_for(p: Path) -> threading.Lock:
    with _locks_guard:
        return _file_locks.setdefault(str(p.resolve()), threading.Lock())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data: dict) -> None:
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def list_files(ws_path: str) -> list[dict]:
    d = _dir(ws_path)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            data = _read(f)
        except Exception:
            continue
        out.append({"name": f.stem, "app": data.get("app", ""),
                    "count": len(data.get("elements", {})),
                    "created_by": data.get("created_by", ""),
                    "updated_at": data.get("updated_at", "")})
    return out


def create_file(ws_path: str, name: str, app: str, username: str) -> dict:
    p = file_path(ws_path, name)
    if p.exists():
        raise FileExistsError(f"'{p.stem}' adında bir locator dosyası zaten var")
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": p.stem, "app": app or "", "platform": "android",
            "created_by": username, "created_at": _now(), "updated_at": _now(),
            "elements": {}}
    _write(p, data)
    return data


def read_file(ws_path: str, name: str) -> dict:
    p = file_path(ws_path, name)
    if not p.exists():
        raise FileNotFoundError(f"'{name}' locator dosyası bulunamadı")
    return _read(p)


def add_element(path: str, key: str, loc: dict, action: str, screen: str,
                app: str, username: str, textless: bool = False) -> dict:
    """Elemanı dosyaya ekler/günceller. Aynı ad farklı XPath ile gelirse (başka ekranda
    aynı yazı) yeni XPath alternatiflere girer; kırılgan olan sağlamıyla yer değiştirir.
    textless: ekranda yazısı olmayan eleman (iconN) — doğrulamada da XPath kullanılır."""
    p = Path(path)
    key = (key or "").strip()
    if not key or not loc or not loc.get("xpath"):
        return {}
    with _lock_for(p):
        data = _read(p) if p.exists() else {"name": p.stem, "elements": {}}
        if app and not data.get("app"):
            data["app"] = app
        els = data.setdefault("elements", {})
        cur = els.get(key)
        if cur is None:
            cur = {"xpath": loc["xpath"], "alternatives": list(loc.get("alternatives") or []),
                   "action": action, "class": loc.get("class", ""),
                   "resource_id": loc.get("resource_id", ""), "fragile": bool(loc.get("fragile")),
                   "screens": [screen] if screen else [], "seen": 1,
                   "added_by": username, "updated_at": _now()}
            els[key] = cur
        else:
            alts = cur.setdefault("alternatives", [])
            new_xp = loc["xpath"]
            if new_xp != cur["xpath"]:
                if cur.get("fragile") and not loc.get("fragile"):
                    alts.insert(0, cur["xpath"])
                    cur.update({"xpath": new_xp, "fragile": False, "class": loc.get("class", ""),
                                "resource_id": loc.get("resource_id", "")})
                elif new_xp not in alts:
                    alts.append(new_xp)
            for a in loc.get("alternatives") or []:
                if a != cur["xpath"] and a not in alts:
                    alts.append(a)
            cur["alternatives"] = alts[:6]
            if screen and screen not in cur.setdefault("screens", []):
                cur["screens"].append(screen)
            cur["seen"] = cur.get("seen", 0) + 1
            cur["updated_at"] = _now()
        if textless:
            cur["textless"] = True
        data["updated_at"] = _now()
        _write(p, data)
        return {"key": key, **cur}


def auto_name(path: str, loc: dict, prefix: str = "icon") -> str:
    """Yazısız eleman (ikon) için ad: aynı XPath'li kayıt varsa onun adı (aynı ikona tekrar
    dokunuldu), yoksa ilk boş iconN. Kaydetmez."""
    p = Path(path)
    with _lock_for(p):
        els = (_read(p) if p.exists() else {}).get("elements", {})
    key = next((k for k, v in els.items() if v.get("xpath") == loc.get("xpath")), None)
    if key:
        return key
    n = 1
    while f"{prefix}{n}" in els:
        n += 1
    return f"{prefix}{n}"


def add_auto_named(path: str, loc: dict, screen: str, app: str, username: str,
                   action: str = "tap", prefix: str = "icon") -> str:
    """auto_name + kaydet (textless) → eleman adı"""
    key = auto_name(path, loc, prefix)
    add_element(path, key, loc, action, screen, app, username, textless=True)
    return key


def _looks_xpath(v: str) -> bool:
    return (v or "").strip().startswith(("/", "("))


def update_element(ws_path: str, name: str, key: str, new_key: str, xpath: str,
                   alternatives: list[str], username: str) -> dict:
    """Elle düzeltme: XPath/alternatifler/ad. Elle girilen XPath kırılgan sayılmaz."""
    p = file_path(ws_path, name)
    key, new_key, xpath = (key or "").strip(), (new_key or key or "").strip(), (xpath or "").strip()
    alts = [a.strip() for a in alternatives or [] if a and a.strip()]
    if not new_key:
        raise ValueError("Eleman adı boş olamaz")
    if not _looks_xpath(xpath):
        raise ValueError("XPath '/' ya da '(' ile başlamalı")
    bad = [a for a in alts if not _looks_xpath(a)]
    if bad:
        raise ValueError(f"Geçersiz alternatif XPath: {bad[0]}")
    with _lock_for(p):
        if not p.exists():
            raise FileNotFoundError(f"'{name}' locator dosyası bulunamadı")
        data = _read(p)
        els = data.setdefault("elements", {})
        if key not in els:
            raise KeyError(f"'{key}' elemanı dosyada yok")
        if new_key != key and new_key in els:
            raise ValueError(f"'{new_key}' adında bir eleman zaten var")
        el = els[key]
        el.update({"xpath": xpath, "alternatives": [a for a in dict.fromkeys(alts) if a != xpath],
                   "fragile": False, "edited_by": username, "updated_at": _now()})
        # ad değişse bile eleman listedeki yerinde kalsın
        data["elements"] = {(new_key if k == key else k): v for k, v in els.items()}
        data["updated_at"] = _now()
        _write(p, data)
        return {"key": new_key, **el}


def delete_element(ws_path: str, name: str, key: str) -> None:
    p = file_path(ws_path, name)
    with _lock_for(p):
        if not p.exists():
            raise FileNotFoundError(f"'{name}' locator dosyası bulunamadı")
        data = _read(p)
        if data.get("elements", {}).pop(key, None) is None:
            raise KeyError(f"'{key}' elemanı dosyada yok")
        data["updated_at"] = _now()
        _write(p, data)


# ── Kod üretiminde kullanım (Java Generator / AI Generator) ─────────────────

def norm_key(s: str) -> str:
    """Adımdaki hedef ↔ dosyadaki eleman adı eşleştirmesi (büyük/küçük harf, Türkçe İ/ı,
    tırnak ve boşluk farkı önemsiz)."""
    s = (s or "").strip().strip("\"'“”‘’").strip()
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"\s+", " ", s)


def build_lookup(data: dict) -> dict:
    return {norm_key(k): v for k, v in (data.get("elements") or {}).items()}


def load_lookup(ws_path: str, name: str) -> dict:
    return build_lookup(read_file(ws_path, name))


def resolve_xpath(lookup: Optional[dict], target: Optional[str], action: str,
                  text_fallback: Optional[str] = None) -> Optional[str]:
    """Hedefin locator dosyasındaki XPath'i (yoksa None). Sağlam kayıtlarda alternatifler
    ve metinle arama XPath birleşimiyle (|) yedek olarak eklenir — kayıttaki XPath o
    ekranda değişmişse eleman yine bulunur. Kırılgan (sıraya bağlı) kayıtta birleşim
    yapılmaz: belge sırasında önce gelen BAŞKA bir aynı yazılı eleman seçilebilirdi.
    Yazı alanında metin yedeği yok (etiket metni alanın kendisi değil)."""
    if not lookup or not target:
        return None
    el = lookup.get(norm_key(target))
    if not el or not el.get("xpath"):
        return None
    textless = bool(el.get("textless"))
    # Doğrulama yazının kendisini kontrol eder → sadece yazısız (ikon) kayıtta XPath'e geçilir
    if action in ("assert", "assert_not_visible") and not textless:
        return None
    xps = [el["xpath"]]
    if not el.get("fragile"):
        xps += [a for a in el.get("alternatives") or [] if a and not a.startswith("/hierarchy")]
        # "icon1" ekranda yazı olarak geçmez → metin yedeği anlamsız
        if text_fallback and action != "type" and not textless:
            xps.append(text_fallback)
    return " | ".join(dict.fromkeys(xps))


# ── ADO Excel dönüşümü ──────────────────────────────────────────────────────

_VERIFY_RE = re.compile(r"g[öo]r[üu]l[üu]r|g[öo]r[üu]lmez|do[gğ]rula|kontrol", re.IGNORECASE)


def to_passive(step: str) -> str:
    """Kayıt adımı (emir kipi) → test case dili (edilgen)."""
    s = (step or "").strip().rstrip(".").strip()
    if not s:
        return ""
    rules = [
        (r"^(.*\S)\s+t[ıi]kla$", r"\1 tıklanır"),
        (r"^(.*\S)\s+bas$", r"\1 basılır"),
        (r"^(.*\S)\s+yaz$", r"\1 yazılır"),
        (r"^(.*\S)\s+gir$", r"\1 girilir"),
        (r"^(.*?)\s*kayd[ıi]r$", r"\1 kaydırılır"),
        (r"^geri\s+d[öo]n$", "Geri dönülür"),
        (r"^(.*\S)\s+bekle$", r"\1 beklenir"),
        (r"^(.*\S)\s+a[çc]$", r"\1 açılır"),
    ]
    for pat, rep in rules:
        if re.match(pat, s, re.IGNORECASE):
            s = re.sub(pat, rep, s, flags=re.IGNORECASE).strip()
            break
    return s[0].upper() + s[1:] + "."


def steps_to_ado(steps: list[str]) -> list[dict]:
    """Aksiyon → satır; ardından gelen doğrulamalar o satırın Step Expected'ına."""
    rows: list[dict] = []
    for raw in steps:
        s = to_passive(raw)
        if not s:
            continue
        if _VERIFY_RE.search(s):
            if rows:
                exp = rows[-1]["step_expected"]
                rows[-1]["step_expected"] = (exp + "\n" + s) if exp else s
            else:
                rows.append({"step_action": "", "step_expected": s})
        else:
            rows.append({"step_action": s, "step_expected": ""})
    return rows
