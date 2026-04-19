"""
Advanced Scenario Models - Desktop/Web-Desktop Automation
----------------------------------------------------------
Image-based automation için Pydantic models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ActionType(str, Enum):
    """Automation action türleri"""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    WAIT = "wait"
    ASSERT_EXISTS = "assert_exists"
    LAUNCH_APP = "launch_app"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    MANUAL = "manual"  # Manuel adım


class StrategyType(str, Enum):
    """Element bulma stratejisi"""
    IMAGE = "image"  # Desktop - Screenshot matching
    LOCATOR = "locator"  # Web - CSS/XPath
    OCR = "ocr"  # Text recognition
    COORDINATE = "coordinate"  # X,Y koordinat


class ImageData(BaseModel):
    """Embedded image verisi"""
    name: str = Field(..., description="Image dosya adı (örn: login_button.png)")
    data: str = Field(..., description="Base64 encoded image data")
    format: str = Field(default="png", description="Image formatı (png, jpg)")
    width: int = Field(..., description="Resize edilmiş genişlik")
    height: int = Field(..., description="Resize edilmiş yükseklik")
    original_width: Optional[int] = Field(None, description="Orijinal genişlik")
    original_height: Optional[int] = Field(None, description="Orijinal yükseklik")
    size_kb: float = Field(..., description="Dosya boyutu (KB)")
    captured_at: Optional[str] = Field(None, description="Çekim zamanı (ISO format)")


class LocatorData(BaseModel):
    """Web locator verisi"""
    type: str = Field(..., description="Locator tipi: id, xpath, css, name, class")
    value: str = Field(..., description="Locator değeri")


class StepParams(BaseModel):
    """Adım parametreleri"""
    text: Optional[str] = Field(None, description="Yazılacak metin")
    url: Optional[str] = Field(None, description="Açılacak URL")
    seconds: Optional[float] = Field(None, description="Bekleme süresi (saniye)")
    timeout: Optional[int] = Field(default=10, description="Element arama timeout (saniye)")
    confidence: Optional[float] = Field(default=0.85, description="Image matching confidence (0.0-1.0)")
    button: Optional[str] = Field(default="left", description="Mouse butonu: left, right, middle")
    key: Optional[str] = Field(None, description="Basılacak tuş (enter, tab, esc, vb)")
    scroll_amount: Optional[int] = Field(None, description="Scroll miktarı (px)")
    x: Optional[int] = Field(None, description="X koordinatı")
    y: Optional[int] = Field(None, description="Y koordinatı")


class ScenarioStep(BaseModel):
    """Scenario adımı - image veya locator based"""
    id: str = Field(..., description="Unique step ID (step_1234567890)")
    action: ActionType = Field(..., description="Action türü")
    strategy: StrategyType = Field(..., description="Element bulma stratejisi")
    description: str = Field(..., description="Adım açıklaması (user-friendly)")
    
    # Image-based (desktop)
    image: Optional[ImageData] = Field(None, description="Screenshot data (base64 embedded)")
    
    # Locator-based (web)
    locator: Optional[LocatorData] = Field(None, description="Web element locator")
    
    # Parametreler
    params: Optional[StepParams] = Field(default_factory=StepParams, description="Adım parametreleri")
    
    # Metadata
    created_at: Optional[str] = Field(None, description="Oluşturulma zamanı")
    updated_at: Optional[str] = Field(None, description="Güncellenme zamanı")
    order: int = Field(default=0, description="Adım sırası")


class ScenarioConfig(BaseModel):
    """Scenario konfigürasyonu"""
    app_path: Optional[str] = Field(None, description="Desktop app path (örn: C:\\Program Files\\MyApp\\app.exe)")
    base_url: Optional[str] = Field(None, description="Web base URL")
    package_name: Optional[str] = Field(None, description="Mobile package name")
    timeout: int = Field(default=30, description="Global timeout (saniye)")
    action_delay: float = Field(default=0.5, description="Adımlar arası bekleme (saniye)")
    retry_count: int = Field(default=3, description="Başarısız adım retry sayısı")
    screenshot_on_error: bool = Field(default=True, description="Hata durumunda screenshot al")


class ScenarioAssets(BaseModel):
    """Scenario asset istatistikleri"""
    total_images: int = Field(default=0, description="Toplam image sayısı")
    total_size_kb: float = Field(default=0.0, description="Toplam boyut (KB)")
    compressed: bool = Field(default=False, description="GZIP ile sıkıştırılmış mı")


class AdvancedScenario(BaseModel):
    """Advanced scenario - image-based automation"""
    id: int = Field(..., description="Scenario ID (timestamp)")
    name: str = Field(..., description="Scenario adı")
    description: Optional[str] = Field(None, description="Açıklama")
    type: str = Field(..., description="Scenario türü: desktop, web, web-desktop, mobile")
    
    # Adımlar
    steps: List[ScenarioStep] = Field(default_factory=list, description="Scenario adımları")
    
    # Konfigürasyon
    config_json: Optional[ScenarioConfig] = Field(None, description="Scenario config")
    
    # Assets
    assets: Optional[ScenarioAssets] = Field(default_factory=ScenarioAssets, description="Asset istatistikleri")
    
    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Ekstra metadata")
    tags: List[str] = Field(default_factory=list, description="Etiketler")
    
    # Timestamps
    created_at: Optional[str] = Field(None, description="Oluşturulma zamanı")
    updated_at: Optional[str] = Field(None, description="Güncellenme zamanı")
    created_by: Optional[int] = Field(None, description="Oluşturan user ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1234567890,
                "name": "Desktop_Login_Test",
                "description": "Desktop uygulamasına giriş testi",
                "type": "desktop",
                "steps": [
                    {
                        "id": "step_1234567890",
                        "action": "click",
                        "strategy": "image",
                        "description": "Login butonuna tıkla",
                        "image": {
                            "name": "login_button.png",
                            "data": "iVBORw0KGgo...",
                            "format": "png",
                            "width": 200,
                            "height": 50,
                            "size_kb": 15.2
                        },
                        "params": {
                            "confidence": 0.85,
                            "timeout": 10
                        }
                    }
                ],
                "config_json": {
                    "app_path": "C:\\Program Files\\MyApp\\app.exe",
                    "timeout": 30,
                    "action_delay": 0.5
                },
                "assets": {
                    "total_images": 5,
                    "total_size_kb": 150.5
                }
            }
        }


# Helper functions

def create_click_step(
    step_id: str,
    description: str,
    image_data: ImageData,
    confidence: float = 0.85
) -> ScenarioStep:
    """Click step oluştur"""
    return ScenarioStep(
        id=step_id,
        action=ActionType.CLICK,
        strategy=StrategyType.IMAGE,
        description=description,
        image=image_data,
        params=StepParams(confidence=confidence),
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )


def create_type_step(
    step_id: str,
    description: str,
    text: str,
    image_data: Optional[ImageData] = None
) -> ScenarioStep:
    """Type step oluştur"""
    return ScenarioStep(
        id=step_id,
        action=ActionType.TYPE,
        strategy=StrategyType.IMAGE if image_data else StrategyType.COORDINATE,
        description=description,
        image=image_data,
        params=StepParams(text=text),
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )


def create_wait_step(
    step_id: str,
    description: str,
    seconds: float
) -> ScenarioStep:
    """Wait step oluştur"""
    return ScenarioStep(
        id=step_id,
        action=ActionType.WAIT,
        strategy=StrategyType.COORDINATE,
        description=description,
        params=StepParams(seconds=seconds),
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )


def create_manual_step(
    step_id: str,
    description: str
) -> ScenarioStep:
    """Manuel step oluştur"""
    return ScenarioStep(
        id=step_id,
        action=ActionType.MANUAL,
        strategy=StrategyType.COORDINATE,
        description=description,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )
