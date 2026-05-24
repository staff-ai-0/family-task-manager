"""Shopping list service tests (W1.4)."""

import pytest
from sqlalchemy import select

from app.core.exceptions import NotFoundException
from app.models.shopping import ShoppingItem, ShoppingList
from app.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListUpdate,
)
from app.services.shopping_service import ShoppingService


class TestLists:
    async def test_create_and_get_list(
        self, db_session, test_family, test_parent_user
    ):
        lst = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="Costco"),
            test_family.id,
            test_parent_user.id,
        )
        assert lst.name == "Costco"
        assert lst.family_id == test_family.id
        assert lst.is_archived is False
        fetched = await ShoppingService.get_list(db_session, lst.id, test_family.id)
        assert fetched.id == lst.id

    async def test_get_list_isolation(
        self, db_session, test_family, test_parent_user
    ):
        lst = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="A"),
            test_family.id,
            test_parent_user.id,
        )
        from uuid import uuid4
        with pytest.raises(NotFoundException):
            await ShoppingService.get_list(db_session, lst.id, uuid4())

    async def test_list_lists_excludes_archived_by_default(
        self, db_session, test_family, test_parent_user
    ):
        a = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="Active"),
            test_family.id,
            test_parent_user.id,
        )
        b = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="Archived"),
            test_family.id,
            test_parent_user.id,
        )
        await ShoppingService.update_list(
            db_session, b.id, ShoppingListUpdate(is_archived=True), test_family.id
        )
        rows = await ShoppingService.list_lists(db_session, test_family.id)
        names = [r["obj"].name for r in rows]
        assert "Active" in names
        assert "Archived" not in names

        all_rows = await ShoppingService.list_lists(
            db_session, test_family.id, include_archived=True
        )
        all_names = [r["obj"].name for r in all_rows]
        assert "Archived" in all_names


class TestItems:
    async def test_add_and_check_item(
        self, db_session, test_family, test_parent_user
    ):
        lst = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="Mercado"),
            test_family.id,
            test_parent_user.id,
        )
        item = await ShoppingService.add_item(
            db_session,
            list_id=lst.id,
            family_id=test_family.id,
            added_by=test_parent_user.id,
            data=ShoppingItemCreate(name="Tortillas", qty="2 pkg"),
        )
        assert item.name == "Tortillas"
        assert item.is_checked is False
        assert item.added_by == test_parent_user.id

        checked = await ShoppingService.update_item(
            db_session,
            item_id=item.id,
            family_id=test_family.id,
            actor_id=test_parent_user.id,
            data=ShoppingItemUpdate(is_checked=True),
        )
        assert checked.is_checked is True
        assert checked.checked_by == test_parent_user.id
        assert checked.checked_at is not None

        unchecked = await ShoppingService.update_item(
            db_session,
            item_id=item.id,
            family_id=test_family.id,
            actor_id=test_parent_user.id,
            data=ShoppingItemUpdate(is_checked=False),
        )
        assert unchecked.is_checked is False
        assert unchecked.checked_by is None
        assert unchecked.checked_at is None

    async def test_pending_count_in_list(
        self, db_session, test_family, test_parent_user
    ):
        lst = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="X"),
            test_family.id,
            test_parent_user.id,
        )
        for name in ("A", "B", "C"):
            await ShoppingService.add_item(
                db_session,
                list_id=lst.id,
                family_id=test_family.id,
                added_by=test_parent_user.id,
                data=ShoppingItemCreate(name=name),
            )
        # Check off one
        items = (
            await db_session.execute(
                select(ShoppingItem).where(ShoppingItem.list_id == lst.id)
            )
        ).scalars().all()
        await ShoppingService.update_item(
            db_session,
            item_id=items[0].id,
            family_id=test_family.id,
            actor_id=test_parent_user.id,
            data=ShoppingItemUpdate(is_checked=True),
        )
        rows = await ShoppingService.list_lists(db_session, test_family.id)
        match = next(r for r in rows if r["obj"].id == lst.id)
        assert match["item_count"] == 3
        assert match["pending_count"] == 2

    async def test_delete_item(
        self, db_session, test_family, test_parent_user
    ):
        lst = await ShoppingService.create_list(
            db_session,
            ShoppingListCreate(name="X"),
            test_family.id,
            test_parent_user.id,
        )
        item = await ShoppingService.add_item(
            db_session,
            list_id=lst.id,
            family_id=test_family.id,
            added_by=test_parent_user.id,
            data=ShoppingItemCreate(name="Drop me"),
        )
        await ShoppingService.delete_item(db_session, item.id, test_family.id)
        with pytest.raises(NotFoundException):
            await ShoppingService._get_item_in_family(
                db_session, item.id, test_family.id
            )
