"""
Database Models - FINAL ARCHITECTURE v2 (FIXED)
Includes: DeviceStatus Enum added to fix ImportError
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship, backref
from database import Base
from datetime import datetime
from enum import Enum as PyEnum

# --- ENUMS (HATAYI DUZELTEN KISIM) ---
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
    
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Iliskiler
    device_sessions = relationship("DeviceSession", back_populates="user")
    test_results = relationship("TestResult", back_populates="user")

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

# Ara Tablo
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