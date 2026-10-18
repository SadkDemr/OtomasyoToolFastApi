"""
Device Node Service — telefonların takılı olduğu makineler (yerel + uzak)
==========================================================================
Uygulama bir VM'de (ya da ayrı bir sunucuda) çalışırken telefonlar başka makinelere
USB ile takılı olabilir (KVM ana makinesi Ubuntu, Mac mini...). O makinelerde:
  - adb sunucusu ağı dinler  (adb -a -P 5037 nodaemon server start)
  - Appium çalışır           (appium --address 0.0.0.0 --port 4723)
Uygulama telefona ait her adb komutunu o makinenin adb sunucusuna (-H host -P port)
yönlendirir, oturumu o makinenin Appium'unda açar. Üretilen script'lerin kendi adb
çağrıları da (monkey, dumpsys, ADB ile yazma) ADB_SERVER_SOCKET ortam değişkeniyle
aynı sunucuya gider.

"Bu sunucu" (id=0) her zaman vardır: uygulamanın kendi makinesine takılı telefonlar
eskisi gibi yerel adb + istekteki Appium adresiyle çalışır.

Telefon kimliği (adb seri no) tüm sunucularda tekil kabul edilir; hangi telefonun
hangi sunucuda olduğu her keşifte (discover) güncellenen haritada tutulur.
"""

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

LOCAL_NODE = {"id": 0, "name": "Bu sunucu", "host": "", "adb_port": 0, "appium_url": "",
              "platform": "android", "local": True}

_lock = threading.Lock()
_nodes_cache: dict = {"at": 0.0, "nodes": None}
_NODES_TTL = 10.0
_device_map: dict[str, dict] = {}       # adb seri no → düğüm
_last_discover = {"at": 0.0}
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="devnode")


# ── Düğümler ────────────────────────────────────────────────────────────────

def _row(n, with_secret: bool = True) -> dict:
    return {"id": n.id, "name": n.name, "host": n.host, "adb_port": n.adb_port or 5037,
            "appium_url": (n.appium_url or "").rstrip("/"), "platform": n.platform or "android",
            "agent_port": getattr(n, "agent_port", None) or 4724,
            "agent_token": (getattr(n, "agent_token", None) or "") if with_secret else "",
            "has_token": bool(getattr(n, "agent_token", None)),
            "enabled": bool(n.enabled), "note": n.note or "", "local": False}


def invalidate() -> None:
    """Admin düğüm ekleyip/silince önbellek tazelensin."""
    with _lock:
        _nodes_cache["at"] = 0.0


def nodes(include_disabled: bool = False) -> list[dict]:
    """Yerel düğüm + kayıtlı (etkin) uzak düğümler."""
    with _lock:
        fresh = _nodes_cache["nodes"] is not None and time.time() - _nodes_cache["at"] < _NODES_TTL
        cached = _nodes_cache["nodes"]
    if not fresh:
        from database import SessionLocal
        from models.db_models import DeviceNode
        db = SessionLocal()
        try:
            cached = [_row(n) for n in db.query(DeviceNode).order_by(DeviceNode.name).all()]
        except Exception as e:
            print(f"[DEVICE-NODE] düğümler okunamadı: {e}")
            cached = cached or []
        finally:
            db.close()
        with _lock:
            _nodes_cache.update({"at": time.time(), "nodes": cached})
    remote = [n for n in cached if include_disabled or n["enabled"]]
    return [LOCAL_NODE] + remote


def get_node(node_id: int) -> Optional[dict]:
    return next((n for n in nodes(include_disabled=True) if n["id"] == node_id), None)


# ── adb ─────────────────────────────────────────────────────────────────────

def _find_adb() -> str:
    from routers.ai_test_generator_router import _find_adb as f
    return f()


def adb_base(node: dict) -> list[str]:
    """Düğümün adb sunucusuna giden komut başı."""
    if node.get("local"):
        return [_find_adb()]
    return [_find_adb(), "-H", node["host"], "-P", str(node["adb_port"])]


def _parse_devices(out: str, node: dict) -> list[dict]:
    devs = []
    for ln in out.splitlines()[1:]:
        parts = ln.split()
        if len(parts) < 2 or parts[0] == "*":
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        devs.append({"id": parts[0], "model": model.replace("_", " "), "adb_state": parts[1],
                     "node_id": node["id"], "node_name": node["name"], "node_host": node["host"],
                     "platform": "android"})
    return devs


def _list_node(node: dict, timeout: float) -> tuple[list[dict], dict]:
    try:
        r = subprocess.run(adb_base(node) + ["devices", "-l"], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        if r.returncode != 0 and not r.stdout.strip():
            raise RuntimeError((r.stderr or "").strip() or f"adb çıkış kodu {r.returncode}")
        devs = _parse_devices(r.stdout, node)
        return devs, {"ok": True, "count": len(devs), "error": ""}
    except FileNotFoundError:
        return [], {"ok": False, "count": 0, "error": "adb bulunamadı"}
    except subprocess.TimeoutExpired:
        return [], {"ok": False, "count": 0,
                    "error": f"{node['host']}:{node['adb_port']} yanıt vermedi (adb sunucusu ağı dinliyor mu, güvenlik duvarı?)"}
    except Exception as e:
        return [], {"ok": False, "count": 0, "error": str(e)[:200]}


def _agent_url(node: dict) -> str:
    return f"http://{node['host']}:{node.get('agent_port') or 4724}"


def _list_ios_node(node: dict, timeout: float) -> tuple[list[dict], dict]:
    """Mac'teki ios-node-agent.py'den iPhone listesi (Appium cihaz listelemez)."""
    import requests
    try:
        r = requests.get(_agent_url(node) + "/devices", timeout=timeout,
                         headers={"X-Agent-Token": node.get("agent_token") or ""})
        if r.status_code == 401:
            raise RuntimeError("ajan anahtarı (token) hatalı")
        r.raise_for_status()
        devs = [{"id": d["udid"], "model": d.get("name") or d.get("model") or "iPhone",
                 "adb_state": "device" if d.get("state") == "ready" else (d.get("state") or "unavailable"),
                 "os_version": d.get("os_version", ""), "node_id": node["id"], "node_name": node["name"],
                 "node_host": node["host"], "platform": "ios"}
                for d in r.json().get("devices", []) if d.get("udid")]
        return devs, {"ok": True, "count": len(devs), "error": ""}
    except requests.exceptions.ConnectionError:
        return [], {"ok": False, "count": 0,
                    "error": f"{_agent_url(node)} erişilemedi (ios-node-agent çalışıyor mu?)"}
    except requests.exceptions.Timeout:
        return [], {"ok": False, "count": 0, "error": f"{_agent_url(node)} yanıt vermedi"}
    except Exception as e:
        return [], {"ok": False, "count": 0, "error": str(e)[:200]}


def discover(timeout: float = 6) -> tuple[list[dict], dict[int, dict]]:
    """Tüm düğümlerdeki telefonlar (Android: adb, iOS: Mac ajanı; paralel)
    → (telefonlar, düğüm durumları)."""
    def _one(n):
        return (n, *(_list_ios_node(n, timeout) if n["platform"] == "ios" else _list_node(n, timeout)))
    results = list(_pool.map(_one, nodes()))
    devices, status = [], {}
    new_map = {}
    for node, devs, st in results:
        status[node["id"]] = {**st, "name": node["name"], "host": node["host"]}
        for d in devs:
            devices.append(d)
            new_map.setdefault(d["id"], node)      # aynı seri iki yerde: ilk bulunan
    with _lock:
        # Ulaşılamayan düğümün telefonları haritadan düşmesin (geçici kopukluk)
        down = {nid for nid, st in status.items() if not st["ok"]}
        for serial, node in _device_map.items():
            if node["id"] in down and serial not in new_map:
                new_map[serial] = node
        _device_map.clear()
        _device_map.update(new_map)
        _last_discover["at"] = time.time()
    return devices, status


def node_for(serial: str) -> dict:
    """Telefonun bulunduğu düğüm (bilinmiyorsa bir kez keşif; yoksa yerel)."""
    serial = (serial or "").strip()
    if not serial:
        return LOCAL_NODE
    with _lock:
        node = _device_map.get(serial)
        stale = time.time() - _last_discover["at"] > 3
    if node is None and stale:
        discover()
        with _lock:
            node = _device_map.get(serial)
    return node or LOCAL_NODE


def adb_cmd(serial: str, *args: str) -> list[str]:
    """Telefona adb komutu: doğru sunucuya, doğru cihaza."""
    base = adb_base(node_for(serial))
    return base + (["-s", serial] if serial else []) + list(args)


def is_remote(serial: str) -> bool:
    return not node_for(serial).get("local")


def platform_for(serial: str) -> str:
    """"ios" (Mac düğümündeki iPhone) ya da "android"."""
    return "ios" if node_for(serial).get("platform") == "ios" else "android"


def appium_url_for(serial: str, default: str) -> str:
    """Uzak telefonun oturumu kendi makinesindeki Appium'da açılır."""
    node = node_for(serial)
    return default if node.get("local") else node["appium_url"]


def adb_env_for(serial: str) -> dict:
    """Script'in kendi adb çağrıları için: adb istemcisi bu sunucuya bağlanır."""
    node = node_for(serial)
    if node.get("local") or node.get("platform") == "ios":
        return {}
    return {"ADB_SERVER_SOCKET": f"tcp:{node['host']}:{node['adb_port']}"}


def adb_devices(only_ready: bool = True) -> list[str]:
    devs, _ = discover()
    return [d["id"] for d in devs if not only_ready or d["adb_state"] == "device"]


# ── Bağlantı testi (admin) ──────────────────────────────────────────────────

def test_node(node: dict) -> dict:
    """"adb" anahtarı iOS'ta Mac ajanının (cihaz listesi) sonucudur."""
    devs, st = (_list_ios_node if node.get("platform") == "ios" else _list_node)(node, 6)
    out = {"adb": st, "devices": [{"id": d["id"], "model": d["model"], "adb_state": d["adb_state"]} for d in devs]}
    if node.get("appium_url"):
        try:
            import requests
            r = requests.get(node["appium_url"].rstrip("/") + "/status", timeout=5)
            ready = r.ok and (r.json().get("value") or {}).get("ready", True)
            out["appium"] = {"ok": bool(ready), "error": "" if ready else f"HTTP {r.status_code}"}
        except Exception as e:
            out["appium"] = {"ok": False, "error": f"{node['appium_url']} erişilemedi: {str(e)[:150]}"}
    return out
