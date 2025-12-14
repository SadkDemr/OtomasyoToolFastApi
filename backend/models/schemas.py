"""
Pydantic Schemas - API Request/Response Modelleri
"""

from pydantic import BaseModel, EmailStr, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


# ============ ENUMS ============

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class ScenarioType(str, Enum):
    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"


class DeviceType(str, Enum):
    EMULATOR = "emulator"
    PHYSICAL = "physical"


class DeviceOS(str, Enum):
    ANDROID = "android"
    IOS = "ios"


class DeviceStatus(str, Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    OFFLINE = "offline"


class TestStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"
    STOPPED = "stopped"


class InputType(str, Enum):
    NATURAL = "natural"
    COMMANDS = "commands"


# ============ AUTH SCHEMAS ============

class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============ SCENARIO SCHEMAS ============

class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    type: ScenarioType
    natural_steps: Optional[str] = None  # Dogal dil adimlari
    steps_json: Optional[str] = None  # JSON formatinda adimlar
    config_json: Optional[str] = None  # url, app_package vs.


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    natural_steps: Optional[str] = None
    steps_json: Optional[str] = None
    config_json: Optional[str] = None


class ScenarioResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str]
    type: str
    natural_steps: Optional[str]
    steps_json: Optional[str]
    config_json: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ScenarioListResponse(BaseModel):
    total: int
    scenarios: List[ScenarioResponse]


# ============ DEVICE SCHEMAS ============

class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    device_id: str = Field(..., min_length=1)  # UDID veya emulator-5554
    type: DeviceType
    os: DeviceOS
    os_version: Optional[str] = None
    appium_url: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    os_version: Optional[str] = None
    appium_url: Optional[str] = None
    status: Optional[DeviceStatus] = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    device_id: str
    type: str
    os: str
    os_version: Optional[str]
    appium_url: Optional[str]
    status: str
    current_user_id: Optional[int]
    current_user_name: Optional[str] = None  # Kullanici adi
    locked_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    total: int
    available: int
    in_use: int
    devices: List[DeviceResponse]


class DeviceLockResponse(BaseModel):
    success: bool
    message: str
    device: Optional[DeviceResponse]


# ============ TEST SCHEMAS ============

class TestStep(BaseModel):
    action: str = ""
    target: str = ""
    value: str = ""
    locator_type: str = "auto"


class StepResult(BaseModel):
    step_number: int = 0
    total_steps: int = 0
    action: str = ""
    target: str = ""
    value: str = ""
    original: str = ""
    success: bool = True
    message: str = ""
    error: Optional[str] = None
    screenshot: Optional[str] = None


# Web Test
class WebTestRequest(BaseModel):
    url: str
    input_type: InputType = InputType.NATURAL
    natural_text: Optional[str] = None
    steps: Optional[List[TestStep]] = None
    headless: bool = False
    stop_on_fail: bool = True
    scenario_id: Optional[int] = None  # Kaydedilmis senaryo


class WebTestResponse(BaseModel):
    test_id: str = ""
    success: bool = False
    message: str = ""
    summary: Optional[Dict[str, Any]] = None
    results: List[StepResult] = []
    duration: Optional[float] = None


# Mobile Test
class MobileTestRequest(BaseModel):
    device_id: int  # DB'deki device ID
    app_package: str = ""
    app_activity: str = ""
    input_type: InputType = InputType.NATURAL
    natural_text: Optional[str] = None
    steps: Optional[List[TestStep]] = None
    stop_on_fail: bool = True
    scenario_id: Optional[int] = None


class MobileTestResponse(BaseModel):
    test_id: str = ""
    success: bool = False
    message: str = ""
    device: Optional[DeviceResponse] = None
    summary: Optional[Dict[str, Any]] = None
    results: List[StepResult] = []
    duration: Optional[float] = None


# ============ TEST RESULT SCHEMAS ============

class TestResultResponse(BaseModel):
    id: int
    scenario_id: int
    scenario_name: Optional[str] = None
    user_id: int
    device_id: Optional[int]
    device_name: Optional[str] = None
    status: str
    summary_json: Optional[str]
    results_json: Optional[str]
    duration: Optional[int]
    executed_at: datetime
    
    class Config:
        from_attributes = True


class TestResultListResponse(BaseModel):
    total: int
    results: List[TestResultResponse]
