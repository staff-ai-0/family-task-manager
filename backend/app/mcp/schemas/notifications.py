"""MCP create schema for the notifications domain."""

from typing import Optional

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    title: str
    body: Optional[str] = None
