"""A parent's reference photo for a chore ("this is what done looks like").

Per task template, at most MAX_BASELINES_PER_TEMPLATE rows. The AI proof
review compares a kid's photo against the newest ones (advisory only)."""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ChoreBaseline(Base):
    __tablename__ = "chore_baselines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String(512), nullable=False)
    caption = Column(String(120), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
