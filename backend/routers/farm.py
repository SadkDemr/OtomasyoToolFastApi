"""
Farm API Router - Uzak cihaz farm'ına bağlantı + iOS Desteği
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import requests
import asyncio
import base64
import subprocess
import os

router = APIRouter(prefix="/api/farm", tags=["farm"])


class FarmConfig(BaseModel):
    url: str
    username: str
    password: str
    appiumUrl: Optional[str] = None


class FarmConnectRequest(BaseModel):
    url: str
    username: str
    password: str
    appiumUrl: Optional[str] = None
    deviceId: str
    device: Optional[Dict[str, Any]] = None


class iOSServerConfig(BaseModel):
    """Mac sunucu ayarları"""
    host: str  # Mac IP adresi
    port: int = 4723  # Appium port
    username: Optional[str] = None
    password: Optional[str] = None


# Global state
farm_session = {
    "token": None,
    "config": None,
    "connected_device": None,
    "appium_session_id": None
}

ios_config = {
    "host": None,
    "port": 4723,
    "devices": []
}


# ============ iOS CİHAZ FONKSİYONLARI ============

def get_local_ios_devices() -> List[Dict]:
    """Yerel Mac'e bağlı iOS cihazları listele (Mac'te çalışır)"""
    devices = []
    
    try:
        # idevice_id komutu ile cihazları listele
        result = subprocess.run(
            ["idevice_id", "-l"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            udids = result.stdout.strip().split('\n')
            
            for udid in udids:
                if not udid:
                    continue
                    
                # Her cihaz için detay al
                device_info = get_ios_device_info(udid)
                if device_info:
                    devices.append(device_info)
                    
    except FileNotFoundError:
        print("[iOS] idevice_id bulunamadı. libimobiledevice yüklü mü?")
    except Exception as e:
        print(f"[iOS] Cihaz listesi hatası: {e}")
    
    return devices


def get_ios_device_info(udid: str) -> Optional[Dict]:
    """iOS cihaz detaylarını al"""
    try:
        result = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "DeviceName"],
            capture_output=True,
            text=True,
            timeout=5
        )
        device_name = result.stdout.strip() if result.returncode == 0 else "iPhone"
        
        result = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "ProductType"],
            capture_output=True,
            text=True,
            timeout=5
        )
        product_type = result.stdout.strip() if result.returncode == 0 else "iPhone"
        
        result = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "ProductVersion"],
            capture_output=True,
            text=True,
            timeout=5
        )
        ios_version = result.stdout.strip() if result.returncode == 0 else ""
        
        return {
            "id": udid,
            "device_id": udid,
            "name": device_name,
            "model": product_type,
            "platform": "ios",
            "platform_version": ios_version,
            "type": "physical",
            "status": "available",
            "os": "IOS"
        }
        
    except Exception as e:
        print(f"[iOS] Cihaz bilgisi hatası ({udid}): {e}")
        return None


@router.get("/ios/devices")
async def get_ios_devices():
    """Yerel iOS cihazları listele"""
    devices = get_local_ios_devices()
    return {
        "success": True,
        "devices": devices,
        "count": len(devices)
    }


@router.post("/ios/devices/remote")
async def get_remote_ios_devices(config: iOSServerConfig):
    """Uzak Mac sunucudaki iOS cihazları listele (SSH üzerinden)"""
    try:
        # SSH ile uzak Mac'teki cihazları sorgula
        if config.username:
            ssh_cmd = ["ssh", f"{config.username}@{config.host}", "idevice_id -l"]
        else:
            ssh_cmd = ["ssh", config.host, "idevice_id -l"]

        result = subprocess.run(
            ssh_cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        devices = []
        if result.returncode == 0:
            udids = result.stdout.strip().split('\n')
            
            for udid in udids:
                if udid:
                    devices.append({
                        "id": udid,
                        "device_id": udid,
                        "name": f"iPhone ({udid[:8]}...)",
                        "platform": "ios",
                        "type": "physical",
                        "status": "available",
                        "os": "IOS",
                        "remote_host": config.host,
                        "appium_url": f"http://{config.host}:{config.port}"
                    })
        
        ios_config["host"] = config.host
        ios_config["port"] = config.port
        ios_config["devices"] = devices
        
        return {
            "success": True,
            "devices": devices,
            "count": len(devices)
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "devices": []}


@router.post("/ios/connect")
async def connect_ios_device(device_id: str, host: str, port: int = 4723, bundle_id: Optional[str] = None):
    """iOS cihazına bağlan"""
    try:
        appium_url = f"http://{host}:{port}"
        
        capabilities = {
            "platformName": "iOS",
            "udid": device_id,
            "automationName": "XCUITest",
            "noReset": True,
            "newCommandTimeout": 300
        }
        
        if bundle_id:
            capabilities["bundleId"] = bundle_id
        
        response = requests.post(
            f"{appium_url}/session",
            json={"capabilities": {"alwaysMatch": capabilities}},
            timeout=60
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            session_id = data.get("value", {}).get("sessionId") or data.get("sessionId")
            
            ios_config["session_id"] = session_id
            ios_config["connected_device"] = device_id
            
            return {
                "success": True,
                "session_id": session_id,
                "appium_url": appium_url
            }
        else:
            return {"success": False, "error": f"Appium hatası: {response.status_code}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_farm_token(config: FarmConfig) -> str:
    """Farm'a login olup token al"""
    try:
        # Login endpoint'i (VFarm API formatı)
        login_url = f"{config.url}/api/auth/login"
        
        response = requests.post(
            login_url, 
            json={"username": config.username, "password": config.password},
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("token") or data.get("access_token") or data.get("accessToken")
        else:
            return None
            
    except Exception as e:
        print(f"[FARM] Login hatası: {e}")
        return None


def get_auth_headers(config: FarmConfig) -> dict:
    """Auth header'larını al"""
    token = get_farm_token(config)
    
    if token:
        farm_session["token"] = token
        return {"Authorization": f"Bearer {token}"}
    else:
        # Basic auth
        credentials = base64.b64encode(f"{config.username}:{config.password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}


@router.post("/test")
async def test_farm_connection(config: FarmConfig):
    """Farm bağlantısını test et"""
    try:
        headers = get_auth_headers(config)
        
        # Device list endpoint'i
        device_url = f"{config.url}/device-list"
        response = requests.get(device_url, headers=headers, verify=False, timeout=10)
        
        if response.status_code == 200:
            devices = response.json()
            return {
                "success": True,
                "device_count": len(devices) if isinstance(devices, list) else 0,
                "message": "Bağlantı başarılı"
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}"
            }
            
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Bağlantı kurulamadı"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Zaman aşımı"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/devices")
async def get_farm_devices(config: FarmConfig):
    """Farm'daki cihazları listele"""
    try:
        headers = get_auth_headers(config)
        farm_session["config"] = config.dict()
        
        # Device list endpoint'i
        device_url = f"{config.url}/device-list"
        response = requests.get(device_url, headers=headers, verify=False, timeout=15)
        
        if response.status_code == 200:
            devices = response.json()
            
            # Sadece ANDROID cihazları filtrele (şimdilik)
            android_devices = [d for d in devices if d.get("os") == "ANDROID"]
            
            return {
                "success": True,
                "devices": android_devices,
                "total": len(devices),
                "android_count": len(android_devices)
            }
        else:
            raise HTTPException(status_code=response.status_code, detail="Farm API hatası")
            
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Farm'a bağlanılamadı")
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Farm yanıt vermedi")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect")
async def connect_to_farm_device(request: FarmConnectRequest):
    """Farm cihazına Appium üzerinden bağlan"""
    try:
        farm_session["connected_device"] = request.device
        farm_session["config"] = {
            "url": request.url,
            "username": request.username,
            "password": request.password,
            "appiumUrl": request.appiumUrl
        }
        
        # Appium capabilities
        device = request.device or {}
        capabilities = {
            "platformName": device.get("os", "Android"),
            "platformVersion": device.get("oSVersion", ""),
            "deviceName": device.get("deviceModel", ""),
            "udid": request.deviceId,
            "automationName": "UiAutomator2",
            "noReset": True,
            "newCommandTimeout": 300
        }
        
        # Appium session başlatma isteği
        appium_url = request.appiumUrl or f"{request.url}:443/wd/hub"
        
        response = requests.post(
            f"{appium_url}/session",
            json={"capabilities": {"alwaysMatch": capabilities}},
            verify=False,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            session_id = data.get("value", {}).get("sessionId") or data.get("sessionId")
            farm_session["appium_session_id"] = session_id
            
            return {
                "success": True,
                "session_id": session_id,
                "message": "Farm cihazına bağlandı"
            }
        else:
            return {
                "success": False,
                "error": f"Appium session başlatılamadı: {response.status_code}"
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/status")
async def get_farm_status():
    """Farm bağlantı durumu"""
    return {
        "connected": farm_session.get("token") is not None or farm_session.get("config") is not None,
        "device": farm_session.get("connected_device"),
        "session_id": farm_session.get("appium_session_id")
    }


@router.websocket("/stream/{device_id}")
async def farm_device_stream(websocket: WebSocket, device_id: str):
    """Farm cihazından ekran görüntüsü stream'i"""
    await websocket.accept()
    
    try:
        config = farm_session.get("config")
        if not config:
            await websocket.send_json({"type": "error", "message": "Farm bağlantısı yok"})
            return
        
        appium_url = config.get("appiumUrl") or f"{config.get('url')}:443/wd/hub"
        session_id = farm_session.get("appium_session_id")
        
        if not session_id:
            await websocket.send_json({"type": "error", "message": "Appium session yok"})
            return
        
        while True:
            try:
                # Screenshot al
                response = requests.get(
                    f"{appium_url}/session/{session_id}/screenshot",
                    verify=False,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    screenshot = data.get("value", "")
                    
                    await websocket.send_json({
                        "type": "frame",
                        "image": screenshot
                    })
                
                await asyncio.sleep(0.5)  # 2 FPS
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"[FARM] Stream hatası: {e}")
                await asyncio.sleep(1)
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[FARM] WebSocket hatası: {e}")