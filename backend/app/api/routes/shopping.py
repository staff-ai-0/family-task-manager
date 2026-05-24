"""Shopping list routes (W1.4).

All endpoints family-scoped. Any active member can read and write — the
shopping list is shared, so parents and kids see the same items.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemResponse,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListDetailResponse,
    ShoppingListResponse,
    ShoppingListUpdate,
)
from app.services.shopping_service import ShoppingService


router = APIRouter()


def _to_list_response(obj, item_count: int, pending_count: int) -> ShoppingListResponse:
    return ShoppingListResponse(
        id=obj.id,
        family_id=obj.family_id,
        name=obj.name,
        is_archived=obj.is_archived,
        created_by=obj.created_by,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        item_count=item_count,
        pending_count=pending_count,
    )


@router.get("/lists", response_model=List[ShoppingListResponse])
async def list_lists(
    include_archived: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await ShoppingService.list_lists(
        db,
        family_id=to_uuid_required(current_user.family_id),
        include_archived=include_archived,
    )
    return [
        _to_list_response(r["obj"], r["item_count"], r["pending_count"]) for r in rows
    ]


@router.post(
    "/lists",
    response_model=ShoppingListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_list(
    data: ShoppingListCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await ShoppingService.create_list(
        db,
        data,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
    )
    return _to_list_response(lst, 0, 0)


@router.get("/lists/{list_id}", response_model=ShoppingListDetailResponse)
async def get_list_detail(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await ShoppingService.get_list(
        db, list_id, to_uuid_required(current_user.family_id)
    )
    items = list(lst.items)
    return ShoppingListDetailResponse(
        id=lst.id,
        family_id=lst.family_id,
        name=lst.name,
        is_archived=lst.is_archived,
        created_by=lst.created_by,
        created_at=lst.created_at,
        updated_at=lst.updated_at,
        item_count=len(items),
        pending_count=sum(1 for i in items if not i.is_checked),
        items=[ShoppingItemResponse.model_validate(i) for i in items],
    )


@router.patch("/lists/{list_id}", response_model=ShoppingListResponse)
async def update_list(
    list_id: UUID,
    data: ShoppingListUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await ShoppingService.update_list(
        db, list_id, data, to_uuid_required(current_user.family_id)
    )
    return _to_list_response(lst, 0, 0)


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ShoppingService.delete_list(
        db, list_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.post(
    "/lists/{list_id}/items",
    response_model=ShoppingItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    list_id: UUID,
    data: ShoppingItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await ShoppingService.add_item(
        db,
        list_id=list_id,
        family_id=to_uuid_required(current_user.family_id),
        added_by=to_uuid_required(current_user.id),
        data=data,
    )
    return ShoppingItemResponse.model_validate(item)


@router.patch("/items/{item_id}", response_model=ShoppingItemResponse)
async def update_item(
    item_id: UUID,
    data: ShoppingItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await ShoppingService.update_item(
        db,
        item_id=item_id,
        family_id=to_uuid_required(current_user.family_id),
        actor_id=to_uuid_required(current_user.id),
        data=data,
    )
    return ShoppingItemResponse.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ShoppingService.delete_item(
        db, item_id, to_uuid_required(current_user.family_id)
    )
    return None
