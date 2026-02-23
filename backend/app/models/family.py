from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base


class Family(Base):
    """Family group model"""
    __tablename__ = "families"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)  # Nullable during creation, set after user created
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    members = relationship("User", back_populates="family")
    # Legacy task relationship (to be removed after migration)
    tasks = relationship("Task", back_populates="family", cascade="all, delete-orphan")
    # New template/assignment relationships
    task_templates = relationship("TaskTemplate", back_populates="family", cascade="all, delete-orphan")
    task_assignments = relationship("TaskAssignment", back_populates="family", cascade="all, delete-orphan")
    rewards = relationship("Reward", back_populates="family", cascade="all, delete-orphan")
    consequences = relationship("Consequence", back_populates="family", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Family(id={self.id}, name={self.name})>"
