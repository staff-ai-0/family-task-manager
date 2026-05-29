"""Pydantic schemas for the per-family a2a webhook."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class A2AWebhookRead(BaseModel):
    url: Optional[str] = None
    enabled: bool = False
    last_success_at: Optional[datetime] = None
    failure_count: int = 0
    # secret is intentionally NOT exposed here

    model_config = ConfigDict(from_attributes=True)


class A2AWebhookUpdate(BaseModel):
    url: str = Field(..., description="HTTPS endpoint to POST receipt events to")
    enabled: bool = False
    rotate_secret: bool = False

    @field_validator("url")
    @classmethod
    def must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("webhook URL must use https://")
        # Pydantic HttpUrl validates the rest
        HttpUrl(v)
        return v


class A2AWebhookSaveResult(BaseModel):
    config: A2AWebhookRead
    secret: Optional[str] = Field(
        None,
        description="Plaintext secret. Returned ONLY when rotate_secret=true on save.",
    )
