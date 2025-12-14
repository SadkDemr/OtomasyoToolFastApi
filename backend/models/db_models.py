"""
Database Models - SQLAlchemy ORM Modelleri
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum


# ============ ENUMS ============

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class ScenarioType(str, enum.Enum):
    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"


class DeviceType(str, enum.Enum):
    EMULATOR = "emulator"
    PHYSICAL = "physical"


class DeviceOS(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"


class DeviceStatus(str, enum.Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    OFFLINE = "offline"


class TestStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"
    STOPPED = "stopped"


# ============ MODELS ============

class User(Base):
    """Kullanıcı tablosu"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), default=UserRole.USER.value)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # İlişkiler
    scenarios = relationship("Scenario", back_populates="owner")
    test_results = relationship("TestResult", back_populates="user")
    # Kullanıcının şu an kullandığı cihaz
    current_device = relationship("Device", back_populates="current_user", uselist=False)


class Scenario(Base):
    """Test senaryosu tablosu"""
    __tablename__ = "scenarios"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    type = Column(String(20), nullable=False)  # web, mobile, desktop
    
    # Test konfigürasyonu
    steps_json = Column(Text)  # JSON string - test adımları
    config_json = Column(Text)  # JSON string - url, app_package, vs.
    
    # Natural language formatında adımlar
    natural_steps = Column(Text)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # İlişkiler
    owner = relationship("User", back_populates="scenarios")
    test_results = relationship("TestResult", back_populates="scenario")


class Device(Base):
    """Cihaz tablosu (Emulator + Fiziksel)"""
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # "Samsung S21", "Pixel Emulator"
    device_id = Column(String(100), unique=True, nullable=False)  # UDID veya emulator-5554
    type = Column(String(20), nullable=False)  # emulator, physical
    os = Column(String(20), nullable=False)  # android, ios
    os_version = Column(String(20))
    
    # Appium bağlantı bilgileri
    appium_url = Column(String(200))  # http://localhost:4723/wd/hub
    
    # Durum
    status = Column(String(20), default=DeviceStatus.AVAILABLE.value)
    current_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # İlişkiler
    current_user = relationship("User", back_populates="current_device")
    test_results = relationship("TestResult", back_populates="device")


class TestResult(Base):
    """Test sonuçları tablosu"""
    __tablename__ = "test_results"
    
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)  # Mobil testler için
    
    status = Column(String(20), nullable=False)  # success, failed, running, stopped
    
    # Sonuç detayları (JSON)
    summary_json = Column(Text)  # {"total": 5, "passed": 4, "failed": 1}
    results_json = Column(Text)  # Adım adım sonuçlar
    
    duration = Column(Integer)  # Saniye cinsinden
    executed_at = Column(DateTime, server_default=func.now())
    
    # İlişkiler
    scenario = relationship("Scenario", back_populates="test_results")
    user = relationship("User", back_populates="test_results")
    device = relationship("Device", back_populates="test_results")
