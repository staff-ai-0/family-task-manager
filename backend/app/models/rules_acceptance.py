"""One row per (family, member, rules version): that person accepted the
family's chore rules. `snapshot` freezes the rules as shown at the time (what
they agreed to). family_id is in the key because an invitation can move an
existing account to another family, whose version numbers are its own."""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class RulesAcceptance(Base):
    __tablename__ = "rules_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "family_id", "user_id", "rules_version",
            name="uq_rules_acceptances_family_user_version",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rules_version = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
