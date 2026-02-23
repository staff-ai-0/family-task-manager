from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    """User role enum"""
    PARENT = "parent"
    CHILD = "child"
    TEEN = "teen"


class User(Base):
    """User model"""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    name = Column(String(100), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.CHILD)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id"), nullable=False, index=True)
    points = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
    
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    family = relationship("Family", back_populates="members")
    # Legacy task relationships (to be removed after migration)
    assigned_tasks = relationship("Task", foreign_keys="Task.assigned_to", back_populates="assigned_user", cascade="all, delete-orphan")
    created_tasks = relationship("Task", foreign_keys="Task.created_by", back_populates="creator")
    # New template/assignment relationships
    created_templates = relationship("TaskTemplate", back_populates="creator", foreign_keys="TaskTemplate.created_by")
    task_assignments = relationship("TaskAssignment", back_populates="assigned_user", foreign_keys="TaskAssignment.assigned_to", cascade="all, delete-orphan")
    consequences = relationship("Consequence", back_populates="user", cascade="all, delete-orphan")
    point_transactions = relationship("PointTransaction", foreign_keys="PointTransaction.user_id", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, name={self.name}, role={self.role})>"
