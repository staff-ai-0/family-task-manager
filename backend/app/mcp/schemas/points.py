"""
MCP pydantic schemas for points-domain entities.

These are the MCP-facing create/update schemas — deliberately minimal
(no family_id, no read-only fields). The adapters translate these to the
real app service schemas before calling into the service layer.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── ledger (read-only; list + get only) ───────────────────────────────────

# No create/update schemas needed for ledger — it is read-only via MCP.
# Use dict as placeholder in the EntitySpec.


# ── adjust (parent adjustment; create is a money-moving op) ───────────────

class AdjustCreate(BaseModel):
    """Schema for creating a parent point adjustment via MCP."""
    user_id: UUID
    points: int = Field(..., ge=-1000, le=1000)
    reason: str = Field(..., min_length=1, max_length=500)


# ── transfer (point transfer; create is a money-moving op) ────────────────

class TransferCreate(BaseModel):
    """Schema for creating a point transfer via MCP."""
    from_user_id: UUID
    to_user_id: UUID
    points: int = Field(..., ge=1, le=1000)
    reason: Optional[str] = Field(None, max_length=500)
