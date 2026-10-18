"""
Device Pool Router — paylaşılan telefonların durumu (/api/device-pool)
=======================================================================
Sunucuya bağlı telefonları ve her birini şu anda kimin, ne için kullandığını
gösterir (services/device_lease_service.py). Herkes görür; telefonu boşa çıkarma
yetkisi yöneticide ve telefonu kullanan kişinin kendisindedir — boşa çıkarma,
kirayı tutan işi de kapatır (oturum → driver.quit, koşum → durdur, job → durdur).
"""

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.db_models import DeviceNode, User
from routers.auth import get_current_user, require_admin
from services import device_lease_service as leases
from services import device_node_service as dnodes

router = APIRouter(prefix="/api/device-pool", tags=["Device Pool"])

_ADB_STATE_TR = {"device": "bağlı", "offline": "çevrimdışı", "unauthorized": "yetki bekliyor",
                 "disconnected": "bağlı değil"}


@router.get("")
async def pool_list(current_user: User = Depends(get_current_user)):
    devs, node_status = await asyncio.to_thread(dnodes.discover)
    holders = leases.all_holders()
    seen = {d["id"] for d in devs}
    # Kirası olup bağlantısı kopan telefon da listede kalsın (kim tutuyor görünsün)
    for dev in holders:
        if dev not in seen:
            node = dnodes.node_for(dev)
            devs.append({"id": dev, "model": "", "adb_state": "disconnected",
                         "node_id": node["id"], "node_name": node["name"], "node_host": node["host"]})
    now = time.time()
    out = []
    for d in devs:
        h = holders.get(d["id"])
        if h:
            status = "mine" if h["user_id"] == current_user.id else "busy"
        else:
            status = "free" if d["adb_state"] == "device" else "unavailable"
        out.append({
            **d,
            "node_name": "" if d.get("node_id") == 0 else d.get("node_name", ""),
            "adb_state_tr": _ADB_STATE_TR.get(d["adb_state"], d["adb_state"]),
            "status": status,
            "holder": h["display"] if h else "",
            "username": h["username"] if h else "",
            "since": h["since"] if h else None,
            "age_sec": int(now - h["since"]) if h else 0,
            "purposes": leases.purposes_text(h) if h else "",
            "uses": [{"purpose": l["purpose"], "detail": l["detail"], "since": l["since"]}
                     for l in (h["leases"] if h else [])],
            "can_release": bool(h) and (current_user.role == "admin" or h["user_id"] == current_user.id),
        })
    out.sort(key=lambda x: ({"mine": 0, "busy": 1, "free": 2}.get(x["status"], 3), x["model"] or x["id"]))
    # Yerel düğümde adb yoksa ve telefon da yoksa (uygulama VM'de, telefonlar uzakta) gösterme
    nodes_out = [{"id": nid, **st} for nid, st in node_status.items()
                 if nid != 0 or st["ok"] or st["count"]]
    return {"devices": out, "nodes": nodes_out, "is_admin": current_user.role == "admin"}


# ── Cihaz sunucuları (admin) ────────────────────────────────────────────────

class NodeIn(BaseModel):
    name: str
    host: str
    adb_port: int = 5037
    appium_url: str = ""          # boşsa http://<host>:4723
    platform: str = "android"
    agent_port: int = 4724        # ios: Mac'teki ios-node-agent
    agent_token: str = ""         # ios: düzenlemede boş = mevcut anahtar korunur
    enabled: bool = True
    note: str = ""


def _clean(body: NodeIn) -> dict:
    name, host = body.name.strip(), body.host.strip()
    if not name or not host:
        raise HTTPException(400, "Ad ve adres (IP) zorunlu")
    if body.platform not in ("android", "ios"):
        raise HTTPException(400, "Platform 'android' ya da 'ios' olmalı")
    if not (1 <= body.adb_port <= 65535) or not (1 <= body.agent_port <= 65535):
        raise HTTPException(400, "Port 1-65535 arasında olmalı")
    url = (body.appium_url or "").strip().rstrip("/") or f"http://{host}:4723"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Appium adresi http:// ile başlamalı")
    out = {"name": name, "host": host, "adb_port": body.adb_port, "appium_url": url,
           "platform": body.platform, "agent_port": body.agent_port,
           "enabled": body.enabled, "note": body.note.strip()}
    if body.agent_token.strip():
        out["agent_token"] = body.agent_token.strip()
    return out


@router.get("/nodes")
async def nodes_list(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(DeviceNode).order_by(DeviceNode.name).all()
    return {"nodes": [dnodes._row(n, with_secret=False) for n in rows]}


@router.post("/nodes")
async def nodes_create(body: NodeIn, current_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    data = _clean(body)
    if data["platform"] == "ios" and not data.get("agent_token"):
        raise HTTPException(400, "iOS sunucusu için ajan anahtarı (token) gerekli — Mac kurulumunun sonunda yazdırılır")
    n = DeviceNode(**data)
    db.add(n)
    db.commit()
    db.refresh(n)
    dnodes.invalidate()
    return dnodes._row(n, with_secret=False)


@router.put("/nodes/{node_id}")
async def nodes_update(node_id: int, body: NodeIn, current_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    n = db.query(DeviceNode).filter(DeviceNode.id == node_id).first()
    if not n:
        raise HTTPException(404, "Cihaz sunucusu bulunamadı")
    for k, v in _clean(body).items():
        setattr(n, k, v)
    db.commit()
    dnodes.invalidate()
    return dnodes._row(n, with_secret=False)


@router.delete("/nodes/{node_id}")
async def nodes_delete(node_id: int, current_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    n = db.query(DeviceNode).filter(DeviceNode.id == node_id).first()
    if not n:
        raise HTTPException(404, "Cihaz sunucusu bulunamadı")
    busy = [d for d in leases.all_holders() if dnodes.node_for(d)["id"] == node_id]
    if busy:
        raise HTTPException(409, f"Bu sunucudaki telefon(lar) kullanımda: {', '.join(busy)} — önce boşa çıkarın")
    db.delete(n)
    db.commit()
    dnodes.invalidate()
    return {"deleted": node_id}


class NodeTestIn(BaseModel):
    host: str
    adb_port: int = 5037
    appium_url: str = ""
    platform: str = "android"
    agent_port: int = 4724
    agent_token: str = ""
    node_id: Optional[int] = None   # düzenlenen sunucu: anahtar boşsa kayıtlı anahtar kullanılır


@router.post("/nodes/test")
async def nodes_test(body: NodeTestIn, current_user: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Kaydetmeden bağlantı denemesi: Android → adb sunucusu, iOS → Mac ajanı; + Appium /status."""
    token = body.agent_token.strip()
    if not token and body.node_id:
        n = db.query(DeviceNode).filter(DeviceNode.id == body.node_id).first()
        token = (n.agent_token or "") if n else ""
    node = {"id": -1, "name": body.host, "host": body.host.strip(), "adb_port": body.adb_port,
            "appium_url": (body.appium_url or "").strip().rstrip("/") or f"http://{body.host.strip()}:4723",
            "platform": body.platform, "agent_port": body.agent_port, "agent_token": token, "local": False}
    if not node["host"]:
        raise HTTPException(400, "Adres (IP) zorunlu")
    return await asyncio.to_thread(dnodes.test_node, node)


async def _stop_lease_work(holder: dict) -> list[str]:
    """Kirayı tutan işleri kapatır → yapılanların listesi."""
    from routers import ai_test_generator_router as ag
    done = []
    for l in holder.get("leases", []):
        try:
            if l["purpose"] == "session":
                await asyncio.to_thread(ag._quit_session, (holder["user_id"], "mobile"))
                done.append("oturum kapatıldı")
            elif l["purpose"] == "run" and l.get("ref"):
                try:
                    await ag.stop_execution(l["ref"], None)
                    done.append("koşum durduruldu")
                except HTTPException:
                    pass   # koşum zaten bitmiş
            elif l["purpose"] == "job" and l.get("ref"):
                from services import ai_job_service
                await asyncio.to_thread(ai_job_service.stop_run, int(l["ref"]))
                done.append("AI Job koşumu durduruldu")
        except Exception as e:
            done.append(f"{l['purpose']} kapatılamadı: {e}")
    return done


@router.post("/{device_id}/release")
async def pool_release(device_id: str, current_user: User = Depends(get_current_user)):
    h = leases.holder(device_id)
    if not h:
        return {"released": False, "message": "Telefon zaten boş"}
    if current_user.role != "admin" and h["user_id"] != current_user.id:
        raise HTTPException(403, f"Bu telefonu {h['display']} kullanıyor — yalnızca o kişi ya da yönetici boşa çıkarabilir.")
    done = await _stop_lease_work(h)
    leases.force_release(device_id)   # iş kapanırken bırakılmayan kira kalmasın
    who = "kendi" if h["user_id"] == current_user.id else f"{h['display']} kullanıcısının"
    print(f"[DEVICE-POOL] {current_user.username} → {device_id} boşa çıkarıldı ({who} kullanımı): {done}")
    return {"released": True, "previous_holder": h["display"], "actions": done}
