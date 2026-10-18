"""
Device Lease Service — fiziksel telefonların kullanıcılar arasında paylaşımı
=============================================================================
Bir telefonu kullanan her yol (AI Generator oturumu, tek seferlik koşum, AI Job
hücreleri) önce telefonu KİRALAR (acquire). Telefon başka bir kullanıcıdaysa istek
DeviceBusyError ile reddedilir; hata, telefonu kimin, ne için, ne zamandan beri
kullandığını taşır ki arayüz "Ahmet Y. kullanıyor (oturum, 12 dk)" diyebilsin.

Kurallar:
- Aynı telefonu aynı anda yalnızca BİR kullanıcı kullanabilir.
- Aynı kullanıcı kendi telefonunu birden fazla amaçla kullanabilir (kendi oturumu
  açıkken o telefonda koşum başlatması gibi) — her kullanım ayrı bir kira (token)
  olarak sayılır, son kira bırakılınca telefon boşa düşer.
- Kiralar bellekte tutulur: oturumlar ve koşum süreçleri de bellekte yaşadığından
  sunucu yeniden başlayınca hepsi birlikte sıfırlanır (artık kira kalmaz).
- Yönetici bir telefonu zorla boşa çıkarabilir (force_release).
"""

import asyncio
import threading
import time
import uuid
from typing import Optional


class DeviceBusyError(Exception):
    def __init__(self, device_id: str, holder: dict):
        self.device_id = device_id
        self.holder = holder
        super().__init__(busy_message(device_id, holder))


_PURPOSE_TR = {"session": "oturum", "run": "koşum", "job": "AI Job"}

_lock = threading.Lock()
# device_id → {"user_id", "username", "display", "since", "leases": {token: {...}}}
_devices: dict[str, dict] = {}


def _display(user) -> str:
    return (getattr(user, "full_name", None) or getattr(user, "username", None) or "?").strip()


def _fmt_age(sec: float) -> str:
    m = int(sec // 60)
    if m < 1:
        return "az önce"
    if m < 60:
        return f"{m} dk"
    return f"{m // 60} sa {m % 60} dk"


def purposes_text(holder: dict) -> str:
    return ", ".join(sorted({_PURPOSE_TR.get(l["purpose"], l["purpose"])
                             for l in holder.get("leases", [])})) or "kullanımda"


def busy_message(device_id: str, holder: dict) -> str:
    return (f"Telefon meşgul: {device_id} şu anda {holder.get('display', '?')} tarafından "
            f"kullanılıyor ({purposes_text(holder)}, {_fmt_age(time.time() - holder.get('since', time.time()))})")


def _snapshot(device_id: str) -> Optional[dict]:
    d = _devices.get(device_id)
    if not d or not d["leases"]:
        return None
    return {
        "device_id": device_id, "user_id": d["user_id"], "username": d["username"],
        "display": d["display"], "since": d["since"],
        "leases": [{"token": t, **l} for t, l in d["leases"].items()],
    }


def acquire(device_id: str, user, purpose: str, detail: str = "", ref=None) -> str:
    """Telefonu kirala → token. Başka kullanıcıdaysa DeviceBusyError.
    ref: kirayı tutan işin kimliği (koşum run_id / job run_id) — zorla bırakmada durdurmak için."""
    device_id = (device_id or "").strip()
    if not device_id:
        raise ValueError("Cihaz belirtilmedi")
    with _lock:
        d = _devices.get(device_id)
        if d and d["leases"] and d["user_id"] != user.id:
            raise DeviceBusyError(device_id, _snapshot(device_id))
        if not d or not d["leases"]:
            d = {"user_id": user.id, "username": user.username, "display": _display(user),
                 "since": time.time(), "leases": {}}
            _devices[device_id] = d
        token = uuid.uuid4().hex[:12]
        d["leases"][token] = {"purpose": purpose, "detail": detail, "since": time.time(), "ref": ref}
        return token


def release(device_id: str, token: Optional[str]) -> None:
    if not token:
        return
    with _lock:
        d = _devices.get(device_id)
        if not d:
            return
        d["leases"].pop(token, None)
        if not d["leases"]:
            _devices.pop(device_id, None)


async def acquire_wait(device_id: str, user, purpose: str, detail: str = "", ref=None,
                       timeout: float = 600, poll: float = 5, on_wait=None,
                       cancelled=None) -> str:
    """Telefon boşalana kadar bekleyerek kirala (AI Job hücreleri için).
    on_wait(holder): ilk beklemede bir kez çağrılan async geri çağrı (arayüze yayın).
    cancelled(): True dönerse bekleme bırakılır (koşum durduruldu)."""
    deadline = time.time() + timeout
    notified = False
    while True:
        try:
            return acquire(device_id, user, purpose, detail, ref)
        except DeviceBusyError as e:
            if time.time() >= deadline or (cancelled and cancelled()):
                raise
            if on_wait and not notified:
                notified = True
                try:
                    await on_wait(e.holder)
                except Exception:
                    pass
        await asyncio.sleep(poll)


def holder(device_id: str) -> Optional[dict]:
    with _lock:
        return _snapshot(device_id)


def check_access(device_id: str, user) -> None:
    """Kiralamadan erişim kontrolü (canlı ekran gibi): başkasının telefonuysa DeviceBusyError."""
    with _lock:
        d = _devices.get(device_id)
        if d and d["leases"] and d["user_id"] != user.id:
            raise DeviceBusyError(device_id, _snapshot(device_id))


def all_holders() -> dict[str, dict]:
    with _lock:
        return {dev: _snapshot(dev) for dev in list(_devices) if _devices[dev]["leases"]}


def force_release(device_id: str) -> Optional[dict]:
    """Yönetici: telefonun tüm kiralarını düşürür → düşürülen sahip bilgisi."""
    with _lock:
        snap = _snapshot(device_id)
        _devices.pop(device_id, None)
        return snap


def busy_http_detail(e: DeviceBusyError) -> dict:
    """HTTP 423 gövdesi: arayüz hem mesajı hem sahip bilgisini kullanabilsin."""
    h = e.holder or {}
    return {"message": str(e), "device_id": e.device_id, "holder": h.get("display", ""),
            "username": h.get("username", ""), "purposes": purposes_text(h), "since": h.get("since")}
