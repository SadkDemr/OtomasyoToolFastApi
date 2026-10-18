"""
App Map Service — Uygulama haritası (ekran → aksiyon → ekran grafı)
-------------------------------------------------------------------
Ekran tanıma VERİDEN BAĞIMSIZ olacak şekilde tasarlandı:
- Ekran, "jeton" kümesiyle tanımlanır:
    id:<resource-id>  → Appium sayfa kaynağından (kullanıcıdan/veriden bağımsız, en güvenilir)
    tx:<etiket>       → sayfa kaynağı + OCR metinleri (rakamlar atılır: bakiye/tarih/IBAN)
- Her ekran ziyaret ettikçe hangi jetonun HER SEFERİNDE göründüğünü öğrenir:
  sabit etiketler ("Gönderen Hesap", "Tutar") kalır, kişiye özel veri (isim,
  alıcı listesi) zamanla elenir ve haritadan silinir (gizlilik).
- Karşılaştırma "ekranın sabit etiketlerinin ne kadarı şu an ekranda var?"
  sorusuna dayanır; fazladan veri (uzun listeler) eşleşmeyi bozmaz. Birçok
  ekranda ortak olan jetonlar (sekme çubuğu, başlık) düşük ağırlık alır.
- Kişiye özel bir yazıya yapılan dokunuşlar "veriye bağlı" işaretlenir.
- Ekran/geçişlerin görüldüğü uygulama sürümleri tutulur.
Veriler backend/app_maps/<uygulama>/ altında, .gitignore'da.
"""

import io
import json
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional

MAPS_DIR = Path(__file__).parent.parent / "app_maps"
MATCH_THRESHOLD = 0.55        # ekran eşleşme skoru eşiği
STATIC_RATIO = 0.6            # ziyaretlerin en az %60'ında görülen jeton = sabit etiket
PRUNE_AFTER_VISITS = 4        # bu kadar ziyaretten sonra nadir jetonlar silinir
PRUNE_RATIO = 0.25
STATUS_BAR_RATIO = 0.045      # üstteki saat/pil şeridi tanımaya katılmaz
_GENERIC_IDS = {"content", "statusbarbackground", "navigationbarbackground", "action_bar_root",
                "decor_content_parent", "parentpanel", "contentpanel", "custompanel", "toolbar"}

_LOCK = threading.Lock()
_OCR = None
_OCR_LOCK = threading.Lock()
_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


# ── Normalizasyon / jetonlar ────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Koşum helper'ındaki _vis_norm ile aynı kural (ç→q, ı→l OCR karışıklıkları dahil)."""
    s = str(s).translate(_TR_MAP).lower().replace("q", "c").replace("l", "i")
    return "".join(ch for ch in s if ch.isalnum())


def _hash_text(t: str) -> str:
    """Gizlilik: ekrandaki yazılar haritada DÜZ METİN olarak tutulmaz (müşteri adları vb.);
    eşleştirme sadece eşitlik gerektirdiğinden geri çevrilemeyen özet yeterlidir."""
    import hashlib
    return "tx#" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def _text_token(text: str) -> Optional[str]:
    t = re.sub(r"[0-9]", "", _norm(text))   # bakiye, tarih, kart no, IBAN → atılır
    return _hash_text(t) if len(t) >= 3 else None


OCR_MAX_W = 800


def _ocr_engine():
    global _OCR
    with _OCR_LOCK:
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
    return _OCR


def ocr_lines(png: bytes) -> tuple[list[dict], int, int]:
    """[{text, norm, box:[x1,y1,x2,y2] (0-1 oran), conf}] + görüntü boyutu."""
    from PIL import Image
    import numpy as np
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    # HIZ: telefon görüntüsü (1080+ px) OCR için küçültülür; kutular oran olduğu için etkilenmez
    if w > OCR_MAX_W:
        im = im.resize((OCR_MAX_W, max(1, int(h * OCR_MAX_W / w))))
    sw, sh = im.size
    res, _ = _ocr_engine()(np.asarray(im)[:, :, ::-1].copy(), use_cls=False)   # RapidOCR BGR bekler
    out = []
    for box, txt, conf in res or []:
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append({
            "text": txt, "norm": _norm(txt), "conf": float(conf),
            "box": [min(xs) / sw, min(ys) / sh, max(xs) / sw, max(ys) / sh],
        })
    out.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return out, w, h


def source_tokens(source_xml: Optional[str]) -> set[str]:
    """Appium sayfa kaynağından jetonlar: resource-id'ler (yapı) + görünen yazılar."""
    toks: set[str] = set()
    if not source_xml:
        return toks
    try:
        import xml.etree.ElementTree as ET
        # iPhone (XCUITest) kaynağı: koşum izi / toparlama da aynı jetonları üretsin
        from services.locator_service import normalize_ios_source
        root = ET.fromstring(normalize_ios_source(source_xml))
    except Exception:
        return toks
    for el in root.iter():
        rid = (el.get("resource-id") or "").split("/")[-1].strip()
        if rid and rid.lower() not in _GENERIC_IDS and not re.fullmatch(r"[0-9_\-]+", rid):
            toks.add("id:" + rid.lower())
        for attr in ("text", "content-desc"):
            tk = _text_token(el.get(attr) or "")
            if tk:
                toks.add(tk)
    return toks


def observation_tokens(lines: list[dict], source_xml: Optional[str] = None) -> set[str]:
    toks = source_tokens(source_xml)
    for l in lines:
        if l["box"][3] < STATUS_BAR_RATIO:
            continue
        tk = _text_token(l["text"])
        if tk:
            toks.add(tk)
    return toks


# ── Depolama ────────────────────────────────────────────────────────────────

def _app_dir(app: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", app or "bilinmeyen")
    d = MAPS_DIR / safe
    (d / "screens").mkdir(parents=True, exist_ok=True)
    return d


def _migrate(data: dict) -> dict:
    """v1 haritaları (signature + ham texts) yeni modele çevirir; ham yazılar silinir."""
    for s in data.get("screens", {}).values():
        if "token_counts" not in s:
            s["token_counts"] = {_hash_text(t): 1 for t in s.get("signature", [])}
            s["visits"] = max(1, s.get("seen_count", 1))
        # düz metin "tx:" jetonlarını özete çevir
        s["token_counts"] = {(_hash_text(t[3:]) if t.startswith("tx:") else t): c
                             for t, c in s["token_counts"].items()}
        s.pop("signature", None)
        s.pop("texts", None)        # gizlilik: ham OCR yazıları tutulmaz
        s.setdefault("versions", {})
        s.setdefault("ocr_name", s.get("name", "Ekran"))
    for t in data.get("transitions", []):
        t.setdefault("versions", {})
    data["schema"] = 3
    return data


def load_map(app: str) -> dict:
    p = _app_dir(app) / "map.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if data.get("schema") == 3 else _migrate(data)
        except Exception:
            pass
    return {"app": app, "schema": 3, "screens": {}, "transitions": []}


def _save_map(app: str, data: dict) -> None:
    p = _app_dir(app) / "map.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def list_apps() -> list[dict]:
    if not MAPS_DIR.exists():
        return []
    out = []
    for d in sorted(MAPS_DIR.iterdir()):
        mp = d / "map.json"
        if mp.exists():
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
                out.append({"app": m.get("app", d.name), "screens": len(m.get("screens", {})),
                            "transitions": len(m.get("transitions", []))})
            except Exception:
                continue
    return out


def screen_thumb_path(app: str, screen_id: str) -> Optional[Path]:
    p = _app_dir(app) / "screens" / f"{re.sub(r'[^a-f0-9]', '', screen_id)}.jpg"
    return p if p.exists() else None


def _save_thumb(app: str, screen_id: str, png: bytes, lines: list[dict], static: Optional[set] = None) -> str:
    """Küçük görüntü. Gizlilik: rakam içeren satırlar (bakiye, IBAN, kart no) her zaman,
    sabit etiketler biliniyorsa onlar DIŞINDAKİ tüm yazılar (isimler, listeler) bulanıklaştırılır."""
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = im.size
    for l in lines:
        if l["box"][3] < STATUS_BAR_RATIO:
            continue
        tk = _text_token(l["text"])
        hide = bool(re.search(r"[0-9]", l["text"])) or (static is not None and tk not in static)
        if hide:
            x1, y1, x2, y2 = (int(l["box"][0] * W) - 4, int(l["box"][1] * H) - 4,
                              int(l["box"][2] * W) + 4, int(l["box"][3] * H) + 4)
            x1, y1 = max(0, x1), max(0, y1)
            if x2 > x1 and y2 > y1:
                im.paste(im.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(12)), (x1, y1))
    im.thumbnail((360, 800))
    rel = f"screens/{screen_id}.jpg"
    im.save(_app_dir(app) / rel, "JPEG", quality=70)
    return rel


# ── Eşleştirme ──────────────────────────────────────────────────────────────

def static_tokens(screen: dict) -> set[str]:
    """Ekranın sabit etiketleri: ziyaretlerin en az yarısında görülen jetonlar
    (tek ziyarette henüz ayırt edilemez → hepsi)."""
    counts, visits = screen.get("token_counts", {}), max(1, screen.get("visits", 1))
    if visits < 2:
        return set(counts)
    return {t for t, c in counts.items() if c / visits >= STATIC_RATIO}


def _weights(data: dict) -> dict[str, float]:
    """Jeton ağırlığı = 1 / (kaç ekranın sabit etiketi olduğu). Sekme çubuğu gibi
    her ekranda olan yazılar ekranı ayırt etmez → düşük ağırlık."""
    df: dict[str, int] = {}
    for s in data["screens"].values():
        for t in static_tokens(s):
            df[t] = df.get(t, 0) + 1
    return {t: 1.0 / n for t, n in df.items()}


def _score(screen: dict, obs: set[str], w: dict[str, float]) -> float:
    L = static_tokens(screen)
    if not L or not obs:
        return 0.0
    common = L & obs
    wl = sum(w.get(t, 1.0) for t in L)
    c1 = sum(w.get(t, 1.0) for t in common) / wl if wl else 0.0   # ekran etiketlerinin ne kadarı var
    c2 = len(common) / len(obs)                                    # gözlemin ne kadarı bu ekrana ait
    # resource-id'ler veriden bağımsız → ortak id'ler varsa güven artar
    ids_l = {t for t in L if t.startswith("id:")}
    if len(ids_l) >= 3:
        id_c = len(ids_l & obs) / len(ids_l)
        c1 = max(c1, 0.5 * c1 + 0.5 * id_c)
    return c1 * (0.5 + 0.5 * c2)


def match_screen(data: dict, obs: set[str]) -> tuple[Optional[str], float]:
    w = _weights(data)
    best_id, best = None, 0.0
    for sid, s in data["screens"].items():
        sc = _score(s, obs, w)
        if sc > best:
            best_id, best = sid, sc
    return (best_id, best) if best >= MATCH_THRESHOLD else (None, best)


def _learn(screen: dict, obs: set[str]) -> None:
    counts = screen.setdefault("token_counts", {})
    for t in obs:
        counts[t] = counts.get(t, 0) + 1
    screen["visits"] = screen.get("visits", 0) + 1
    if screen["visits"] >= PRUNE_AFTER_VISITS:   # kişiye özel/nadir yazılar haritadan silinir
        v = screen["visits"]
        screen["token_counts"] = {t: c for t, c in counts.items() if c / v >= PRUNE_RATIO}


def _auto_name(lines: list[dict]) -> str:
    """Ekranın üst-orta kısmındaki en büyük yazı (rakam içermeyen). Geçici addır:
    ekrana bir dokunuşla gelinirse add_transition onu dokunulan hedefin adıyla değiştirir."""
    top = [l for l in lines if 0.12 <= l["box"][1] <= 0.6 and len(l["norm"]) >= 4
           and not re.search(r"[0-9]", l["text"])]
    if not top:
        return "Ekran"
    best = max(top, key=lambda l: (l["box"][3] - l["box"][1]))
    return re.sub(r"^\W+|\W+$", "", best["text"].strip())[:60] or "Ekran"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def register_screen(app: str, png: bytes, lines: list[dict], user: str, source: str,
                    source_xml: Optional[str] = None, version: str = "") -> tuple[str, bool, str]:
    """Ekranı haritada bul ya da yeni ekle. Döner: (screen_id, yeni_mi, ad)."""
    obs = observation_tokens(lines, source_xml)
    with _LOCK:
        data = load_map(app)
        sid, _ = match_screen(data, obs)
        if sid:
            s = data["screens"][sid]
            _learn(s, obs)
            s["last_seen"] = _now()
            s["seen_count"] = s.get("seen_count", 0) + 1
            if version:
                s.setdefault("versions", {})[version] = _now()
            # 3. ziyarette sabit etiketler belli → küçük görüntü kişiye özel yazılar gizlenerek
            # yenilenir, eski geçiş/işlemlerdeki kişiye özel hedefler temizlenir
            if s["visits"] == 3:
                try:
                    _save_thumb(app, sid, png, lines, static_tokens(s))
                except Exception:
                    pass
                _scrub_screen(data, sid)
            _save_map(app, data)
            return sid, False, s.get("name", "")
        sid = uuid.uuid4().hex[:12]
        name = _auto_name(lines)
        s = {"name": name, "name_source": "ocr", "ocr_name": name, "token_counts": {}, "visits": 0,
             "has_structure": any(t.startswith("id:") for t in obs),
             "first_seen": _now(), "last_seen": _now(), "seen_count": 1,
             "added_by": user, "source": source, "versions": {version: _now()} if version else {}}
        _learn(s, obs)
        s["thumb"] = _save_thumb(app, sid, png, lines)
        data["screens"][sid] = s
        _save_map(app, data)
        return sid, True, name


def _merge_into(data: dict, keep: str, drop: str) -> None:
    """drop ekranını keep'e katar (kilit içinde çağrılır): jeton sayaçları ve ziyaretler
    toplanır — iki farklı kullanıcının ortak gördüğü yazılar sabit etiket olarak kalır,
    kişiye özel olanlar oransal olarak düşer. Geçişler keep'e yönlendirilir."""
    k, d = data["screens"][keep], data["screens"].pop(drop)
    kc = k.setdefault("token_counts", {})
    for t, c in d.get("token_counts", {}).items():
        kc[t] = kc.get(t, 0) + c
    k["visits"] = k.get("visits", 1) + d.get("visits", 1)
    k["seen_count"] = k.get("seen_count", 1) + d.get("seen_count", 1)
    k["has_structure"] = k.get("has_structure") or d.get("has_structure")
    k.setdefault("versions", {}).update(d.get("versions", {}))
    if k.get("name_source") == "ocr" and d.get("name_source") in ("action", "user"):
        k["name"], k["name_source"] = d["name"], d["name_source"]
    for t in data["transitions"]:
        if t["from"] == drop: t["from"] = keep
        if t["to"] == drop:   t["to"] = keep
    # yönlendirme sonrası oluşan kopya geçişleri birleştir, kendine dönen geçişleri at
    seen: dict = {}
    merged = []
    for t in data["transitions"]:
        if t["from"] == t["to"]:
            continue
        key = (t["from"], t["to"], t["action"].get("type"), _norm(t["action"].get("target") or ""))
        if key in seen:
            seen[key]["count"] = seen[key].get("count", 1) + t.get("count", 1)
            seen[key].setdefault("versions", {}).update(t.get("versions", {}))
            continue
        seen[key] = t
        merged.append(t)
    data["transitions"] = merged
    try:
        p = _app_dir(data["app"]) / "screens" / f"{drop}.jpg"
        if p.exists():
            p.unlink()
    except Exception:
        pass


def merge_screens(app: str, keep: str, drop: str) -> bool:
    if keep == drop:
        return False
    with _LOCK:
        data = load_map(app)
        if keep not in data["screens"] or drop not in data["screens"]:
            return False
        _merge_into(data, keep, drop)
        _save_map(app, data)
        return True


def is_dynamic_target(screen: dict, target: str) -> bool:
    """Dokunulan yazı ekranın sabit etiketi değilse (isim, alıcı, kart adı) ya da rakam
    içeriyorsa → veriye bağlı. Ekran en az 2 kez görülmeden karar verilemez (False)."""
    if not target:
        return False
    if re.search(r"[0-9]", target):
        return True
    if screen.get("visits", 1) < 2:
        return False
    tk = _text_token(target)
    return bool(tk) and tk not in static_tokens(screen)


_DYNAMIC_LABEL = "(kişiye özel bir öğeye dokunuldu — isim/kart/alıcı)"


def _mask_action(action: dict) -> None:
    """Gizlilik: kişiye özel hedefin adı (isim, kart, alıcı) haritada tutulmaz."""
    action["target"] = ""
    action["label"] = _DYNAMIC_LABEL
    action["dynamic"] = True
    action.pop("point", None)


def _scrub_screen(data: dict, sid: str) -> None:
    """Ekranın sabit/değişken ayrımı netleşince (3. ziyaret) o ekrandan çıkan
    geçişlerde ve ekran işlemlerinde kalmış kişiye özel hedefleri geriye dönük temizle."""
    s = data["screens"].get(sid)
    if not s:
        return
    for t in data.get("transitions", []):
        a = t.get("action", {})
        if t["from"] == sid and a.get("target") and is_dynamic_target(s, a["target"]):
            old = a["target"]
            _mask_action(a)
            # Hedef ekran bu kişiye özel dokunuşun adını almışsa ("Ahmet Yılmaz") geri al
            to_s = data["screens"].get(t["to"])
            if to_s and to_s.get("name_source") == "action" and _norm(to_s.get("name", "")) == _norm(old):
                to_s["name"] = to_s.get("ocr_name") or "Ekran"
                to_s["name_source"] = "ocr"
    acts = s.get("actions", {})
    for k in list(acts):
        a = acts[k]
        if a.get("target") and is_dynamic_target(s, a["target"]):
            a["target"], a["dynamic"] = "", True
            nk = a["type"] + ":kisiyeozel"
            if nk in acts and nk != k:
                acts[nk]["count"] = acts[nk].get("count", 1) + a.get("count", 1)
                acts.pop(k)
            else:
                acts[nk] = acts.pop(k)


def add_transition(app: str, from_id: str, to_id: str, action: dict, user: str, source: str,
                   version: str = "") -> tuple[bool, str]:
    """Geçiş ekle; aynı (from, aksiyon hedefi, to) varsa sayacını artır.
    Döner: (yeni_mi, hedef_ekran_id) — hedef ekran otomatik birleştirildiyse id değişir."""
    with _LOCK:
        data = load_map(app)
        from_s = data["screens"].get(from_id, {})
        action = dict(action)
        action["dynamic"] = is_dynamic_target(from_s, action.get("target") or "")
        if action["dynamic"]:
            _mask_action(action)
        key = (action.get("type"), _norm(action.get("target") or ""))
        # Aynı ekrandan aynı (veriye bağlı OLMAYAN) dokunuş başka bir ekrana gidiyorsa,
        # iki "farklı" ekran aslında aynıdır — farklı kullanıcının verisi yüzünden
        # yazıları tutmamıştır. Veriden bağımsız bu sinyalle birleştirilir.
        if not action["dynamic"] and action.get("target") and action.get("type") != "back":
            for t in data["transitions"]:
                a = t["action"]
                if (t["from"] == from_id and t["to"] != to_id and t["to"] in data["screens"]
                        and to_id in data["screens"] and not a.get("dynamic")
                        and (a.get("type"), _norm(a.get("target") or "")) == key):
                    _merge_into(data, t["to"], to_id)
                    to_id = t["to"]
                    break
        for t in data["transitions"]:
            a = t["action"]
            if t["from"] == from_id and t["to"] == to_id and (a.get("type"), _norm(a.get("target") or "")) == key:
                t["count"] = t.get("count", 1) + 1
                t["last_seen"] = _now()
                a["dynamic"] = action["dynamic"]
                if version:
                    t.setdefault("versions", {})[version] = _now()
                _save_map(app, data)
                return False, to_id
        data["transitions"].append({
            "id": uuid.uuid4().hex[:12], "from": from_id, "to": to_id, "action": action,
            "count": 1, "first_seen": _now(), "last_seen": _now(),
            "added_by": user, "source": source, "versions": {version: _now()} if version else {},
        })
        # "Ayarlar"a dokununca açılan ekranın en anlamlı adı "Ayarlar"dır — sadece
        # OCR'dan tahmin edilmiş adı bir kez değiştirir, elle verilen ada ve
        # kişiye özel hedeflere ("Ahmet Yılmaz") dokunmaz
        to_s = data["screens"].get(to_id)
        if (to_s and to_s.get("name_source") == "ocr" and action.get("type") == "tap"
                and action.get("target") and not action["dynamic"]):
            to_s["name"] = action["target"].strip()[:60]
            to_s["name_source"] = "action"
        _save_map(app, data)
        return True, to_id


def add_screen_action(app: str, screen_id: str, action: dict, user: str, source: str) -> bool:
    """Ekranı DEĞİŞTİRMEYEN işlem (alana yazı, toggle, aynı ekranda kalan dokunuş)
    ekranın işlem listesine eklenir. Gizlilik: yazılan DEĞER hiç saklanmaz, sadece
    alan adı; kişiye özel hedefler (isim/kart) adı tutulmadan genel kaydedilir.
    Döner: yeni_mi."""
    typ = action.get("type") or "tap"
    if typ == "back":
        return False
    with _LOCK:
        data = load_map(app)
        s = data["screens"].get(screen_id)
        if not s:
            return False
        target = (action.get("target") or "").strip()
        # Yazı alanı adları ipucu (hint) olarak görünüp yazınca kaybolabilir → sabit etiket
        # kontrolü onlar için anlamsız; sadece rakam içeren adlar (kişiye özel) maskelenir
        if typ == "input":
            dynamic = bool(re.search(r"[0-9]", target))
        else:
            dynamic = is_dynamic_target(s, target)
        if dynamic:
            target = ""
        key = typ + ":" + (_norm(target) if target else ("kisiyeozel" if dynamic else ""))
        acts = s.setdefault("actions", {})
        a = acts.get(key)
        if a:
            a["count"] = a.get("count", 1) + 1
            a["last_seen"] = _now()
            _save_map(app, data)
            return False
        acts[key] = {"type": typ, "target": target[:80], "dynamic": dynamic, "count": 1,
                     "first_seen": _now(), "last_seen": _now(), "added_by": user, "source": source}
        _save_map(app, data)
        return True


def rename_screen(app: str, screen_id: str, name: str) -> bool:
    with _LOCK:
        data = load_map(app)
        if screen_id not in data["screens"]:
            return False
        data["screens"][screen_id]["name"] = name.strip()[:80]
        data["screens"][screen_id]["name_source"] = "user"
        _save_map(app, data)
        return True


def delete_screen(app: str, screen_id: str) -> bool:
    """Ekranı, görüntüsünü ve ona giren/çıkan tüm geçişleri siler."""
    with _LOCK:
        data = load_map(app)
        if screen_id not in data["screens"]:
            return False
        data["screens"].pop(screen_id)
        data["transitions"] = [t for t in data["transitions"]
                               if t["from"] != screen_id and t["to"] != screen_id]
        _save_map(app, data)
    p = screen_thumb_path(app, screen_id)
    if p:
        try:
            p.unlink()
        except Exception:
            pass
    return True


def delete_transition(app: str, transition_id: str) -> bool:
    with _LOCK:
        data = load_map(app)
        before = len(data["transitions"])
        data["transitions"] = [t for t in data["transitions"] if t["id"] != transition_id]
        if len(data["transitions"]) == before:
            return False
        _save_map(app, data)
        return True


def public_screen(s: dict) -> dict:
    """API'ye giden ekran özeti — jeton sayaçları yerine sadece özet bilgi."""
    st = static_tokens(s)
    return {k: v for k, v in s.items() if k not in ("token_counts",)} | {
        "static_labels": len([t for t in st if t.startswith("tx#")]),
        "structure_ids": len([t for t in st if t.startswith("id:")]),
    }


def find_path(app: str, from_id: str, to_id: str) -> Optional[list[dict]]:
    """En kısa geçiş yolu (BFS). Veriye bağlı geçişler (kişiye özel dokunuşlar) ancak
    başka yol yoksa kullanılır. Döner: geçiş listesi ya da None."""
    return find_path_in(load_map(app), from_id, to_id)


def expected_screens(data: dict, target: str) -> set[str]:
    """Bir adımın hedefi (örn. "Ayarlar") hangi ekranlarda bulunur? Koşumda kendini
    toparlama için: o hedefe dokunulan geçişlerin kaynak ekranları + hedefi sabit
    etiketi olan ekranlar."""
    if not target:
        return set()
    out = set()
    nt, tk = _norm(target), _text_token(target)
    for t in data.get("transitions", []):
        a = t.get("action", {})
        if _norm(a.get("target") or "") == nt and t["from"] in data["screens"]:
            out.add(t["from"])
    if tk:
        for sid, s in data["screens"].items():
            if tk in static_tokens(s):
                out.add(sid)
    return out


def find_path_in(data: dict, from_id: str, to_id: str) -> Optional[list[dict]]:
    if from_id == to_id:
        return []

    def _bfs(allow_dynamic: bool):
        adj: dict[str, list[dict]] = {}
        for t in data["transitions"]:
            if not allow_dynamic and t["action"].get("dynamic"):
                continue
            adj.setdefault(t["from"], []).append(t)
        prev: dict[str, dict] = {}
        q = deque([from_id]); seen = {from_id}
        while q:
            cur = q.popleft()
            for t in sorted(adj.get(cur, []), key=lambda t: -t.get("count", 1)):
                nxt = t["to"]
                if nxt in seen:
                    continue
                seen.add(nxt); prev[nxt] = t
                if nxt == to_id:
                    path = []
                    while nxt != from_id:
                        path.append(prev[nxt]); nxt = prev[nxt]["from"]
                    return list(reversed(path))
                q.append(nxt)
        return None

    return _bfs(False) or _bfs(True)


# ── Adım metninden aksiyon çıkarma (koşum izleri için) ─────────────────────

def action_from_step(label: str) -> dict:
    """'"Takım" butonuna tıkla' → {type: tap, target: Takım, label: ...}"""
    q = re.findall(r'["“”]([^"“”]+)["“”]', label or "")
    low = (label or "").lower()
    typ = "tap"
    if re.search(r"\b(yaz|gir|doldur)", low):
        typ = "input"
    elif re.search(r"geri\s*(d[öo]n|git|tu[şs])|back\b", low):
        typ = "back"
    return {"type": typ, "target": q[0] if q else "", "label": label or ""}


# ── Koşum izini işle (koşum bittikten sonra, arka planda) ──────────────────

def process_run_trace(trace_dir: str, step_labels: list[str], step_outcomes: dict, user: str) -> dict:
    """Koşum scriptinin yazdığı izi (snap_*.png [+ snap_*.xml] + events.jsonl + meta.json)
    haritaya işler. Sadece BAŞARILI adımların geçişleri eklenir; ekran değişmeyen
    adımlar (doğrulama, bekleme) geçiş üretmez. Döner: özet sayılar."""
    d = Path(trace_dir)
    summary = {"screens_new": 0, "transitions_new": 0, "steps": 0}
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        app, version = meta.get("app") or "", meta.get("version") or ""
        if not app:
            return summary
        events = [json.loads(l) for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        # shot k: "after_step" = bu görüntüden ÖNCE biten adım (-1 = ilk ekran)
        shots = []
        for ev in events:
            png = (d / ev["file"]).read_bytes()
            xml_p = d / ev["file"].replace(".png", ".xml")
            src = xml_p.read_text(encoding="utf-8", errors="replace") if xml_p.exists() else None
            lines, _, _ = ocr_lines(png)
            sid, is_new, _ = register_screen(app, png, lines, user, "run", src, version)
            summary["screens_new"] += int(is_new)
            shots.append((ev["after_step"], sid))
        for k in range(1, len(shots)):
            from_id, (after_idx, to_id) = shots[k - 1][1], shots[k]
            if after_idx < 0 or step_outcomes.get(after_idx) != "pass":
                continue
            summary["steps"] += 1
            label = step_labels[after_idx] if after_idx < len(step_labels) else ""
            if from_id == to_id:
                # Ekran değişmedi → ekran içi işlem (alana yazı, toggle, doğrulama hariç)
                act = action_from_step(label)
                if act["target"] and not re.search(r"g[öo]r[üu]l[üu]r|kontrol|do[ğg]rula|bekle", label.lower()):
                    summary["actions_new"] = summary.get("actions_new", 0) + int(
                        add_screen_action(app, from_id, act, user, "run"))
                continue
            is_new, eff = add_transition(app, from_id, to_id, action_from_step(label), user, "run", version)
            summary["transitions_new"] += int(is_new)
            if eff != to_id:   # ekran birleştirildi → sonraki adımlar da yeni id'yi kullansın
                summary["screens_merged"] = summary.get("screens_merged", 0) + 1
                shots = [(a, eff if s == to_id else s) for a, s in shots]
    finally:
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    return summary
