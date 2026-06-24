"""MCP create/update schemas for the shopping domain."""

from typing import Optional

from pydantic import BaseModel


# ── ShoppingList ──────────────────────────────────────────────────────────────


class ListCreate(BaseModel):
    name: str


class ListUpdate(BaseModel):
    name: Optional[str] = None
    is_archived: Optional[bool] = None


# ── ShoppingItem ──────────────────────────────────────────────────────────────


class ItemCreate(BaseModel):
    name: str
    qty: Optional[str] = None


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    qty: Optional[str] = None
    is_checked: Optional[bool] = None
