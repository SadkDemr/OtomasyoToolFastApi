"""
Pydantic Schemas - API request/response modelleri
"""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


# ========== AUTH ==========

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None


# Alias for backward compatibility
UserRegister = UserCreate


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str = "user"
    upload_only: bool = False

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ========== FOLDERS ==========

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


class FolderResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    children: List['FolderResponse'] = []
    
    class Config:
        from_attributes = True


# ========== SCENARIOS ==========

class ScenarioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = "web"  # web, mobile, desktop
    folder_id: Optional[int] = None
    natural_steps: Optional[str] = None
    steps_json: Optional[str] = None
    config_json: Optional[str] = None
    tags: Optional[str] = None


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    folder_id: Optional[int] = None
    natural_steps: Optional[str] = None
    steps_json: Optional[str] = None
    config_json: Optional[str] = None
    tags: Optional[str] = None


class ScenarioResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    type: str = "web"
    folder_id: Optional[int] = None
    natural_steps: Optional[str] = None
    steps_json: Optional[str] = None
    config_json: Optional[str] = None
    tags: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ScenarioListResponse(BaseModel):
    total: int
    scenarios: List[ScenarioResponse]


# ========== DEVICES ==========

class DeviceCreate(BaseModel):
    name: str
    device_id: str
    type: str = "physical"  # physical, emulator
    platform: str = "android"
    appium_url: Optional[str] = "http://localhost:4723"


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    appium_url: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    device_id: str
    type: str = "physical"
    platform: Optional[str] = "android"
    status: str = "available"
    appium_url: Optional[str] = None
    locked_by: Optional[int] = None
    current_user_id: Optional[int] = None
    
    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    total: int
    devices: List[DeviceResponse]


class DeviceLockResponse(BaseModel):
    success: bool
    message: str
    device: Optional[DeviceResponse] = None


# ========== TEST STEPS & RESULTS ==========

class TestStep(BaseModel):
    """Test adımı"""
    action: str = ""
    target: str = ""
    value: str = ""
    locator_type: str = "auto"
    timeout: int = 10
    optional: bool = False


class StepResult(BaseModel):
    """Adım sonucu"""
    step_number: int
    action: str
    success: bool
    message: str = ""
    screenshot: Optional[str] = None
    duration: float = 0


# ========== JOBS ==========

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InputType(str, Enum):
    NATURAL = "natural"
    STEPS = "steps"


class JobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    scenario_ids: List[int] = []
    device_ids: List[int] = []
    config_json: Optional[str] = None


class JobResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    # status db'de yoktu ama frontend istiyor, dinamik hesaplayacagiz veya varsayilan donecegiz
    status: str = "pending" 
    created_at: Optional[datetime] = None
    
    # EKLENEN ALANLAR (Sayılar için):
    scenario_count: int = 0
    device_count: int = 0
    
    @model_validator(mode='before')
    @classmethod
    def calculate_counts(cls, v: Any) -> Any:
        # v bir SQLAlchemy Job objesidir
        if hasattr(v, 'scenarios'):
            # JobScenario tablosundan sayıyı al
            v.scenario_count = len(v.scenarios)
        if hasattr(v, 'associated_devices'):
            # JobDevice tablosundan sayıyı al
            v.device_count = len(v.associated_devices)
        return v

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    total: int
    jobs: List[JobResponse]


# ========== MOBILE TEST ==========

class MobileTestRequest(BaseModel):
    device_id: str
    app_package: str = ""
    app_activity: str = ""
    input_type: str = "natural"  # natural | steps
    natural_text: str = ""
    steps: List[TestStep] = []
    stop_on_fail: bool = True
    restart_app: bool = True
    # Görüntü işleme / AI
    use_vision: bool = True        # Python görüntü işleme ile fallback
    use_llm: bool = False          # LLM (Gemini) ile görüntü analizi


class MobileTestResponse(BaseModel):
    test_id: str
    success: bool
    message: str
    summary: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = []
    duration: float = 0


# ========== WEB TEST ==========

class WebTestRequest(BaseModel):
    url: str = ""
    input_type: str = "natural"
    natural_text: str = ""
    steps: List[TestStep] = []
    headless: bool = False
    stop_on_fail: bool = True


class WebTestResponse(BaseModel):
    test_id: str
    success: bool
    message: str
    summary: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = []
    duration: float = 0


# ========== STATS ==========

class DashboardStats(BaseModel):
    total_scenarios: int = 0
    total_devices: int = 0
    total_jobs: int = 0
    success_rate: float = 0
    recent_jobs: List[JobResponse] = []


# ========================================================================
# GIT INTEGRATION SCHEMAS
# ========================================================================

# ========== REPOSITORIES (Admin) ==========

class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Örn: Mobil iOS Testleri")
    repo_url: str = Field(..., description="Azure Repos / GitHub URL")
    repo_type: str = Field(..., description="mobile-ios | mobile-android | web | desktop | api")
    description: Optional[str] = Field(default="", max_length=500)
    git_username: Optional[str] = None
    git_token: Optional[str] = None


class RepositoryUpdate(BaseModel):
    name: Optional[str] = None
    repo_url: Optional[str] = None
    description: Optional[str] = None
    git_username: Optional[str] = None
    git_token: Optional[str] = None


class RepositoryResponse(BaseModel):
    id: int
    name: str
    repo_url: str
    repo_type: str
    description: str
    created_by: int
    created_at: datetime
    workspace_count: int = 0  # Kaç kullanıcı clone'ladı
    
    class Config:
        from_attributes = True


class RepositoryListResponse(BaseModel):
    repositories: List[RepositoryResponse]


# ========== WORKSPACES (User) ==========

class CloneRequest(BaseModel):
    repository_id: int = Field(..., description="Clone edilecek repository ID")


class CommitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=200, description="Commit mesajı")


class WorkspaceResponse(BaseModel):
    id: int
    repository_id: int
    repository_name: str
    repository_type: str
    branch_name: str
    is_cloned: bool
    has_changes: bool
    cloned_at: Optional[datetime]
    last_pulled: Optional[datetime]
    last_pushed: Optional[datetime]
    
    class Config:
        from_attributes = True


class WorkspaceListResponse(BaseModel):
    workspaces: List[WorkspaceResponse]


class CatalogItemResponse(BaseModel):
    id: int
    name: str
    repo_url: str
    repo_type: str
    description: str
    is_cloned_by_me: bool
    my_workspace_id: Optional[int]
    my_branch: Optional[str]
    has_changes: bool


class CatalogResponse(BaseModel):
    catalog: List[CatalogItemResponse]


class GitStatusResponse(BaseModel):
    is_cloned: bool
    branch: Optional[str]
    has_changes: bool = False
    changed_files: List[str] = []
    untracked_files: List[str] = []
    total_changes: int = 0
    message: Optional[str] = None


class PullResponse(BaseModel):
    success: bool
    message: str
    has_conflicts: bool


class CommitHistoryResponse(BaseModel):
    commits: List[Dict[str, str]]  # hash, author, date, message