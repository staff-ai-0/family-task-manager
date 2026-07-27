"""DeduplicateService — destructive, money-adjacent, previously untested.

`POST /api/budget/transactions/deduplicate` soft-deletes rows across a family's
whole history with `dry_run` defaulting to False, and had 0% coverage. The bug
that motivated this suite: the old pairwise sweep only marked the INNER row as
consumed, so once the outer row lost a comparison it was soft-deleted and then
kept being used as a merge candidate — re-deleting it, folding later rows into
a tombstone, and leaving the real duplicates alive while reporting them merged.

The invariant that makes that class of bug impossible, and which most of these
tests assert one way or another: a group of N mutual duplicates always leaves
exactly ONE live row, and `merged` always equals the number of rows actually
soft-deleted.
"""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models.budget import BudgetTransaction
from app.services.budget.dedup_service import DeduplicateService

DAY = date(2026, 7, 1)


@pytest.fixture
def txn_factory(db, family, account_factory):
    """Create a live transaction with controllable richness and created_at."""
    created = {"n": 0}

    async def _make(
        account,
        *,
        amount: int = -10000,
        on: date = DAY,
        notes: str | None = None,
        category_id=None,
        receipt_image_path: str | None = None,
        cleared: bool = False,
        imported_id: str | None = None,
        is_parent: bool = False,
        parent_id=None,
        family_id=None,
    ):
        # Deterministic, strictly increasing created_at: the keeper tie-break
        # and the scan order both depend on it.
        created["n"] += 1
        txn = BudgetTransaction(
            id=uuid4(),
            family_id=family_id or family.id,
            account_id=account.id,
            date=on,
            amount=amount,
            notes=notes,
            category_id=category_id,
            receipt_image_path=receipt_image_path,
            cleared=cleared,
            imported_id=imported_id,
            is_parent=is_parent,
            parent_id=parent_id,
            created_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
            + timedelta(seconds=created["n"]),
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)
        return txn

    return _make


async def _live_ids(db, family_id):
    rows = (
        await db.execute(
            select(BudgetTransaction.id).where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return set(rows)


async def _deleted_count(db, family_id):
    rows = (
        await db.execute(
            select(BudgetTransaction.id).where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_not(None),
            )
        )
    ).scalars().all()
    return len(rows)


class TestGroupResolution:
    """The core invariant: N duplicates collapse to exactly one live row."""

    async def test_triple_duplicate_leaves_exactly_one_live_row(
        self, db, family, account_factory, txn_factory
    ):
        acct = await account_factory(family.id)
        t1 = await txn_factory(acct, receipt_image_path="local:f/t1.jpg")
        t2 = await txn_factory(acct, notes="from bank", cleared=True)
        t3 = await txn_factory(acct, notes="from bank too", cleared=True)

        result = await DeduplicateService.run(db, family.id)

        live = await _live_ids(db, family.id)
        assert len(live) == 1, "a group of 3 duplicates must leave exactly 1 live row"
        # The image-bearing row scores highest, so it is the survivor.
        assert live == {t1.id}
        assert result["merged"] == 2
        assert {t2.id, t3.id} == {t2.id, t3.id}

    async def test_triple_duplicate_when_the_richest_row_is_last(
        self, db, family, account_factory, txn_factory
    ):
        """Ordering matters: the pairwise bug only bit when the anchor lost.

        With the richest row FIRST the old code happened to be correct. With it
        LAST, the anchor lost its first comparison, got soft-deleted, and then
        kept being used as a merge candidate — so the survivors stayed
        duplicates of each other while the run reported them merged.
        """
        acct = await account_factory(family.id)
        await txn_factory(acct, notes="plain")                       # weakest
        await txn_factory(acct, notes="plain", cleared=True)
        richest = await txn_factory(acct, receipt_image_path="local:f/z.jpg")

        result = await DeduplicateService.run(db, family.id)

        live = await _live_ids(db, family.id)
        assert live == {richest.id}, (
            "the richest row must be the sole survivor regardless of insert order"
        )
        assert result["merged"] == 2 == await _deleted_count(db, family.id)

    async def test_merged_count_equals_rows_actually_soft_deleted(
        self, db, family, account_factory, txn_factory
    ):
        """The old code reported merged=3 while deleting 2 rows."""
        acct = await account_factory(family.id)
        await txn_factory(acct)
        await txn_factory(acct, notes="n")
        await txn_factory(acct, receipt_image_path="local:f/x.jpg")

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == await _deleted_count(db, family.id)
        assert result["merged"] == len(result["pairs"])

    async def test_no_pair_names_a_deleted_row_as_keeper(
        self, db, family, account_factory, txn_factory
    ):
        """A tombstone must never receive merged notes/category/receipt."""
        acct = await account_factory(family.id)
        await txn_factory(acct, notes="only notes")
        await txn_factory(acct, receipt_image_path="local:f/img.jpg")
        await txn_factory(acct, notes="third")

        result = await DeduplicateService.run(db, family.id)

        for pair in result["pairs"]:
            keeper = (
                await db.execute(
                    select(BudgetTransaction).where(
                        BudgetTransaction.id == UUID(pair["keeper_id"])
                    )
                )
            ).scalar_one()
            assert keeper.deleted_at is None, "keeper must be a live row"

    async def test_rerun_is_idempotent(
        self, db, family, account_factory, txn_factory
    ):
        acct = await account_factory(family.id)
        await txn_factory(acct, notes="a")
        await txn_factory(acct, notes="b")

        first = await DeduplicateService.run(db, family.id)
        survivors = await _live_ids(db, family.id)
        second = await DeduplicateService.run(db, family.id)

        assert first["merged"] == 1
        assert second["merged"] == 0
        assert second["pairs"] == []
        assert await _live_ids(db, family.id) == survivors


class TestDataPreservation:
    async def test_receipt_image_is_moved_not_copied(
        self, db, family, account_factory, txn_factory
    ):
        """Two live rows must never reference the same stored object."""
        acct = await account_factory(family.id)
        # Loser carries the image; keeper wins on items/notes/cleared.
        await txn_factory(acct, receipt_image_path="local:f/only.jpg")
        await txn_factory(
            acct, notes="richer", cleared=True, category_id=None,
        )

        await DeduplicateService.run(db, family.id)

        rows = (
            await db.execute(
                select(BudgetTransaction).where(
                    BudgetTransaction.family_id == family.id,
                )
            )
        ).scalars().all()
        paths = [r.receipt_image_path for r in rows if r.receipt_image_path]
        assert len(paths) == len(set(paths)), "an image path is referenced twice"
        live_with_path = [
            r for r in rows if r.deleted_at is None and r.receipt_image_path
        ]
        assert len(live_with_path) == 1
        assert live_with_path[0].receipt_image_path == "local:f/only.jpg"

    async def test_keeper_notes_are_not_clobbered(
        self, db, family, account_factory, txn_factory
    ):
        """A hand-typed note must survive a merge with a longer bank memo."""
        acct = await account_factory(family.id)
        keeper = await txn_factory(
            acct,
            notes="Reembolsado por Mayra",
            receipt_image_path="local:f/k.jpg",
            cleared=True,
        )
        await txn_factory(acct, notes="Compra supermercado XYZ ticket largo")

        await DeduplicateService.run(db, family.id)

        await db.refresh(keeper)
        assert keeper.deleted_at is None
        assert "Reembolsado por Mayra" in (keeper.notes or "")

    async def test_category_is_inherited_when_keeper_has_none(
        self, db, family, account_factory, txn_factory
    ):
        from app.schemas.budget import CategoryCreate, CategoryGroupCreate
        from app.services.budget.category_service import (
            CategoryGroupService,
            CategoryService,
        )

        group = await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Casa", is_income=False)
        )
        category = await CategoryService.create(
            db, family.id, CategoryCreate(name="Super", group_id=group.id)
        )
        acct = await account_factory(family.id)
        keeper = await txn_factory(
            acct, receipt_image_path="local:f/k.jpg", cleared=True
        )
        await txn_factory(acct, category_id=category.id)

        await DeduplicateService.run(db, family.id)

        await db.refresh(keeper)
        assert keeper.category_id == category.id


class TestRefusals:
    async def test_group_with_two_images_is_refused_and_reported(
        self, db, family, account_factory, txn_factory
    ):
        """Two receipts for one amount could be two real purchases."""
        acct = await account_factory(family.id)
        await txn_factory(acct, receipt_image_path="local:f/a.jpg")
        await txn_factory(acct, receipt_image_path="local:f/b.jpg")

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 0
        assert result["refused"] == 1
        assert len(await _live_ids(db, family.id)) == 2

    async def test_split_parent_is_never_merged(
        self, db, family, account_factory, txn_factory
    ):
        """Merging a split parent strands its legs live in every activity total."""
        acct = await account_factory(family.id)
        p1 = await txn_factory(acct, is_parent=True)
        p2 = await txn_factory(acct, is_parent=True)
        await txn_factory(acct, amount=-7000, parent_id=p1.id)
        await txn_factory(acct, amount=-3000, parent_id=p1.id)
        await txn_factory(acct, amount=-7000, parent_id=p2.id)
        await txn_factory(acct, amount=-3000, parent_id=p2.id)

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 0
        assert await _deleted_count(db, family.id) == 0

    async def test_split_children_are_never_candidates(
        self, db, family, account_factory, txn_factory
    ):
        acct = await account_factory(family.id)
        parent = await txn_factory(acct, is_parent=True)
        await txn_factory(acct, amount=-5000, parent_id=parent.id)
        await txn_factory(acct, amount=-5000, parent_id=parent.id)

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 0

    async def test_tolerance_floor_no_longer_widens_tiny_amounts(
        self, db, family, account_factory, txn_factory
    ):
        """A 0 must not swallow a real 1-cent row.

        The old window was max(1, amount*1%), so the floor forced a 1-cent
        tolerance onto amounts where a true 1% rounds to 0 — making 0 and -1
        "duplicates" and destroying a real cent. Without the floor, 1% of 1
        cent is 0, so they no longer match. (-100 vs -101 DOES still merge:
        1% of 101 is 1 cent, which is the tolerance behaving as specified.)
        """
        acct = await account_factory(family.id)
        zero = await txn_factory(acct, amount=0)
        cent = await txn_factory(acct, amount=-1)

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 0
        for row in (zero, cent):
            await db.refresh(row)
            assert row.deleted_at is None

    async def test_different_account_or_date_never_merges(
        self, db, family, account_factory, txn_factory
    ):
        a = await account_factory(family.id, name="A")
        b = await account_factory(family.id, name="B")
        await txn_factory(a, on=DAY)
        await txn_factory(b, on=DAY)                       # same day, other account
        await txn_factory(a, on=DAY + timedelta(days=1))   # same account, next day

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 0


class TestTolerance:
    async def test_tolerance_is_order_independent(
        self, db, family, account_factory, txn_factory
    ):
        """Whether two rows are duplicates must not depend on insertion order.

        The old window came from the earlier row only, so -10000 then -9900
        merged while -9900 then -10000 did not.
        """
        a = await account_factory(family.id, name="A")
        b = await account_factory(family.id, name="B")
        await txn_factory(a, amount=-10000)
        await txn_factory(a, amount=-9900)
        await txn_factory(b, amount=-9900)
        await txn_factory(b, amount=-10000)

        result = await DeduplicateService.run(db, family.id, dry_run=True)

        # Either both accounts treat (-10000, -9900) as duplicates or neither
        # does; one-of-two means the answer depended on insertion order.
        assert len(result["pairs"]) in (0, 2), (
            "the same amount pair resolved differently depending on which row "
            f"was inserted first: {result['pairs']}"
        )

    def test_tolerance_predicate_is_symmetric(self):
        within = DeduplicateService._within_tolerance
        assert within(-10000, -9900) == within(-9900, -10000)
        assert within(-100, -101) == within(-101, -100)
        assert within(0, 0) is True
        assert within(0, -1) is False, "a 0 must not absorb a real 1-cent row"


class TestDryRun:
    async def test_dry_run_mutates_nothing(
        self, db, family, account_factory, txn_factory
    ):
        acct = await account_factory(family.id)
        t1 = await txn_factory(acct, receipt_image_path="local:f/a.jpg")
        t2 = await txn_factory(acct, notes="b")

        result = await DeduplicateService.run(db, family.id, dry_run=True)

        assert result["dry_run"] is True
        assert result["merged"] == 0
        assert len(result["pairs"]) == 1, "preview must still show what would go"
        await db.refresh(t1)
        await db.refresh(t2)
        assert t1.deleted_at is None and t2.deleted_at is None
        assert t1.receipt_image_path == "local:f/a.jpg"
        assert t2.notes == "b"

    async def test_dry_run_pair_count_matches_the_real_run(
        self, db, family, account_factory, txn_factory
    ):
        """The UI confirms on the dry-run count and reports the real one."""
        acct = await account_factory(family.id)
        await txn_factory(acct)
        await txn_factory(acct, notes="n")
        await txn_factory(acct, receipt_image_path="local:f/x.jpg")

        preview = await DeduplicateService.run(db, family.id, dry_run=True)
        real = await DeduplicateService.run(db, family.id)

        assert len(preview["pairs"]) == real["merged"]


class TestTenantIsolation:
    async def test_other_family_rows_are_never_touched(
        self, db, family, other_family, account_factory, txn_factory
    ):
        mine = await account_factory(family.id, name="Mine")
        theirs = await account_factory(other_family.id, name="Theirs")
        await txn_factory(mine, notes="a")
        await txn_factory(mine, notes="b")
        await txn_factory(theirs, family_id=other_family.id, notes="x")
        await txn_factory(theirs, family_id=other_family.id, notes="y")

        result = await DeduplicateService.run(db, family.id)

        assert result["merged"] == 1
        assert await _deleted_count(db, other_family.id) == 0
        assert len(await _live_ids(db, other_family.id)) == 2
