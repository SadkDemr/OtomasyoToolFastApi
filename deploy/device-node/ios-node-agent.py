#!/usr/bin/env python3
"""
iOS Cihaz Sunucusu Ajanı (Mac mini)
====================================
Appium iPhone listesi vermez; uygulama (Cihaz Havuzu) Mac'e takılı iPhone'ları bu
küçük HTTP servisinden öğrenir. Yalnızca Python standart kütüphanesi kullanır.

  GET /health                       → {"ok": true}
  GET /devices   (X-Agent-Token)    → {"devices": [{"udid","name","model","os_version","state"}]}
      state: "ready" (eşleşmiş, kullanılabilir) | "unauthorized" (iPhone'da "Bu bilgisayara
             güven" onaylanmamış) | "unavailable"

Kaynak: libimobiledevice (idevice_id / ideviceinfo); yoksa Xcode'un `xcrun devicectl`.
Ortam: AGENT_TOKEN (zorunlu), AGENT_PORT (varsayılan 4724), AGENT_BIND (0.0.0.0)
"""

import hmac
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("AGENT_TOKEN", "")
PORT = int(os.environ.get("AGENT_PORT", "4724"))
BIND = os.environ.get("AGENT_BIND", "0.0.0.0")
CACHE_SEC = 4.0

_cache = {"at": 0.0, "devices": []}
_lock = threading.Lock()


def _run(cmd, timeout=10):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def _via_libimobiledevice():
    if not shutil.which("idevice_id"):
        return None
    code, out, _ = _run(["idevice_id", "-l"])
    if code != 0:
        return []
    devs = []
    for udid in [l.strip() for l in out.splitlines() if l.strip()]:
        info = {}
        c, o, e = _run(["ideviceinfo", "-u", udid], timeout=8)
        if c == 0:
            for ln in o.splitlines():
                if ": " in ln:
                    k, v = ln.split(": ", 1)
                    info[k.strip()] = v.strip()
            state = "ready"
        else:
            msg = (e + o).lower()
            state = "unauthorized" if ("pair" in msg or "trust" in msg) else "unavailable"
        devs.append({"udid": udid, "name": info.get("DeviceName", ""), "model": info.get("ProductType", ""),
                     "os_version": info.get("ProductVersion", ""), "state": state})
    return devs


def _via_devicectl():
    if not shutil.which("xcrun"):
        return []
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        code, _, _ = _run(["xcrun", "devicectl", "list", "devices", "--json-output", path], timeout=20)
        if code != 0:
            return []
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    devs = []
    for d in (data.get("result") or {}).get("devices", []):
        hw, dp, cp = d.get("hardwareProperties", {}), d.get("deviceProperties", {}), d.get("connectionProperties", {})
        if hw.get("platform") not in (None, "iOS") or not hw.get("udid"):
            continue
        if cp.get("transportType") not in ("wired", None):
            continue            # yalnız USB'ye takılı telefonlar
        paired = cp.get("pairingState") == "paired"
        devs.append({"udid": hw["udid"], "name": dp.get("name", ""),
                     "model": hw.get("marketingName") or hw.get("productType", ""),
                     "os_version": dp.get("osVersionNumber", ""),
                     "state": "ready" if paired else "unauthorized"})
    return devs


def list_devices():
    with _lock:
        if time.time() - _cache["at"] < CACHE_SEC:
            return _cache["devices"]
    devs = _via_libimobiledevice()
    if devs is None:
        devs = _via_devicectl()
    with _lock:
        _cache.update({"at": time.time(), "devices": devs})
    return devs


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path.split("?")[0] != "/devices":
            return self._send(404, {"error": "bulunamadı"})
        if not hmac.compare_digest(self.headers.get("X-Agent-Token", ""), TOKEN):
            return self._send(401, {"error": "geçersiz anahtar"})
        try:
            return self._send(200, {"devices": list_devices()})
        except Exception as e:
            return self._send(500, {"error": str(e)[:200]})

    def log_message(self, fmt, *args):   # erişim günlüğü gürültüsü yok
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("AGENT_TOKEN tanımlı değil")
    print(f"iOS cihaz ajanı {BIND}:{PORT} dinliyor")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
