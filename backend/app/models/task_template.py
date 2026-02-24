"""
TaskTemplate model

Represents reusable task/chore definitions that can be assigned weekly.
Templates are permanent and family-scoped. They define WHAT needs to be done,
while TaskAssignment defines WHO does it and WHEN.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base


class TaskTemplate(Base):
    """Reusable task template for weekly assignment generation"""

    __tablename__ = "task_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    title_es = Column(String(200), nullable=True)
    description_es = Column(Text, nullable=True)
    points = Column(Integer, nullable=False, default=10)

    # Scheduling: how often per week (1=daily, 3=every 3 days, 7=weekly)
    interval_days = Column(Integer, nullable=False, default=1)

    # Classification
    is_bonus = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Ownership
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Metadata
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    creator = relationship("User", back_populates="created_templates", foreign_keys=[created_by])
    family = relationship("Family", back_populates="task_templates")
    assignments = relationship(
        "TaskAssignment", back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<TaskTemplate(id={self.id}, title='{self.title}', interval={self.interval_days}d, bonus={self.is_bonus})>"

    @property
    def frequency_label(self) -> str:
        """Human-readable frequency label"""
        if self.interval_days == 1:
            return "daily"
        elif self.interval_days == 7:
            return "weekly"
        else:
            return f"every {self.interval_days} days"
