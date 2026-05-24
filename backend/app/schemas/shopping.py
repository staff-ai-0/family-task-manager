"""Shopping list Pydantic schemas (W1.4)."""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import FamilyEntityResponse, BaseResponse, EntityResponse


class ShoppingItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    qty: Optional[str] = Field(None, max_length=40)
    note: Optional[str] = Field(None, max_length=200)


class ShoppingItemCreate(ShoppingItemBase):
    pass


class ShoppingItemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    qty: Optional[str] = Field(None, max_length=40)
    note: Optional[str] = Field(None, max_length=200)
    is_checked: Optional[bool] = None


class ShoppingItemResponse(EntityResponse):
    list_id: UUID
    name: str
    qty: Optional[str] = None
    note: Optional[str] = None
    is_checked: bool
    added_by: Optional[UUID] = None
    checked_by: Optional[UUID] = None


class ShoppingListBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class ShoppingListCreate(ShoppingListBase):
    pass


class ShoppingListUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    is_archived: Optional[bool] = None


class ShoppingListResponse(FamilyEntityResponse):
    name: str
    is_archived: bool
    created_by: Optional[UUID] = None
    item_count: int = 0
    pending_count: int = 0


class ShoppingListDetailResponse(ShoppingListResponse):
    items: List[ShoppingItemResponse] = []
