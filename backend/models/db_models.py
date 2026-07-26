"""
Database Models - FINAL VERSION + GIT INTEGRATION + ADVANCED EDITOR
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship, backref
from database import Base
from datetime import datetime
from enum import Enum as PyEnum

# --- ENUMS ---
class DeviceStatus(str, PyEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"
    LOCKED = "locked"

# --- KULLANICI & YETKI ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String, nullable=True)
    role = Column(String, default="user") # admin, user
    upload_only = Column(Boolean, default=False)  # True ise login sonrasi sadece dosya yukleme sayfasi gorunur

    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Iliskiler
    device_sessions = relationship("DeviceSession", back_populates="user")
    test_results = relationship("TestResult", back_populates="user")
    
    # Git integration ilişkileri
    created_repositories = relationship("Repository", back_populates="creator")
    workspaces = relationship("UserWorkspace", back_populates="user")

# --- DOSYA YUKLEME (Genel) ---
class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"))
    original_filename = Column(String)
    stored_filename    = Column(String)   # disk uzerindeki uuid tabanli ad
    file_type         = Column(String)    # "image" | "video"
    mime_type         = Column(String)    # imza kontrolunden tespit edilen gercek tip
    size_bytes        = Column(Integer)
    note              = Column(Text, nullable=True)
    uploaded_at       = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

# --- KLASOR YAPISI (AGAC) ---
class Folder(Base):
    __tablename__ = "folders"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    
    children = relationship("Folder", 
                          backref=backref('parent', remote_side=[id]),
                          cascade="all, delete-orphan")
    
    scenarios = relationship("Scenario", back_populates="folder", cascade="all, delete-orphan")

# --- SENARYOLAR ---
class Scenario(Base):
    __tablename__ = "scenarios"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    type = Column(String) # web, mobile
    natural_steps = Column(Text)
    steps_json = Column(Text, nullable=True)
    config_json = Column(Text, nullable=True)
    
    is_active = Column(Boolean, default=True) 
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    folder = relationship("Folder", back_populates="scenarios")
    job_associations = relationship("JobScenario", back_populates="scenario", cascade="all, delete-orphan")

# --- JOB CIHAZ ILISKISI (YENI TABLO) ---
class JobDevice(Base):
    __tablename__ = "job_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    
    job = relationship("Job", back_populates="associated_devices")
    device = relationship("Device")

# --- JOB (TEST PAKETLERI) ---
class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    scenarios = relationship("JobScenario", back_populates="job", cascade="all, delete-orphan")
    executions = relationship("JobExecution", back_populates="job", cascade="all, delete-orphan")
    
    # YENI EKLENEN ILISKI:
    associated_devices = relationship("JobDevice", back_populates="job", cascade="all, delete-orphan")

# --- JOB SENARYO ARA TABLO ---
class JobScenario(Base):
    __tablename__ = "job_scenarios"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    order = Column(Integer, default=0)
    
    job = relationship("Job", back_populates="scenarios")
    scenario = relationship("Scenario", back_populates="job_associations")

# --- JOB EXECUTIONS ---
class JobExecution(Base):
    __tablename__ = "job_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    status = Column(String, default="pending")
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    
    total_tests = Column(Integer, default=0)
    passed_tests = Column(Integer, default=0)
    failed_tests = Column(Integer, default=0)
    
    job = relationship("Job", back_populates="executions")
    results = relationship("TestResult", back_populates="job_execution")

# --- TEST SONUCLARI ---
class TestResult(Base):
    __tablename__ = "test_results"
    
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    job_execution_id = Column(Integer, ForeignKey("job_executions.id"), nullable=True)
    
    device_name = Column(String, nullable=True)
    status = Column(String) # success, failed
    log_json = Column(Text)
    screenshot_path = Column(String, nullable=True)
    
    executed_at = Column(DateTime, default=datetime.utcnow)
    duration_seconds = Column(Integer, default=0)
    
    job_execution = relationship("JobExecution", back_populates="results")
    user = relationship("User", back_populates="test_results")

# --- CIHAZLAR ---
class Device(Base):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    device_id = Column(String, unique=True, index=True) # UDID
    type = Column(String) # emulator, physical
    os = Column(String) # android, ios
    os_version = Column(String, nullable=True)
    status = Column(String, default=DeviceStatus.AVAILABLE.value) # Enum kullanildi
    appium_url = Column(String, default="http://localhost:4723")
    
    current_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    sessions = relationship("DeviceSession", back_populates="device")

# --- CIHAZ OTURUMLARI ---
class DeviceSession(Base):
    __tablename__ = "device_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    
    session_type = Column(String, default="manual") # manual, automated
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    
    user = relationship("User", back_populates="device_sessions")
    device = relationship("Device", back_populates="sessions")


# ========================================================================
# GIT INTEGRATION MODELS + ADVANCED EDITOR
# ========================================================================

class Repository(Base):
    """
    Admin tarafından eklenen Git repository'ler (Azure Repos / GitHub).
    Örn: Mobil iOS, Mobil Android, Web, Desktop, API
    """
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    repo_url = Column(String(500), nullable=False)
    repo_type = Column(String(50), nullable=False)  # mobile-ios, mobile-android, web, desktop, web-desktop, api
    description = Column(Text, nullable=True)

    # Editor type: "normal" (web-only, text-based) veya "advanced" (desktop/web-desktop, image-based)
    editor_type = Column(String(20), nullable=False, default="normal")  # normal, advanced

    # Git provider: azure, github, generic
    provider = Column(String(20), nullable=False, default="generic")

    # Git credentials (optional - admin sağlar)
    git_username = Column(String(100), nullable=True)
    git_token = Column(String(500), nullable=True)  # ⚠️ Production'da encrypt et!

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # İlişkiler
    creator = relationship("User", back_populates="created_repositories")
    workspaces = relationship("UserWorkspace", back_populates="repository", cascade="all, delete-orphan")
    user_permissions = relationship("UserProjectPermission", back_populates="repository", cascade="all, delete-orphan")


class UserProjectPermission(Base):
    """
    Admin tarafından kullanıcılara verilen proje (repo) bazlı yetkiler.
    view: Senaryoları görüntüleme + çalıştırma
    edit: Görüntüleme + kendi workspace'ine kopyalayıp düzenleme
    """
    __tablename__ = "user_project_permissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    permission = Column(String(20), nullable=False, default="view")  # view, edit
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id], backref="project_permissions")
    repository = relationship("Repository", back_populates="user_permissions")
    grantor = relationship("User", foreign_keys=[granted_by])


class ScenarioSharePermission(Base):
    """
    Admin tarafından verilen kullanıcılar arası senaryo erişim yetkisi.
    Örn: Admin, Engin'e Sadık'ın senaryolarını görme+koşma yetkisi verir.
    permission: view_run | view_edit_run
    """
    __tablename__ = "scenario_share_permissions"

    id              = Column(Integer, primary_key=True, index=True)
    granted_by      = Column(Integer, ForeignKey("users.id"), nullable=False)
    grantee_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # yetkiyi alan
    owner_user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)  # senaryosu paylaşılan
    permission      = Column(String(20), nullable=False, default="view_run")   # view_run | view_edit_run
    granted_at      = Column(DateTime, default=datetime.utcnow)

    grantor  = relationship("User", foreign_keys=[granted_by])
    grantee  = relationship("User", foreign_keys=[grantee_user_id])
    owner    = relationship("User", foreign_keys=[owner_user_id])


class UserWorkspace(Base):
    """
    Kullanıcının clone'ladığı repository'ler (workspace).
    Her kullanıcı kendi branch'inde çalışır: user-{username}
    """
    __tablename__ = "user_workspaces"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    
    # Lokal path: /workspaces/{user_id}/{repo_name}/
    local_path = Column(String(500), nullable=False)
    
    # Branch bilgisi: user-{username}
    branch_name = Column(String(100), nullable=False)
    
    # Durum
    is_cloned = Column(Boolean, default=False)
    has_changes = Column(Boolean, default=False)  # git status --porcelain sonucu
    
    # Timestamps
    cloned_at = Column(DateTime, nullable=True)
    last_pulled = Column(DateTime, nullable=True)
    last_pushed = Column(DateTime, nullable=True)
    
    # İlişkiler
    user = relationship("User", back_populates="workspaces")
    repository = relationship("Repository", back_populates="workspaces")


# --- AI TEST GENERATOR: JOB SISTEMI (Faz 1: Mobil) ---
class AiJob(Base):
    __tablename__ = "ai_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, index=True)
    platform = Column(String, default="mobile")
    created_at = Column(DateTime, default=datetime.utcnow)

    scenarios = relationship("AiJobScenario", back_populates="job", cascade="all, delete-orphan")
    devices   = relationship("AiJobDevice",   back_populates="job", cascade="all, delete-orphan")
    schedule  = relationship("AiJobSchedule", back_populates="job", cascade="all, delete-orphan")
    runs      = relationship("AiJobRun",      back_populates="job", cascade="all, delete-orphan")


class AiJobScenario(Base):
    __tablename__ = "ai_job_scenarios"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    scenario_folder = Column(String)

    job = relationship("AiJob", back_populates="scenarios")


class AiJobDevice(Base):
    __tablename__ = "ai_job_devices"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    device_id = Column(String)
    device_name = Column(String, nullable=True)

    job = relationship("AiJob", back_populates="devices")


class AiJobSchedule(Base):
    __tablename__ = "ai_job_schedules"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    schedule_type = Column(String)  # 'once' | 'daily' | 'weekly'
    run_at = Column(DateTime)
    enabled = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)

    job = relationship("AiJob", back_populates="schedule")


class AiJobRun(Base):
    __tablename__ = "ai_job_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")       # running | completed | interrupted
    trigger_type = Column(String, default="manual")  # manual | scheduled
    total_cells = Column(Integer, default=0)
    passed_cells = Column(Integer, default=0)
    failed_cells = Column(Integer, default=0)

    job = relationship("AiJob", back_populates="runs")
    results = relationship("AiJobRunResult", back_populates="job_run", cascade="all, delete-orphan")


class AiJobRunResult(Base):
    __tablename__ = "ai_job_run_results"

    id = Column(Integer, primary_key=True, index=True)
    job_run_id = Column(Integer, ForeignKey("ai_job_runs.id"))
    scenario_folder = Column(String)
    scenario_name = Column(String, nullable=True)
    device_id = Column(String)
    device_name = Column(String, nullable=True)
    status = Column(String, default="queued")  # queued | running | pass | fail | error
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    log_json = Column(Text, nullable=True)

    job_run = relationship("AiJobRun", back_populates="results")