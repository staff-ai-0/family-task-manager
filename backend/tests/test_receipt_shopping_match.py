"""Receipt → shopping auto-check fuzzy matching (W5.1)."""

import pytest
from sqlalchemy import select

from app.models.shopping import ShoppingItem
from app.schemas.shopping import ShoppingItemCreate, ShoppingListCreate
from app.services.budget.receipt_scanner_service import _auto_check_shopping_items
from app.services.shopping_service import ShoppingService


async def _seed_pending_list(db, family, parent, items: list[str]):
    lst = await ShoppingService.create_list(
        db, ShoppingListCreate(name="Mercado"), family.id, parent.id
    )
    for name in items:
        await ShoppingService.add_item(
            db,
            list_id=lst.id,
            family_id=family.id,
            added_by=parent.id,
            data=ShoppingItemCreate(name=name),
        )
    return lst


class TestAutoCheck:
    async def test_exact_match_checks_item(
        self, db_session, test_family, test_parent_user
    ):
        await _seed_pending_list(
            db_session, test_family, test_parent_user, ["Tortillas"]
        )
        matched = await _auto_check_shopping_items(
            db_session, test_family.id, ["Tortillas de harina 1kg"]
        )
        assert "Tortillas" in matched

    async def test_fuzzy_match_checks_item(
        self, db_session, test_family, test_parent_user
    ):
        await _seed_pending_list(
            db_session, test_family, test_parent_user, ["leche entera"]
        )
        matched = await _auto_check_shopping_items(
            db_session, test_family.id, ["LECHE ENTERA"]
        )
        assert "leche entera" in matched

    async def test_unrelated_does_not_match(
        self, db_session, test_family, test_parent_user
    ):
        await _seed_pending_list(
            db_session, test_family, test_parent_user, ["plátanos"]
        )
        matched = await _auto_check_shopping_items(
            db_session, test_family.id, ["Detergente Ariel"]
        )
        assert matched == []

    async def test_checked_items_skipped(
        self, db_session, test_family, test_parent_user
    ):
        await _seed_pending_list(
            db_session, test_family, test_parent_user, ["tortillas"]
        )
        # First call checks it.
        await _auto_check_shopping_items(
            db_session, test_family.id, ["Tortillas"]
        )
        # Second call: item already checked, should not re-match.
        matched = await _auto_check_shopping_items(
            db_session, test_family.id, ["Tortillas"]
        )
        assert matched == []

    async def test_short_token_does_not_substring_match(
        self, db_session, test_family, test_parent_user
    ):
        # "te" inside "leche" should NOT trigger via substring path
        # because min length < 4. Ratio also low.
        await _seed_pending_list(
            db_session, test_family, test_parent_user, ["te"]
        )
        matched = await _auto_check_shopping_items(
            db_session, test_family.id, ["leche"]
        )
        assert matched == []
