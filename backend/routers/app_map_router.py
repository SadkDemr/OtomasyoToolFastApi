"""
App Map Router — uygulama haritası görüntüleme + tarayıcıdan KAYIT MODU
-----------------------------------------------------------------------
Kayıt modu, AI Test Generator'daki kalıcı mobil oturumu (/api/ai-gen/session/start)
kullanır: backend açık Appium oturumuna doğrudan W3C HTTP ile bağlanır (her
dokunuşta yeni script başlatılmaz). Kullanıcı tarayıcıdaki ekran görüntüsüne
tıklar → o noktaya dokunulur → geçiş haritaya ve senaryo adımı olarak kaydedilir.
"""

import base64
import re
import io
import threading
import time
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from sqlalchemy.orm import Session

from database import get_db
from models.db_models import User
from routers.auth import get_current_user
from services import app_map_service as amap
from services import locator_service as locs

router = APIRouter(prefix="/api/app-map", tags=["App Map"])

# user_id → son kayıt modu durumu {app, screen_id, lines, img_w, img_h, steps:[...]}
_record_state: dict[int, dict] = {}

_ARROW_STEPS = {  # Evren sınıfı (normalize) → kural motorunun tanıdığı adım metni
    amap._norm("sol ok"):    '"<" iconuna tıkla',
    amap._norm("sağ ok"):    '">" iconuna tıkla',
    amap._norm("aşağı ok"):  "Aşağı oka tıkla",
    amap._norm("yukarı ok"): "Yukarı oka tıkla",
}


# ── Appium (W3C) yardımcıları ───────────────────────────────────────────────

def _session(user: User) -> dict:
    from routers.ai_test_generator_router import _get_session, _touch_session
    sess = _get_session(user.id, "mobile")
    if not sess:
        raise HTTPException(409, "Önce AI Test Generator'da mobil oturumu başlatın.")
    _touch_session(user.id, "mobile")
    return sess


def _is_ios(sess: Optional[dict] = None, dev: str = "") -> bool:
    """iPhone mu? (oturum kaydı ya da telefonun bulunduğu cihaz sunucusu)."""
    if sess and sess.get("device_os"):
        return sess["device_os"] == "ios"
    dev = dev or (sess or {}).get("device_id") or ""
    if not dev:
        return False
    from services import device_node_service as dnodes
    return dnodes.platform_for(dev) == "ios"


# Aynı oturuma AYNI ANDA iki komut gitmez: eşzamanlı sayfa kaynağı + dokunuş/ekran
# görüntüsü UiAutomator2 instrumentation sürecini çökertebiliyor ("instrumentation
# process is not running"). Kilit, başka bir iş parçacığından da bırakılabilsin diye Lock.
_sess_locks: dict[str, threading.Lock] = {}


def _lock(sess: dict) -> threading.Lock:
    return _sess_locks.setdefault(sess["session_id"], threading.Lock())


def _wd(sess: dict, method: str, path: str, json_body: Optional[dict] = None, timeout: float = 20,
        locked: bool = False):
    """locked=True → çağıran kilidi zaten tutuyor."""
    url = f"{sess['command_executor_url'].rstrip('/')}/session/{sess['session_id']}{path}"
    lk = _lock(sess)
    if not locked and not lk.acquire(timeout=timeout + 15):
        raise HTTPException(503, "Telefon meşgul (önceki komut bitmedi), tekrar deneyin")
    try:
        r = requests.request(method, url, json=json_body, timeout=timeout)
    finally:
        if not locked:
            lk.release()
    if not r.ok:
        if "instrumentation process is not running" in r.text:
            raise HTTPException(410, "Telefondaki UiAutomator2 çöktü — oturumu bitirip yeniden başlatın.")
        raise HTTPException(502, f"Appium hatası ({r.status_code}): {r.text[:200]}")
    return r.json().get("value")


def _screenshot(sess: dict) -> bytes:
    return base64.b64decode(_wd(sess, "GET", "/screenshot"))


def _tap(sess: dict, x: int, y: int, locked: bool = False) -> None:
    _wd(sess, "POST", "/actions", {"actions": [{
        "type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"},
        "actions": [
            {"type": "pointerMove", "duration": 0, "x": x, "y": y},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": 80},
            {"type": "pointerUp", "button": 0},
        ],
    }]}, locked=locked)


def _swipe(sess: dict, x1: int, y1: int, x2: int, y2: int, ms: int = 350, locked: bool = False) -> None:
    _wd(sess, "POST", "/actions", {"actions": [{
        "type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"},
        "actions": [
            {"type": "pointerMove", "duration": 0, "x": x1, "y": y1},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": ms, "x": x2, "y": y2},
            {"type": "pause", "duration": 60},   # bırakmadan önce dur → savrulma (fling) olmasın
            {"type": "pointerUp", "button": 0},
        ],
    }]}, locked=locked)


# HIZ: UiAutomator2 her komuttan önce uygulamanın "boşta" olmasını bekler (varsayılan
# 10 sn). Animasyonlu/yükleme göstergeli ekranlarda her dokunuş, ekran görüntüsü ve
# sayfa kaynağı bu süreye takılır. Kayıt modunda kapatılır, çıkışta geri alınır.
_fast_sessions: set[str] = set()


def _fast_mode(sess: dict, on: bool = True) -> None:
    sid = sess["session_id"]
    if on == (sid in _fast_sessions):
        return
    # Birim farkı: UiAutomator2 milisaniye (varsayılan 10000), XCUITest saniye (varsayılan 10)
    off_value = 10 if _is_ios(sess) else 10000
    try:
        _wd(sess, "POST", "/appium/settings",
            {"settings": {"waitForIdleTimeout": 0 if on else off_value}}, timeout=5)
    except Exception:
        pass
    (_fast_sessions.add if on else _fast_sessions.discard)(sid)


_rect_cache: dict[str, dict] = {}


def _rect(sess: dict) -> dict:
    sid_key = sess["session_id"]
    if sid_key not in _rect_cache:
        _rect_cache[sid_key] = _wd(sess, "GET", "/window/rect")
    return _rect_cache[sid_key]


_version_cache: dict[tuple[str, str], str] = {}


def _app_version(sess: dict) -> str:
    """Uygulama sürümü (adb dumpsys) — oturum başına bir kez okunur."""
    dev, app = sess.get("device_id") or "", sess.get("app_package") or ""
    if not app or _is_ios(sess):   # iPhone'da adb yok — sürüm bilinmez
        return ""
    key = (dev, app)
    if key not in _version_cache:
        ver = ""
        try:
            import subprocess
            from services import device_node_service as dnodes
            cmd = dnodes.adb_cmd(dev, "shell", "dumpsys", "package", app)
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
            for ln in out.splitlines():
                if "versionName=" in ln:
                    ver = ln.split("versionName=", 1)[1].strip()
                    break
        except Exception:
            pass
        _version_cache[key] = ver
    return _version_cache[key]


# ── Kayıt modu iş mantığı ───────────────────────────────────────────────────
# HIZ: ekran görüntüsü tarayıcıya HEMEN döner; sayfa kaynağı + OCR + haritaya kayıt
# arka planda yapılır (kullanıcı ekrana bakarken biter). Bir sonraki dokunuş
# yalnızca gerekirse önceki analizin bitmesini bekler. Geçiş, iki ekranın analizi
# de bitince kaydedilir.
from concurrent.futures import ThreadPoolExecutor

_analysis_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="appmap")


def _ocr_warmup():
    """Sunucu açılırken OCR modelini yükle — ilk kayıt modu açılışı beklemesin."""
    try:
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (64, 32), "white").save(b, "PNG")
        amap._ocr_engine()(b.getvalue(), use_cls=False)
    except Exception:
        pass


threading.Thread(target=_ocr_warmup, daemon=True).start()


_adb_err: dict[str, str] = {}   # cihaz → son adb hatası (ekranda gösterilir)


def _adb_screencap(dev: str):
    """HIZ: ham (sıkıştırılmamış) ekran görüntüsü — telefon PNG sıkıştırması yapmaz.
    Ham format tanınmazsa `screencap -p` (PNG) denenir. Olmazsa None; neden _adb_err'de."""
    import struct, subprocess
    from PIL import Image
    from services import device_node_service as dnodes
    if _is_ios(dev=dev):
        return None              # iPhone: ekran görüntüsü Appium'dan (adb yok)
    base = dnodes.adb_cmd(dev)   # uzak telefonda ilgili cihaz sunucusunun adb'sine gider
    # Uzak telefonda ham görüntü (~10 MB/kare) ağı tıkar → doğrudan PNG (~1-2 MB)
    remote = dnodes.is_remote(dev)
    try:
        r = subprocess.run(base + ["exec-out", "screencap"] + (["-p"] if remote else []),
                           capture_output=True, timeout=10)
        out = r.stdout
        if remote and out[:4] == b"\x89PNG":
            _adb_err.pop(dev, None)
            return Image.open(io.BytesIO(out)).convert("RGB")
        if len(out) >= 16:
            w, h, fmt = struct.unpack_from("<III", out, 0)
            n = w * h * 4
            hdr = len(out) - n
            # 1 = RGBA_8888, 2 = RGBX_8888, 5 = BGRA_8888 (üretici/sürüme göre değişiyor)
            if hdr in (12, 16) and 100 < w < 5000 and 100 < h < 5000 and fmt in (1, 2, 5):
                raw = out[hdr:hdr + n]
                im = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA" if fmt == 5 else "RGBA", 0, 1)
                _adb_err.pop(dev, None)
                return im.convert("RGB")
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        if err:   # cihaz yok / yetkisiz / çok cihaz → PNG denemenin anlamı yok
            _adb_err[dev] = err.splitlines()[-1][:200]
            return None
        r = subprocess.run(base + ["exec-out", "screencap", "-p"], capture_output=True, timeout=10)
        if r.stdout[:4] == b"\x89PNG":
            _adb_err.pop(dev, None)
            return Image.open(io.BytesIO(r.stdout)).convert("RGB")
        _adb_err[dev] = ((r.stderr or b"").decode("utf-8", "replace").strip()
                         or f"tanınmayan görüntü biçimi ({len(out)} bayt)")[:200]
    except Exception as e:
        _adb_err[dev] = str(e)[:200]
    return None


class _MjpegStream:
    """UiAutomator2'nin dahili MJPEG sunucusundan (oturum açılırken mjpegServerPort ile
    bilgisayara yönlendirilir) sürekli kare okur; en son kare bellekte tutulur.
    Canlı ekran ve kayıt modu ekran görüntüleri buradan ANINDA alınır (cihazda
    screenshot/PNG kodlama beklenmez). 60 sn kullanılmazsa kendiliğinden kapanır."""

    def __init__(self, port: int):
        self.port, self.frame, self.ts = port, None, 0.0
        self.cond = threading.Condition()
        self.last_use = time.time()
        self.alive = True
        threading.Thread(target=self._run, daemon=True, name=f"mjpeg-{port}").start()

    def _run(self):
        while self.alive and time.time() - self.last_use < 60:
            try:
                # Ham soket: recv veri geldiği anda döner (requests/urllib3 tamponu kareleri biriktiriyor)
                import socket as _sock
                sk = _sock.create_connection(("127.0.0.1", self.port), timeout=10)
                sk.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n")
                buf = b""
                while self.alive and time.time() - self.last_use < 60:
                    chunk = sk.recv(262144)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        a = buf.find(b"\xff\xd8")
                        if a < 0:
                            buf = buf[-1:]
                            break
                        b = buf.find(b"\xff\xd9", a + 2)
                        if b < 0:
                            buf = buf[a:]
                            break
                        with self.cond:
                            self.frame, self.ts = buf[a:b + 2], time.time()
                            self.cond.notify_all()
                        buf = buf[b + 2:]
                sk.close()
            except Exception:
                time.sleep(1)
        self.alive = False

    def latest(self, after: float = 0.0, timeout: float = 1.5):
        """after'dan SONRA gelmiş ilk kare (jpeg bytes, zaman) — yoksa None."""
        self.last_use = time.time()
        end = time.time() + timeout
        with self.cond:
            while self.ts <= after or self.frame is None:
                left = end - time.time()
                if left <= 0 or not self.alive:
                    return None
                self.cond.wait(left)
            return self.frame, self.ts


_streams: dict[str, _MjpegStream] = {}


def _stream(sess: Optional[dict]) -> Optional[_MjpegStream]:
    if not sess or not sess.get("mjpeg_port"):
        return None
    sid = sess["session_id"]
    st = _streams.get(sid)
    if st is None or not st.alive:
        try:   # OCR için yeterli çözünürlük (varsayılan %50 küçük kalıyor), 10 kare/sn
            _wd(sess, "POST", "/appium/settings", {"settings": {
                "mjpegScalingFactor": 75, "mjpegServerFramerate": 10,
                "mjpegServerScreenshotQuality": 60}}, timeout=5)
        except Exception:
            pass
        st = _streams[sid] = _MjpegStream(int(sess["mjpeg_port"]))
    return st


def _sig(im) -> bytes:
    """Ekran değişti mi karşılaştırması için minik gri imza."""
    return im.convert("L").resize((36, 80)).tobytes()


def _sig_diff(a: Optional[bytes], b: Optional[bytes]) -> float:
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _grab(sess: dict, after: float = 0.0):
    """(PIL görüntü, kaynak adı). Akış → adb ham → Appium sırasıyla."""
    from PIL import Image
    ms = _stream(sess)
    if ms:
        got = ms.latest(after, timeout=1.5)
        if got:
            return Image.open(io.BytesIO(got[0])).convert("RGB"), "akış"
    im = _adb_screencap(sess.get("device_id") or "")
    if im is not None:
        return im, "adb"
    return Image.open(io.BytesIO(_screenshot(sess))).convert("RGB"), "appium"


def _settle(sess: dict, before_sig: Optional[bytes], t_act: float):
    """Dokunuş sonrası ekran DURULUNCA kareyi al. Akış varsa sabit bekleme yerine: art
    arda iki kare aynıysa (ve ekran değiştiyse ya da 0.8 sn geçtiyse) hemen döner."""
    ms = _stream(sess)
    if not ms:
        time.sleep(0.45)
        return _grab(sess)
    from PIL import Image
    time.sleep(0.2)
    last_sig, last_im, after = None, None, time.time()
    while True:
        got = ms.latest(after, timeout=1.0)
        if not got:
            break
        after = got[1]
        im = Image.open(io.BytesIO(got[0])).convert("RGB")
        sg = _sig(im)
        el = time.time() - t_act
        stable = last_sig is not None and _sig_diff(sg, last_sig) < 1.5
        changed = _sig_diff(sg, before_sig) > 3
        last_sig, last_im = sg, im
        if (stable and (changed or el >= 0.8)) or el >= 2.0:
            return im, "akış"
    return (last_im, "akış") if last_im is not None else _grab(sess)


def _adb_input(sess: dict, *args) -> bool:
    import subprocess
    from services import device_node_service as dnodes
    dev = sess.get("device_id") or ""
    if _is_ios(sess):
        return False             # iPhone: dokunuş her zaman Appium'dan
    try:
        r = subprocess.run(dnodes.adb_cmd(dev, "shell", "input", *map(str, args)),
                           capture_output=True, timeout=6)
        return r.returncode == 0
    except Exception:
        return False


def _act(sess: dict, kind: str, *a) -> None:
    """Dokunuş/kaydırma/geri. Telefon boştaysa Appium (en hızlı); bir önceki ekranın sayfa
    kaynağı hâlâ okunuyorsa BEKLEMEDEN adb input (UiAutomator2'ye dokunmaz → çökme yok)."""
    lk = _lock(sess)
    if lk.acquire(blocking=False):
        try:
            if kind == "tap":
                _tap(sess, *a, locked=True)
            elif kind == "swipe":
                _swipe(sess, *a, locked=True)
            else:
                _wd(sess, "POST", "/back", {}, locked=True)
        finally:
            lk.release()
        return
    ok = (_adb_input(sess, "tap", *a) if kind == "tap" else
          _adb_input(sess, "swipe", *a, 350) if kind == "swipe" else
          _adb_input(sess, "keyevent", 4))
    if not ok:   # adb yok/çok cihaz → Appium'u bekle
        if kind == "tap":
            _tap(sess, *a)
        elif kind == "swipe":
            _swipe(sess, *a)
        else:
            _wd(sess, "POST", "/back", {})


def _png_bytes(im) -> bytes:
    buf = io.BytesIO(); im.save(buf, "PNG", compress_level=1)
    return buf.getvalue()


def _jpeg_data_url(src) -> str:
    from PIL import Image
    im = src.copy() if hasattr(src, "size") else Image.open(io.BytesIO(src)).convert("RGB")
    im.thumbnail((540, 1200))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _analyze(entry: dict, sess: dict, user: User, app: str, version: str) -> dict:
    """Arka plan: sayfa kaynağı + OCR → ekranı haritada bul/ekle → (varsa) geçişi kaydet.
    Sayfa kaynağı (ağ/cihaz beklemesi) ile OCR (CPU) PARALEL çalışır."""
    if entry.get("png") is None:          # adb ham görüntü → PNG kodlama arka planda
        entry["png"] = _png_bytes(entry["img"])
    lines, w, h = amap.ocr_lines(entry["png"])
    entry["src_done"].wait(timeout=30)
    src = entry.get("src")
    entry["source"] = src
    # Kaynak okunurken dokunulduysa (adb ile, beklemeden) kaynak yarı yarıya sonraki ekran
    # olabilir → ekran kimliğine katılmaz; yalnız metin eşleştirmede (OCR ile birebir) kullanılır
    acted = entry.get("acted_at")
    reg_src = None if (acted and entry.get("src_end", 0) > acted) else src
    sid, is_new, name = amap.register_screen(app, entry["png"], lines, user.username, "record", reg_src, version)
    res = {"screen_id": sid, "name": name, "is_new": is_new, "lines": lines, "source": src}
    link = entry.get("link")
    if link:
        try:
            prev = link["prev"]["fut"].result(timeout=60)
            if link.get("resolve"):
                res["tapped"] = _resolve_tap(link, prev, app)
            if prev["screen_id"] != sid:
                _, sid = amap.add_transition(app, prev["screen_id"], sid, link["action"],
                                             user.username, "record", version)
                res["screen_id"] = sid
                res["name"] = amap.load_map(app)["screens"].get(sid, {}).get("name", name)
                res["navigated"] = True
            elif link["action"].get("target"):
                # ekran değişmedi → ekran içi işlem (alana yazı, toggle, aynı ekranda dokunuş)
                amap.add_screen_action(app, sid, link["action"], user.username, "record")
        except Exception as e:
            print(f"[APP-MAP] geçiş kaydedilemedi: {e}")
        finally:
            # Hedef çözülemediyse bile yer tutucu kalmasın
            r = link.get("resolve")
            if r and r["steps"][r["idx"]] is None:
                r["steps"][r["idx"]] = ""
    return res


def _resolve_tap(link: dict, prev: dict, app: str) -> dict:
    """Dokunuş ANINDA yapıldı; neye dokunulduğu (adım metni) burada, önceki ekranın
    analizi (OCR + sayfa kaynağı) bitince bulunur ve adım listesindeki yerine yazılır."""
    r, action = link["resolve"], link["action"]
    xr, yr, x, y = r["xr"], r["yr"], r["x"], r["y"]
    target, step = _element_at(prev, link["prev"]["png"], xr, yr)
    if target and step.startswith('"'):
        real = _source_text_match(prev.get("source"), target, x, y)
        if real:
            target, step = real, f'"{real}" butonuna tıkla'
    icon_loc = None
    if not target:
        # Yazısız ikon: OCR/Evren okuyamadı ama sayfa kaynağında elemanın XPath'i var
        target, step, icon_loc = _icon_step(link.get("loc"), prev.get("source"), x, y,
                                            prev.get("name", ""), app)
    dynamic = amap.is_dynamic_target(amap.load_map(app)["screens"].get(prev["screen_id"], {}), target)
    action.update({"target": target, "label": step})
    r["steps"][r["idx"]] = step
    out = {"target": target, "step": step, "x": x, "y": y, "dynamic": dynamic}
    if icon_loc is not None:
        out["locator"] = icon_loc
    elif target:
        out["locator"] = _save_locator(link.get("loc"), prev.get("source"), x, y, "tap",
                                       target, prev.get("name", ""), app)
    return out


def _icon_step(ld: Optional[dict], source: Optional[str], x: int, y: int,
               screen: str, app: str) -> tuple[str, str, Optional[dict]]:
    """Yazısız eleman → (hedef, adım, locator özeti|None).
    content-desc varsa o ad (normal yoldan kaydedilir → özet None); locator dosyası
    seçiliyse iconN adıyla dosyaya yazılır; dosya yoksa XPath doğrudan adıma girer."""
    loc = locs.locate(source, x, y, "tap")
    if not loc:
        return "", "", None
    # Erişilebilirlik etiketi (Android content-desc; iPhone'da ikonun label'ı — OCR okuyamasa da)
    desc = loc.get("desc", "") or loc.get("text", "")
    if locs._stable_text(desc):
        return desc, f'"{desc}" ikonuna tıkla', None
    if ld:
        try:
            key = locs.add_auto_named(ld["path"], loc, screen, app, ld.get("user", ""))
            return key, f'"{key}" ikonuna tıkla', {"ok": True, "file": ld["name"], "xpath": loc["xpath"],
                                                   "fragile": loc["fragile"], "icon": key}
        except Exception as e:
            print(f"[LOCATOR] ikon yazılamadı: {e}")
    xp = loc["xpath"]
    if '"' in xp:          # adım tırnağıyla çakışmasın
        return "", "", None
    return xp, f'"{xp}" ikonuna tıkla', {"ok": False, "xpath": xp, "fragile": loc["fragile"],
                                          "reason": "locator dosyası seçili değil — XPath adıma yazıldı"}


def _save_locator(ld: Optional[dict], source: Optional[str], x: int, y: int, kind: str,
                  key: str, screen: str, app: str, textless: bool = False) -> Optional[dict]:
    """Seçili locator dosyası varsa noktadaki elemanın XPath'ini yazar → arayüz özeti."""
    if not ld or not key:
        return None
    try:
        loc = locs.locate(source, x, y, kind, key if kind == "input" else "")
        if not loc:
            return {"ok": False, "reason": "sayfa kaynağında eleman bulunamadı"}
        locs.add_element(ld["path"], key, loc, kind, screen, app, ld.get("user", ""), textless=textless)
        return {"ok": True, "file": ld["name"], "xpath": loc["xpath"], "fragile": loc["fragile"]}
    except Exception as e:
        print(f"[LOCATOR] yazılamadı: {e}")
        return {"ok": False, "reason": str(e)}


def _new_entry(user: User, sess: dict, link: Optional[dict] = None, img=None, how: str = "") -> dict:
    """Ekran görüntüsü (verilmediyse al), analizi arka plana at, tarayıcı yanıtını hemen döndür."""
    app = sess.get("app_package") or "bilinmeyen"
    version = _app_version(sess)
    st = _record_state.setdefault(user.id, {"steps": [], "seq": 0})
    if img is None:
        t0 = time.time()
        img, how = _grab(sess)
        print(f"[APP-MAP] ekran görüntüsü ({how}) {time.time() - t0:.2f} sn")
    st["seq"] = st.get("seq", 0) + 1
    entry = {"seq": st["seq"], "png": None, "img": img, "sig": _sig(img), "link": link,
             "src": None, "src_done": threading.Event()}

    def _fetch_source():   # telefon komutları sırayla: önceki kaynak okuması bitince başlar
        lk = _lock(sess)
        try:
            if lk.acquire(timeout=40):
                try:
                    entry["src"] = _wd(sess, "GET", "/source", timeout=20, locked=True)
                    if _is_ios(sess):   # XCUITest kaynağı → Android benzeri öznitelikler
                        entry["src"] = locs.normalize_ios_source(entry["src"])
                finally:
                    entry["src_end"] = time.time()
                    lk.release()
        except Exception as e:
            print(f"[APP-MAP] sayfa kaynağı alınamadı: {e}")
        finally:
            entry["src_done"].set()

    threading.Thread(target=_fetch_source, daemon=True).start()
    entry["fut"] = _analysis_pool.submit(_analyze, entry, sess, user, app, version)
    st.update({"app": app, "version": version, "cur": entry})
    return {"app": app, "version": version, "seq": entry["seq"], "pending": True,
            "image": _jpeg_data_url(img), "steps": _steps_view(st)}


def _steps_view(st: dict) -> list:
    """None = dokunuldu, hedefi henüz çözülüyor; "" = tanınamadı (adım yok)."""
    return ["⏳ ..." if s is None else s for s in st.get("steps", []) if s != ""]


def _status(user: User) -> dict:
    st = _record_state.get(user.id) or {}
    cur = st.get("cur")
    if not cur:
        return {"ready": False}
    if not cur["fut"].done():
        return {"ready": False, "seq": cur["seq"]}
    try:
        r = cur["fut"].result()
    except Exception as e:
        return {"ready": True, "seq": cur["seq"], "error": str(e)}
    return {"ready": True, "seq": cur["seq"], "steps": _steps_view(st),
            "screen": {"id": r["screen_id"], "name": r["name"], "is_new": r["is_new"]},
            "navigated": r.get("navigated", False), "tapped": r.get("tapped"),
            "slots": list(st.get("steps", []))}   # None = çözülüyor, "" = tanınamadı


def _snapshot(user: User, sess: dict) -> dict:
    return _new_entry(user, sess)


def _element_at(res: dict, png: bytes, xr: float, yr: float) -> tuple[str, str]:
    """Dokunulan noktadaki eleman → (hedef metin, senaryo adımı). Önce OCR metni
    (kutu içinde ya da çok yakınında), yoksa Evren'den ok/ikon sınıfı."""
    best, best_d = None, 1e9
    for l in res.get("lines", []):
        x1, y1, x2, y2 = l["box"]
        dx = max(x1 - xr, 0, xr - x2); dy = max(y1 - yr, 0, yr - y2)
        d = (dx * dx + dy * dy) ** 0.5
        if d < best_d and len(l["norm"]) >= 2:
            best, best_d = l, d
    if best and best_d <= 0.03:
        # OCR yanındaki ikonu harf/işaret sanabilir ("%Takım", "Ayarlar >") → baştaki/sondaki
        # harf-rakam olmayan kırıntılar atılır; geriye bir şey kalmazsa ikon yoluna düşülür
        txt = re.sub(r"^[\W_]+|[\W_]+$", "", best["text"].strip())
        if len(amap._norm(txt)) >= 2:
            return txt, f'"{txt}" butonuna tıkla'
    # Metin yok → Evren (yapılandırılmışsa) ok/ikon sınıfına bak
    try:
        from services.ai_service import evren_enabled, evren_predict
        if evren_enabled() and png:
            preds = evren_predict(png, "screen.png", timeout=10).get("predictions") or []
            hits = [p for p in preds if len(p.get("bbox") or []) == 4
                    and p["bbox"][0] <= xr <= p["bbox"][2] and p["bbox"][1] <= yr <= p["bbox"][3]]
            if hits:
                p = min(hits, key=lambda p: (p["bbox"][2] - p["bbox"][0]) * (p["bbox"][3] - p["bbox"][1]))
                cls = amap._norm(p.get("class_name") or "")
                if cls in _ARROW_STEPS:
                    return p["class_name"], _ARROW_STEPS[cls]
    except Exception:
        pass
    return "", ""


def _source_text_match(source_xml: Optional[str], ocr_text: str, x: int, y: int) -> str:
    """OCR metninin uygulamadaki GERÇEK (Türkçe harfli) hâli. OCR modeli Ö/Ş/Ğ/İ/Ç/Ü
    harflerini sadeleştirir ("ÖDEME" → "ODEME"); bu metinle adım yazılırsa koşumda
    eleman bulunamaz. Sayfa kaynağında sadeleştirilmiş hâli OCR ile aynı olan yazı
    aranır — tıklanan noktayı içermesi gerekmez (yazının yanına/butonun boşluğuna
    tıklanmış olabilir); birden fazlaysa noktaya en yakını seçilir."""
    import re as _re
    import xml.etree.ElementTree as ET
    want = amap._norm(ocr_text)
    if not source_xml or not want:
        return ""
    try:
        root = ET.fromstring(source_xml)
    except Exception:
        return ""
    best, best_key = "", None
    for el in root.iter():
        m = _re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        dx = max(x1 - x, 0, x - x2); dy = max(y1 - y, 0, y - y2)
        dist = (dx * dx + dy * dy) ** 0.5
        for attr in ("text", "content-desc"):
            txt = (el.get(attr) or "").strip()
            n = amap._norm(txt)
            if not n or len(txt) > 80:
                continue
            if n == want:
                rank = 0                       # birebir aynı yazı
            elif (want in n or n in want) and dist <= 150:
                rank = 1                       # kısmi (OCR satırı bölmüş/birleştirmiş) — yakında olmalı
            else:
                continue
            key = (rank, dist, len(txt))
            if best_key is None or key < best_key:
                best, best_key = txt, key
    return best


def _do_tap(user: User, xr: float, yr: float) -> dict:
    """HIZ: önceki ekranın analizini BEKLEMEDEN hemen dokunur. Neye dokunulduğu
    (adım metni) arka planda çözülür; adım listesinde yeri şimdiden ayrılır."""
    t0 = time.time()
    sess = _session(user)
    _fast_mode(sess)
    st = _record_state.get(user.id)
    if not st or not st.get("cur"):
        raise HTTPException(400, "Önce ekran görüntüsü alın.")
    prev = st["cur"]
    rect = _rect(sess)
    x, y = int(xr * rect["width"]), int(yr * rect["height"])
    st["busy"] = st.get("busy", 0) + 1
    try:
        prev["src_done"].wait(0.8)
        t_act = prev["acted_at"] = time.time()
        _act(sess, "tap", x, y)
        img, how = _settle(sess, prev.get("sig"), t_act)
    finally:
        st["busy"] -= 1
    st["steps"].append(None)
    action = {"type": "tap", "target": "", "label": "", "point": [round(xr, 4), round(yr, 4)]}
    resolve = {"steps": st["steps"], "idx": len(st["steps"]) - 1, "xr": xr, "yr": yr, "x": x, "y": y}
    out = _new_entry(user, sess, {"prev": prev, "action": action, "resolve": resolve,
                                  "loc": st.get("locator")}, img, how)
    out["tapped"] = {"x": x, "y": y, "pending": True}
    out["slot"] = resolve["idx"]   # sayfa, bu adımın yerini tutar; çözülünce status.slots'tan doldurur
    print(f"[APP-MAP] dokunuş toplam {time.time() - t0:.2f} sn (görüntü: {how})")
    return out


def _do_swipe(user: User, direction: str) -> dict:
    """Aşağı kaydır = içerik aşağı akar (parmak alttan üste). Kural motoruyla aynı anlam."""
    sess = _session(user)
    _fast_mode(sess)
    st = _record_state.setdefault(user.id, {"steps": []})
    prev = st.get("cur")
    rect = _rect(sess)
    w, h = rect["width"], rect["height"]
    y_lo, y_hi = int(h * 0.72), int(h * 0.30)
    st["busy"] = st.get("busy", 0) + 1
    try:
        if prev:
            prev["src_done"].wait(0.8)
            prev["acted_at"] = time.time()
        t_act = time.time()
        if direction == "down":
            _act(sess, "swipe", w // 2, y_lo, w // 2, y_hi)
            step = "Aşağı kaydır"
        else:
            _act(sess, "swipe", w // 2, y_hi, w // 2, y_lo)
            step = "Yukarı kaydır"
        img, how = _settle(sess, prev.get("sig") if prev else None, t_act)
    finally:
        st["busy"] -= 1
    st["steps"].append(step)
    # target boş → aynı ekranda kalırsa ekran içi işlem olarak kaydedilmez
    link = {"prev": prev, "action": {"type": "swipe", "target": "", "label": step}} if prev else None
    out = _new_entry(user, sess, link, img, how)
    out["tapped"] = {"target": step, "step": step, "x": w // 2, "y": y_lo, "dynamic": False}
    return out


def _do_back(user: User) -> dict:
    sess = _session(user)
    _fast_mode(sess)
    st = _record_state.setdefault(user.id, {"steps": []})
    prev = st.get("cur")
    st["busy"] = st.get("busy", 0) + 1
    try:
        if prev:
            prev["src_done"].wait(0.8)
            prev["acted_at"] = time.time()
        t_act = time.time()
        _act(sess, "back")
        img, how = _settle(sess, prev.get("sig") if prev else None, t_act)
    finally:
        st["busy"] -= 1
    st["steps"].append("Geri dön")
    link = {"prev": prev, "action": {"type": "back", "target": "", "label": "Geri dön"}} if prev else None
    return _new_entry(user, sess, link, img, how)


def _field_label_at(source_xml: Optional[str], lines: list, x: int, y: int, xr: float, yr: float) -> str:
    """Yazı alanının adı: önce alanın kendi ipucu/metni (sayfa kaynağı), yoksa alanın
    hemen ÜSTÜNDEKİ etiket (sayfa kaynağı, sonra OCR)."""
    import re as _re
    import xml.etree.ElementTree as ET
    els = []
    if source_xml:
        try:
            for el in ET.fromstring(source_xml).iter():
                m = _re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds") or "")
                if m:
                    els.append((el, tuple(map(int, m.groups()))))
        except Exception:
            els = []
    field = None
    for el, (x1, y1, x2, y2) in els:
        if locs.is_input_class(el.get("class") or el.tag) and x1 <= x <= x2 and y1 <= y <= y2:
            field = (el, (x1, y1, x2, y2))
    if field:
        el, (fx1, fy1, fx2, fy2) = field
        own = (el.get("hint") or "").strip() or (el.get("text") or "").strip()
        if own and not _re.search(r"[0-9]", own):
            return own[:60]
        above = [(fy1 - b[3], (e.get("text") or e.get("content-desc") or "").strip()) for e, b in els
                 if b[3] <= fy1 + 5 and min(b[2], fx2) - max(b[0], fx1) > 0
                 and (e.get("text") or e.get("content-desc") or "").strip()]
        above = [a for a in above if a[0] < 250 and not _re.search(r"[0-9]", a[1])]
        if above:
            return min(above)[1][:60]
    # Sayfa kaynağı yoksa OCR: noktanın içindeki ya da hemen üstündeki yazı
    best, best_d = "", 1e9
    for l in lines or []:
        bx1, by1, bx2, by2 = l["box"]
        inside = bx1 <= xr <= bx2 and by1 <= yr <= by2
        d = 0 if inside else (yr - by2 if by2 <= yr and min(bx2, xr + 0.3) - max(bx1, xr - 0.3) > 0 else 1e9)
        if d < best_d and d < 0.08 and len(l["norm"]) >= 2 and not _re.search(r"[0-9]", l["text"]):
            best, best_d = l["text"].strip(), d
    return best[:60]


def _type_text(sess: dict, value: str) -> None:
    """Odaktaki alana yaz: W3C aktif eleman, olmazsa klavye olayları."""
    try:
        el = _wd(sess, "GET", "/element/active")
        eid = (el or {}).get("element-6066-11e4-a52e-4f735466cecf") or (el or {}).get("ELEMENT")
        if eid:
            _wd(sess, "POST", f"/element/{eid}/value", {"text": value, "value": list(value)})
            return
    except HTTPException:
        pass
    keys = []
    for ch in value:
        keys += [{"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch}]
    _wd(sess, "POST", "/actions", {"actions": [{"type": "key", "id": "kb", "actions": keys}]})


def _do_type(user: User, xr: float, yr: float, value: str) -> dict:
    sess = _session(user)
    _fast_mode(sess)
    st = _record_state.get(user.id)
    if not st or not st.get("cur"):
        raise HTTPException(400, "Önce ekran görüntüsü alın.")
    prev = st["cur"]
    res = prev["fut"].result(timeout=60)
    rect = _rect(sess)
    x, y = int(xr * rect["width"]), int(yr * rect["height"])
    label = _field_label_at(res.get("source"), res.get("lines"), x, y, xr, yr)
    st["busy"] = st.get("busy", 0) + 1   # canlı karede "elle değişti" sanılmasın
    try:
        prev["acted_at"] = time.time()
        _tap(sess, x, y)
        time.sleep(0.3)
        _type_text(sess, value)
        try:
            _wd(sess, "POST", "/appium/device/hide_keyboard", {})
        except HTTPException:
            pass
        img, how = _settle(sess, prev.get("sig"), time.time())
    finally:
        st["busy"] -= 1
    v = value.replace('"', "'")
    step = f'"{label}" alanına "{v}" yaz' if label else f'"{v}" yaz'
    st["steps"].append(step)
    # Gizlilik: haritaya sadece ALAN ADI gider, yazılan değer gitmez
    action = {"type": "input", "target": label, "label": f'"{label}" alanına yazı' if label else "yazı girişi"}
    out = _new_entry(user, sess, {"prev": prev, "action": action}, img, how)
    out["tapped"] = {"target": label or "(alan adı bulunamadı)", "step": step, "x": x, "y": y, "dynamic": False}
    if label:
        out["tapped"]["locator"] = _save_locator(st.get("locator"), res.get("source"), x, y, "input",
                                                 label, res.get("name", ""), sess.get("app_package") or "")
    return out


# ── Endpoint'ler: kayıt modu ────────────────────────────────────────────────

class TapRequest(BaseModel):
    x: float   # görüntü genişliğine oran (0-1)
    y: float


@router.post("/record/snapshot")
async def record_snapshot(current_user: User = Depends(get_current_user)):
    sess = _session(current_user)
    await run_in_threadpool(_fast_mode, sess)
    _record_state.setdefault(current_user.id, {"steps": [], "seq": 0})["on"] = True
    return await run_in_threadpool(_snapshot, current_user, sess)


def _live_frame(user: User, device_id: str) -> tuple[bytes, str, int]:
    """(jpeg, kaynak, kayıt seq). Oturumun MJPEG akışı varsa son kare (anında); yoksa adb
    ham görüntü, o da yoksa Appium. Kayıt modundayken ekran ELLE değiştirildiyse
    (telefona doğrudan dokunuldu) ve görüntü durulduysa yeni ekran olarak kaydedilir."""
    from PIL import Image
    from routers.ai_test_generator_router import _get_session
    sess = _get_session(user.id, "mobile")
    dev = device_id or (sess or {}).get("device_id") or ""
    use_sess = sess if sess and (not device_id or device_id == (sess.get("device_id") or device_id)) else None
    if dev:
        # Başkasının kullandığı telefonun ekranı gösterilmez (müşteri verisi olabilir)
        from services import device_lease_service as leases
        try:
            leases.check_access(dev, user)
        except leases.DeviceBusyError as e:
            raise HTTPException(423, leases.busy_http_detail(e))
    ms = _stream(use_sess)
    jpg, im, how = None, None, ""
    if ms:
        got = ms.latest(0, timeout=1.5)
        if got:
            jpg, how = got[0], "stream"
    from services import device_node_service as dnodes
    is_ios = bool(dev) and dnodes.platform_for(dev) == "ios"
    if jpg is None and is_ios:
        # iPhone'da adb yok: ekran yalnız açık oturumun Appium ekran görüntüsünden alınır
        if not use_sess:
            raise HTTPException(409, "iPhone canlı ekranı için önce ▶ Oturumu Başlat")
        im, how =Image.open(io.BytesIO(_screenshot(use_sess))).convert("RGB"), "appium"
    if jpg is None and im is None:
        im = _adb_screencap(dev)
        if im is None and use_sess:
            im = Image.open(io.BytesIO(_screenshot(use_sess))).convert("RGB")
        if im is None:
            raise HTTPException(404, f"Cihaz ekranı alınamadı [{dev or 'cihaz seçilmedi'}]: {_adb_err.get(dev) or 'adb görüntü vermedi'}")
        how = "adb"
    st = _record_state.get(user.id) or {}
    cur = st.get("cur")
    if use_sess and st.get("on") and cur and not st.get("busy") and cur["fut"].done():
        if im is None:
            im = Image.open(io.BytesIO(jpg)).convert("RGB")
        sg = _sig(im)
        stable = _sig_diff(sg, st.get("live_sig")) < 1.5
        st["live_sig"] = sg
        if stable and _sig_diff(sg, cur.get("sig")) > 6:
            print("[APP-MAP] ekran elle değişti → yeni ekran kaydediliyor")
            _new_entry(user, use_sess, None, im.copy(), how)
    if jpg is None:
        im = im.copy()
        im.thumbnail((540, 1200))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=65)
        jpg = buf.getvalue()
    return jpg, how, int((st.get("cur") or {}).get("seq") or 0)


@router.get("/devices")
async def list_devices(current_user: User = Depends(get_current_user)):
    """Tüm cihaz sunucularındaki (yerel + uzak) Android telefonlar: [{id, model, node, ...}]."""
    from services import device_lease_service as leases
    from services import device_node_service as dnodes
    found, _ = await run_in_threadpool(dnodes.discover)
    holders = leases.all_holders()
    devs = []
    for d in found:
        if d["adb_state"] != "device":
            continue
        h = holders.get(d["id"])
        devs.append({"id": d["id"], "model": d["model"], "platform": d.get("platform", "android"),
                     "node": "" if d["node_id"] == 0 else d["node_name"],
                     "busy": bool(h), "mine": bool(h) and h["user_id"] == current_user.id,
                     "holder": h["display"] if h else "",
                     "purposes": leases.purposes_text(h) if h else ""})
    return {"devices": devs}


@router.get("/live")
async def live_frame(device_id: str = "", current_user: User = Depends(get_current_user)):
    from fastapi.responses import Response
    jpg, how, seq = await run_in_threadpool(_live_frame, current_user, device_id)
    return Response(jpg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Live-Src": how, "X-Rec-Seq": str(seq),
        "Access-Control-Expose-Headers": "X-Live-Src, X-Rec-Seq"})


@router.post("/record/stop")
async def record_stop(current_user: User = Depends(get_current_user)):
    """Kayıt modu kapandı → UiAutomator2 boşta bekleme ayarını varsayılana döndür
    (aynı oturumda koşulacak adımlar eski davranışla çalışsın)."""
    from routers.ai_test_generator_router import _get_session
    sess = _get_session(current_user.id, "mobile")
    st = _record_state.get(current_user.id)
    if st:
        st["on"] = False
    if sess:
        await run_in_threadpool(_fast_mode, sess, False)
    return {"success": True}


def _inspect(user: User, xr: float, yr: float) -> dict:
    import xml.etree.ElementTree as ET
    sess = _session(user)
    st = _record_state.get(user.id)
    if not st or not st.get("cur"):
        raise HTTPException(400, "Önce ekran görüntüsü alın.")
    cur = st["cur"]
    res = cur["fut"].result(timeout=30)
    rect = _rect(sess)
    x, y = int(xr * rect["width"]), int(yr * rect["height"])
    target, _ = _element_at(res, cur.get("png"), xr, yr)
    if target:
        target = _source_text_match(res.get("source"), target, x, y) or target
    else:
        # Yazısız ikon: dokunuştaki gibi content-desc → (dosya seçiliyse) iconN → XPath.
        # iconN burada sadece önerilir; dosyaya doğrulama adımı seçilince yazılır (/record/verify)
        loc = locs.locate(res.get("source"), x, y, "verify")
        if loc:
            desc, ld = loc.get("desc", "") or loc.get("text", ""), st.get("locator")
            if locs._stable_text(desc):
                return {"target": desc, "kind": "icon", "textless": False}
            if ld:
                return {"target": locs.auto_name(ld["path"], loc), "kind": "icon", "textless": True}
            if '"' not in loc["xpath"]:
                return {"target": loc["xpath"], "kind": "icon", "textless": False, "xpath_only": True}
        return {"target": "", "kind": "text"}
    kind = "text"
    try:   # noktadaki en küçük eleman tıklanabilir/buton mu?
        best = None
        for el in ET.fromstring(res.get("source") or "").iter():
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds") or "")
            if not m:
                continue
            x1, y1, x2, y2 = map(int, m.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                area = (x2 - x1) * (y2 - y1)
                if best is None or area < best[0]:
                    best = (area, el)
        if best is not None:
            el = best[1]
            cls = el.get("class") or el.tag
            if "Button" in cls or el.get("clickable") == "true":
                kind = "button"
    except Exception:
        pass
    return {"target": target, "kind": kind}


class InspectRequest(BaseModel):
    x: float
    y: float


@router.post("/record/inspect")
async def record_inspect(req: InspectRequest, current_user: User = Depends(get_current_user)):
    """Dokunmadan: noktadaki yazı ve tür (buton/metin) — doğrulama adımı eklemek için."""
    if not (0 <= req.x <= 1 and 0 <= req.y <= 1):
        raise HTTPException(400, "Koordinat 0-1 aralığında olmalı")
    return await run_in_threadpool(_inspect, current_user, req.x, req.y)


class SwipeRequest(BaseModel):
    direction: str   # "down" | "up"


@router.post("/record/swipe")
async def record_swipe(req: SwipeRequest, current_user: User = Depends(get_current_user)):
    if req.direction not in ("down", "up"):
        raise HTTPException(400, "Yön 'down' ya da 'up' olmalı")
    return await run_in_threadpool(_do_swipe, current_user, req.direction)


@router.get("/record/status")
async def record_status(current_user: User = Depends(get_current_user)):
    """Son ekranın arka plan analizi bitti mi? (ekran adı, yeni mi, geçiş)"""
    return _status(current_user)


@router.post("/record/tap")
async def record_tap(req: TapRequest, current_user: User = Depends(get_current_user)):
    if not (0 <= req.x <= 1 and 0 <= req.y <= 1):
        raise HTTPException(400, "Koordinat 0-1 aralığında olmalı")
    return await run_in_threadpool(_do_tap, current_user, req.x, req.y)


class TypeRequest(BaseModel):
    x: float
    y: float
    value: str


@router.post("/record/type")
async def record_type(req: TypeRequest, current_user: User = Depends(get_current_user)):
    if not (0 <= req.x <= 1 and 0 <= req.y <= 1):
        raise HTTPException(400, "Koordinat 0-1 aralığında olmalı")
    if not req.value:
        raise HTTPException(400, "Yazılacak değer boş")
    return await run_in_threadpool(_do_type, current_user, req.x, req.y, req.value)


@router.post("/record/back")
async def record_back(current_user: User = Depends(get_current_user)):
    return await run_in_threadpool(_do_back, current_user)


@router.post("/record/reset")
async def record_reset(current_user: User = Depends(get_current_user)):
    st = _record_state.get(current_user.id)
    if st:
        st["steps"] = []
    return {"success": True}


class VerifyRequest(BaseModel):
    x: float
    y: float
    target: str
    textless: bool = False   # yazısız ikon (iconN) — doğrulamada da XPath kullanılır


@router.post("/record/verify")
async def record_verify(req: VerifyRequest, current_user: User = Depends(get_current_user)):
    """Sağ tıkla eklenen doğrulama adımının elemanını locator dosyasına yazar."""
    if not (0 <= req.x <= 1 and 0 <= req.y <= 1):
        raise HTTPException(400, "Koordinat 0-1 aralığında olmalı")

    def _run():
        sess = _session(current_user)
        st = _record_state.get(current_user.id) or {}
        cur = st.get("cur")
        if not cur or not st.get("locator"):
            return {"locator": None}
        res = cur["fut"].result(timeout=30)
        rect = _rect(sess)
        x, y = int(req.x * rect["width"]), int(req.y * rect["height"])
        return {"locator": _save_locator(st["locator"], res.get("source"), x, y, "verify",
                                         req.target, res.get("name", ""),
                                         sess.get("app_package") or "", textless=req.textless)}
    return await run_in_threadpool(_run)


# ── Endpoint'ler: locator dosyaları (workspace/locators/<isim>.json) ────────

def _workspace(user: User, db: Session):
    from routers.ai_test_generator_router import _get_user_workspace
    ws = _get_user_workspace(user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadı. Önce Workspace sayfasından bir repo clone edin.")
    return ws


def _commit_push(user: User, ws, message: str) -> dict:
    from pathlib import Path
    from services import git_service
    email = getattr(user, "email", None) or f"{user.username}@localhost"
    committed = pushed = False
    try:
        committed = git_service.commit_changes(Path(ws.local_path), message,
                                               author=f"{user.username} <{email}>")
    except Exception as e:
        print(f"[LOCATOR] git commit başarısız: {e}")
    if committed:
        repo = ws.repository
        try:
            git_service.push_branch(Path(ws.local_path), ws.branch_name,
                                    username=repo.git_username if repo else None,
                                    token=repo.git_token if repo else None)
            pushed = True
        except Exception as e:
            print(f"[LOCATOR] git push başarısız: {e}")
    return {"committed": committed, "pushed": pushed}


def _selected(user: User) -> str:
    return ((_record_state.get(user.id) or {}).get("locator") or {}).get("name", "")


@router.get("/locators")
async def locator_list(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _workspace(current_user, db)
    return {"files": locs.list_files(ws.local_path), "selected": _selected(current_user)}


class LocatorNameRequest(BaseModel):
    name: str = ""


def _select(user: User, ws, name: str) -> None:
    st = _record_state.setdefault(user.id, {"steps": [], "seq": 0})
    if not name:
        st.pop("locator", None)
        return
    p = locs.file_path(ws.local_path, name)
    if not p.exists():
        raise HTTPException(404, f"'{name}' locator dosyası bulunamadı")
    st["locator"] = {"name": p.stem, "path": str(p), "user": user.username}


@router.post("/locators")
async def locator_create(req: LocatorNameRequest, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Yeni locator dosyası oluşturur ve kayıt için seçer."""
    from routers.ai_test_generator_router import _get_session
    ws = _workspace(current_user, db)
    app = (_get_session(current_user.id, "mobile") or {}).get("app_package") or ""
    try:
        data = locs.create_file(ws.local_path, req.name, app, current_user.username)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _select(current_user, ws, data["name"])
    git = await run_in_threadpool(_commit_push, current_user, ws, f"locator: '{data['name']}' oluşturuldu")
    return {"name": data["name"], "selected": data["name"], **git}


@router.post("/locators/select")
async def locator_select(req: LocatorNameRequest, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Kayıtta XPath'lerin yazılacağı dosyayı seçer (boş ad = seçimi kaldır)."""
    ws = _workspace(current_user, db)
    _select(current_user, ws, req.name.strip())
    return {"selected": _selected(current_user)}


@router.post("/locators/commit")
async def locator_commit(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Seçili locator dosyasındaki değişiklikleri commit + push eder (kayıt bitince)."""
    name = _selected(current_user)
    if not name:
        return {"committed": False, "pushed": False}
    ws = _workspace(current_user, db)
    git = await run_in_threadpool(_commit_push, current_user, ws, f"locator: '{name}' güncellendi")
    return {"name": name, **git}


class LocatorElementUpdate(BaseModel):
    key: str
    new_key: str = ""
    xpath: str
    alternatives: list[str] = []


class LocatorElementKey(BaseModel):
    key: str


@router.post("/locators/{name}/element/update")
async def locator_element_update(name: str, req: LocatorElementUpdate,
                                 current_user: User = Depends(get_current_user),
                                 db: Session = Depends(get_db)):
    """Elemanın adını / XPath'ini / alternatiflerini elle düzeltir (commit + push)."""
    ws = _workspace(current_user, db)
    try:
        el = locs.update_element(ws.local_path, name, req.key, req.new_key, req.xpath,
                                 req.alternatives, current_user.username)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    git = await run_in_threadpool(_commit_push, current_user, ws,
                                  f"locator: '{name}' / '{el['key']}' düzenlendi")
    return {"element": el, **git}


@router.post("/locators/{name}/element/delete")
async def locator_element_delete(name: str, req: LocatorElementKey,
                                 current_user: User = Depends(get_current_user),
                                 db: Session = Depends(get_db)):
    ws = _workspace(current_user, db)
    try:
        locs.delete_element(ws.local_path, name, req.key)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    git = await run_in_threadpool(_commit_push, current_user, ws, f"locator: '{name}' / '{req.key}' silindi")
    return {"deleted": req.key, **git}


@router.get("/locators/{name}")
async def locator_detail(name: str, current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    ws = _workspace(current_user, db)
    try:
        return locs.read_file(ws.local_path, name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))


# ── Endpoint: kayıt adımları → ADO Excel (Java Generator içe aktarma formatı) ─

class AdoExportRequest(BaseModel):
    title: str
    steps: list[str]


@router.post("/export/ado")
async def export_ado(req: AdoExportRequest, current_user: User = Depends(get_current_user)):
    from urllib.parse import quote
    from fastapi.responses import StreamingResponse
    from routers.testcasegen_router import _tcg_defaults_dict
    from services.testcasegen_service import build_export_workbook
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "Test case başlığı boş")
    rows = locs.steps_to_ado(req.steps)
    if not rows:
        raise HTTPException(400, "Dışa aktarılacak adım yok")
    d = _tcg_defaults_dict(current_user)
    wb = build_export_workbook([{"title_id": "t", "steps": rows}], {"t": {"text": title}},
                               d["area_path"], d["assigned_to"], d["state"])
    from openpyxl.styles import Alignment
    for row in wb.active.iter_rows(min_row=2):      # çok satırlı Expected hücresi okunur kalsın
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = (locs.sanitize_name(title) or "test_case") + ".xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


# ── Endpoint'ler: harita görüntüleme ────────────────────────────────────────

@router.get("/apps")
async def map_apps(current_user: User = Depends(get_current_user)):
    return {"apps": amap.list_apps()}


@router.get("/maps/{app}")
async def map_detail(app: str, current_user: User = Depends(get_current_user)):
    m = amap.load_map(app)
    screens = [{"id": sid, **amap.public_screen(s)} for sid, s in m["screens"].items()]
    return {"app": m["app"], "screens": screens, "transitions": m["transitions"]}


@router.get("/maps/{app}/screens/{screen_id}/thumb")
async def map_thumb(app: str, screen_id: str, current_user: User = Depends(get_current_user)):
    p = amap.screen_thumb_path(app, screen_id)
    if not p:
        raise HTTPException(404, "Görüntü yok")
    return FileResponse(p, media_type="image/jpeg")


class RenameRequest(BaseModel):
    name: str


@router.post("/maps/{app}/screens/{screen_id}/rename")
async def map_rename(app: str, screen_id: str, req: RenameRequest,
                     current_user: User = Depends(get_current_user)):
    if not req.name.strip():
        raise HTTPException(400, "Ad boş olamaz")
    if not amap.rename_screen(app, screen_id, req.name):
        raise HTTPException(404, "Ekran bulunamadı")
    return {"success": True}


@router.delete("/maps/{app}/screens/{screen_id}")
async def map_delete_screen(app: str, screen_id: str, current_user: User = Depends(get_current_user)):
    if not amap.delete_screen(app, screen_id):
        raise HTTPException(404, "Ekran bulunamadı")
    return {"success": True}


@router.delete("/maps/{app}/transitions/{transition_id}")
async def map_delete_transition(app: str, transition_id: str, current_user: User = Depends(get_current_user)):
    if not amap.delete_transition(app, transition_id):
        raise HTTPException(404, "Geçiş bulunamadı")
    return {"success": True}


class MergeRequest(BaseModel):
    into: str   # korunacak ekran


@router.post("/maps/{app}/screens/{screen_id}/merge")
async def map_merge(app: str, screen_id: str, req: MergeRequest, current_user: User = Depends(get_current_user)):
    """screen_id ekranını req.into ekranına katar (aynı ekran iki kez kaydedildiyse)."""
    if not amap.merge_screens(app, req.into, screen_id):
        raise HTTPException(400, "Birleştirilemedi (ekran yok ya da aynı ekran)")
    return {"success": True}


@router.get("/maps/{app}/path")
async def map_path(app: str, from_id: str, to_id: str, current_user: User = Depends(get_current_user)):
    """İki ekran arası en kısa yol + senaryoya eklenebilecek adım metinleri."""
    path = amap.find_path(app, from_id, to_id)
    if path is None:
        raise HTTPException(404, "Haritada bu iki ekran arasında yol yok")
    return {"transitions": path,
            "steps": [t["action"].get("label") or t["action"].get("target") for t in path],
            "dynamic_steps": [i for i, t in enumerate(path) if t["action"].get("dynamic")]}
