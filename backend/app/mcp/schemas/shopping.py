"""MCP create/update schemas for the shopping domain."""

from typing import Optional

from pydantic import BaseModel


class ItemCreate(BaseModel):
    name: str
    qty: Optional[str] = None


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    qty: Optional[str] = None
