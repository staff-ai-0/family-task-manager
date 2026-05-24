"""Shopping list service (W1.4).

Family-scoped CRUD for shopping lists and items. Everyone in the family can
read/write; archived lists stay queryable for history.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException, ForbiddenException
from app.models.shopping import ShoppingItem, ShoppingList
from app.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListUpdate,
)


class ShoppingService:
    # ─── Lists ────────────────────────────────────────────────────────

    @staticmethod
    async def create_list(
        db: AsyncSession,
        data: ShoppingListCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> ShoppingList:
        lst = ShoppingList(
            name=data.name,
            family_id=family_id,
            created_by=created_by,
        )
        db.add(lst)
        await db.commit()
        await db.refresh(lst)
        return lst

    @staticmethod
    async def list_lists(
        db: AsyncSession,
        family_id: UUID,
        include_archived: bool = False,
    ) -> List[dict]:
        q = select(ShoppingList).where(ShoppingList.family_id == family_id)
        if not include_archived:
            q = q.where(ShoppingList.is_archived.is_(False))
        q = q.order_by(ShoppingList.created_at.desc())
        lists = list((await db.execute(q)).scalars().all())

        if not lists:
            return []
        list_ids = [l.id for l in lists]
        rows = (
            await db.execute(
                select(
                    ShoppingItem.list_id,
                    func.count().label("total"),
                    func.count()
                    .filter(ShoppingItem.is_checked.is_(False))
                    .label("pending"),
                )
                .where(ShoppingItem.list_id.in_(list_ids))
                .group_by(ShoppingItem.list_id)
            )
        ).all()
        counts = {row[0]: (row[1] or 0, row[2] or 0) for row in rows}

        return [
            {
                "obj": l,
                "item_count": counts.get(l.id, (0, 0))[0],
                "pending_count": counts.get(l.id, (0, 0))[1],
            }
            for l in lists
        ]

    @staticmethod
    async def get_list(
        db: AsyncSession, list_id: UUID, family_id: UUID
    ) -> ShoppingList:
        q = (
            select(ShoppingList)
            .options(selectinload(ShoppingList.items))
            .where(
                and_(
                    ShoppingList.id == list_id,
                    ShoppingList.family_id == family_id,
                )
            )
        )
        lst = (await db.execute(q)).scalar_one_or_none()
        if not lst:
            raise NotFoundException("Shopping list not found")
        return lst

    @staticmethod
    async def update_list(
        db: AsyncSession,
        list_id: UUID,
        data: ShoppingListUpdate,
        family_id: UUID,
    ) -> ShoppingList:
        lst = await ShoppingService.get_list(db, list_id, family_id)
        update = data.model_dump(exclude_unset=True)
        for k, v in update.items():
            setattr(lst, k, v)
        await db.commit()
        await db.refresh(lst)
        return lst

    @staticmethod
    async def delete_list(
        db: AsyncSession, list_id: UUID, family_id: UUID
    ) -> None:
        lst = await ShoppingService.get_list(db, list_id, family_id)
        await db.delete(lst)
        await db.commit()

    # ─── Items ────────────────────────────────────────────────────────

    @staticmethod
    async def add_item(
        db: AsyncSession,
        list_id: UUID,
        family_id: UUID,
        added_by: UUID,
        data: ShoppingItemCreate,
    ) -> ShoppingItem:
        # Verify the parent list belongs to the family.
        await ShoppingService.get_list(db, list_id, family_id)
        item = ShoppingItem(
            list_id=list_id,
            name=data.name,
            qty=data.qty,
            note=data.note,
            added_by=added_by,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def _get_item_in_family(
        db: AsyncSession, item_id: UUID, family_id: UUID
    ) -> ShoppingItem:
        q = (
            select(ShoppingItem)
            .join(ShoppingList, ShoppingItem.list_id == ShoppingList.id)
            .where(
                and_(
                    ShoppingItem.id == item_id,
                    ShoppingList.family_id == family_id,
                )
            )
        )
        item = (await db.execute(q)).scalar_one_or_none()
        if not item:
            raise NotFoundException("Shopping item not found")
        return item

    @staticmethod
    async def update_item(
        db: AsyncSession,
        item_id: UUID,
        family_id: UUID,
        actor_id: UUID,
        data: ShoppingItemUpdate,
    ) -> ShoppingItem:
        item = await ShoppingService._get_item_in_family(db, item_id, family_id)
        update = data.model_dump(exclude_unset=True)

        if "is_checked" in update:
            new_state = bool(update.pop("is_checked"))
            if new_state and not item.is_checked:
                item.checked_by = actor_id
                item.checked_at = datetime.now(timezone.utc)
            elif not new_state and item.is_checked:
                item.checked_by = None
                item.checked_at = None
            item.is_checked = new_state

        for k, v in update.items():
            setattr(item, k, v)

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def delete_item(
        db: AsyncSession, item_id: UUID, family_id: UUID
    ) -> None:
        item = await ShoppingService._get_item_in_family(db, item_id, family_id)
        await db.delete(item)
        await db.commit()
