"""
Git-Integrated Models
---------------------
Repository: Admin tarafından eklenen repo'lar (Azure Repos / GitHub)
UserWorkspace: Kullanıcıların clone'ladığı projeler
"""

from unittest.mock import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone


# ── Mevcut Base ve engine import edilecek ──
# from database import Base, engine


class Repository(Base):
    """
    Admin tarafından eklenen merkezi repo'lar.
    Örn: Mobil iOS, Mobil Android, Web, Desktop, API
    """
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    repo_url = Column(String(500), nullable=False)  # Azure Repos / GitHub URL
    repo_type = Column(String(50), nullable=False)  # mobile-ios, mobile-android, web, desktop, api
    description = Column(Text, nullable=True)
    
    # Git credentials (optional - admin sağlar)
    git_username = Column(String(100), nullable=True)
    git_token = Column(String(500), nullable=True)  # Encrypted olmalı production'da
    
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # İlişkiler
    creator = relationship("User", back_populates="created_repositories")
    workspaces = relationship("UserWorkspace", back_populates="repository", cascade="all, delete-orphan")


class UserWorkspace(Base):
    """
    Kullanıcının clone'ladığı repo'lar (workspace).
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


# ── User modeline eklenecek ilişkiler ──
# User.created_repositories = relationship("Repository", back_populates="creator")
# User.workspaces = relationship("UserWorkspace", back_populates="user")
