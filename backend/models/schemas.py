"""
Pydantic Schemas - Data Validation
FIXED: TestStep action field optional defaults added to prevent validation error
"""
from pydantic import BaseModel
from typing import Optional, List, ForwardRef, Dict, Any
from datetime import datetime
from enum import Enum

# --- ENUMS ---
class ScenarioType(str, Enum):
    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"

class InputType(str, Enum):
    NATURAL = "natural"
    JSON = "json"

class DeviceType(str, Enum):
    EMULATOR = "emulator"
    PHYSICAL = "physical"

# --- AUTH SCHEMAS ---
class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None

class UserRegister(UserBase):
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(UserBase):
    id: int
    role: str
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class TokenResponse(Token):
    pass

# --- FOLDER SCHEMAS ---
class FolderBase(BaseModel):
    name: str
    parent_id: Optional[int] = None

class FolderCreate(FolderBase):
    pass

FolderResponse = ForwardRef('FolderResponse')

class FolderResponse(FolderBase):
    id: int
    children: List[FolderResponse] = []
    class Config:
        from_attributes = True

FolderResponse.model_rebuild()

# --- SCENARIO SCHEMAS ---
class ScenarioBase(BaseModel):
    name: str
    description: Optional[str] = None
    type: ScenarioType
    folder_id: Optional[int] = None
    natural_steps: str
    config_json: Optional[str] = None

class ScenarioCreate(ScenarioBase):
    pass

class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[int] = None
    natural_steps: Optional[str] = None
    steps_json: Optional[str] = None
    config_json: Optional[str] = None

class ScenarioResponse(ScenarioBase):
    id: int
    user_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class ScenarioListResponse(BaseModel):
    total: int
    scenarios: List[ScenarioResponse]

# --- JOB SCHEMAS ---
class JobBase(BaseModel):
    name: str
    description: Optional[str] = None

class JobCreate(JobBase):
    scenario_ids: List[int] = []
    
    # GUNCELLEME: Senaryo detaylarini iceren yeni sema
class JobScenarioDetail(BaseModel):
    id: int
    name: str
    type: str
    class Config:
        from_attributes = True

class JobResponse(JobBase):
    id: int
    created_at: datetime
    # BURASI EKLENDI: Artik job icindeki senaryolari da donuyoruz
    scenarios: List[JobScenarioDetail] = [] 
    
    class Config:
        from_attributes = True

# --- COMMON TEST SCHEMAS ---
class StepResult(BaseModel):
    step_number: int
    action: str
    success: bool
    message: str
    error: Optional[str] = None

# --- FIX BURADA YAPILDI ---
class TestStep(BaseModel):
    action: str = ""  # <-- Zorunlu alan kaldirildi, default eklendi
    target: str = ""
    value: str = ""
    locator_type: str = "auto"

# --- WEB TEST SCHEMAS ---
class WebTestRequest(BaseModel):
    url: Optional[str] = None
    input_type: str = "natural"
    natural_text: str = ""
    steps: List[Dict[str, Any]] = []
    browser: str = "chrome"
    headless: bool = False
    stop_on_fail: bool = True

class WebTestResponse(BaseModel):
    test_id: str
    success: bool
    message: str
    results: List[StepResult]
    screenshot_path: Optional[str] = None

# --- MOBILE TEST SCHEMAS ---
class MobileTestRequest(BaseModel):
    device_id: str
    app_package: Optional[str] = ""
    app_activity: Optional[str] = ""
    input_type: str = "natural"
    natural_text: str = ""
    steps: List[Any] = []
    stop_on_fail: bool = True
    restart_app: bool = True

class MobileTestResponse(BaseModel):
    test_id: str
    success: bool
    message: str
    results: List[StepResult]

# --- DEVICE SCHEMAS ---
class DeviceBase(BaseModel):
    name: str
    device_id: str
    type: DeviceType
    os: str
    os_version: Optional[str] = None
    appium_url: Optional[str] = "http://localhost:4723"

class DeviceCreate(DeviceBase):
    pass

class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    appium_url: Optional[str] = None
    status: Optional[str] = None

class DeviceResponse(DeviceBase):
    id: int
    status: str
    current_user_id: Optional[int]
    class Config:
        from_attributes = True

class DeviceListResponse(BaseModel):
    devices: List[DeviceResponse]

class DeviceLockResponse(BaseModel):
    success: bool
    message: str
    device: Optional[DeviceResponse] = None