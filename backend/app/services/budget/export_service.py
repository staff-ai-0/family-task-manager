"""
Budget Export/Import Service

Handles exporting all budget data as a ZIP archive and restoring from backup.
"""

import io
import json
import zipfile
from datetime import date, datetime
from typing import Any, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetCategorizationRule,
    BudgetGoal,
    BudgetPayee,
    BudgetRecurringTransaction,
    BudgetTransaction,
)


def _serialize_value(v: Any) -> Any:
    """Convert a value to JSON-safe type."""
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _model_to_dict(obj: Any, exclude: set | None = None) -> dict:
    """Convert a SQLAlchemy model instance to a serializable dict."""
    exclude = exclude or set()
    result = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        result[col.name] = _serialize_value(getattr(obj, col.name))
    return result


class ExportService:
    """Service for budget data export and import."""

    @classmethod
    async def export_budget(cls, db: AsyncSession, family_id: UUID) -> bytes:
        """Export all budget data as a ZIP file.

        Returns:
            ZIP file bytes containing budget_data.json and metadata.json.
        """
        # Query all budget entities (excludes soft-deleted rows)
        accounts = (await db.execute(
            select(BudgetAccount).where(
                BudgetAccount.family_id == family_id,
                BudgetAccount.deleted_at.is_(None),
            )
        )).scalars().all()

        category_groups = (await db.execute(
            select(BudgetCategoryGroup).where(
                BudgetCategoryGroup.family_id == family_id,
                BudgetCategoryGroup.deleted_at.is_(None),
            )
        )).scalars().all()

        categories = (await db.execute(
            select(BudgetCategory).where(
                BudgetCategory.family_id == family_id,
                BudgetCategory.deleted_at.is_(None),
            )
        )).scalars().all()

        payees = (await db.execute(
            select(BudgetPayee).where(BudgetPayee.family_id == family_id)
        )).scalars().all()

        transactions = (await db.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )).scalars().all()

        allocations = (await db.execute(
            select(BudgetAllocation).where(BudgetAllocation.family_id == family_id)
        )).scalars().all()

        rules = (await db.execute(
            select(BudgetCategorizationRule).where(BudgetCategorizationRule.family_id == family_id)
        )).scalars().all()

        goals = (await db.execute(
            select(BudgetGoal).where(BudgetGoal.family_id == family_id)
        )).scalars().all()

        recurring = (await db.execute(
            select(BudgetRecurringTransaction).where(BudgetRecurringTransaction.family_id == family_id)
        )).scalars().all()

        # Serialize
        budget_data = {
            "accounts": [_model_to_dict(a) for a in accounts],
            "category_groups": [_model_to_dict(g) for g in category_groups],
            "categories": [_model_to_dict(c) for c in categories],
            "payees": [_model_to_dict(p) for p in payees],
            "transactions": [_model_to_dict(t) for t in transactions],
            "allocations": [_model_to_dict(a) for a in allocations],
            "rules": [_model_to_dict(r) for r in rules],
            "goals": [_model_to_dict(g) for g in goals],
            "recurring": [_model_to_dict(r) for r in recurring],
        }

        metadata = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "family_id": str(family_id),
            "counts": {k: len(v) for k, v in budget_data.items()},
        }

        # Create ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("budget_data.json", json.dumps(budget_data, indent=2, default=str))
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
        buf.seek(0)
        return buf.read()

    @classmethod
    async def import_budget(cls, db: AsyncSession, family_id: UUID, zip_bytes: bytes) -> dict:
        """Import budget data from a ZIP backup. Clears existing data first.

        Args:
            db: Database session
            family_id: Family ID
            zip_bytes: ZIP file bytes

        Returns:
            Dict with import statistics.
        """
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            data_str = zf.read("budget_data.json").decode("utf-8")
            budget_data = json.loads(data_str)

        # Clear existing budget data (order matters for FK constraints)
        for model_cls in [
            BudgetTransaction,
            BudgetAllocation,
            BudgetRecurringTransaction,
            BudgetGoal,
            BudgetCategorizationRule,
            BudgetCategory,
            BudgetCategoryGroup,
            BudgetPayee,
            BudgetAccount,
        ]:
            await db.execute(delete(model_cls).where(model_cls.family_id == family_id))
        await db.flush()

        stats = {}

        # Import in dependency order
        _import_map = [
            ("accounts", BudgetAccount),
            ("category_groups", BudgetCategoryGroup),
            ("categories", BudgetCategory),
            ("payees", BudgetPayee),
            ("allocations", BudgetAllocation),
            ("rules", BudgetCategorizationRule),
            ("goals", BudgetGoal),
            ("recurring", BudgetRecurringTransaction),
            ("transactions", BudgetTransaction),
        ]

        for key, model_cls in _import_map:
            items = budget_data.get(key, [])
            count = 0
            for item_dict in items:
                # Override family_id to current family
                item_dict["family_id"] = family_id
                # Convert UUID strings back
                _convert_uuids(item_dict, model_cls)
                # Convert dates/datetimes back
                _convert_dates(item_dict, model_cls)

                obj = model_cls(**item_dict)
                db.add(obj)
                count += 1
            stats[key] = count

        await db.commit()
        return stats


def _convert_uuids(item: dict, model_cls: Any) -> None:
    """Convert string UUIDs back to UUID objects for UUID columns."""
    for col in model_cls.__table__.columns:
        if col.name in item and item[col.name] is not None:
            col_type = str(col.type)
            if "UUID" in col_type.upper():
                try:
                    item[col.name] = UUID(str(item[col.name]))
                except (ValueError, TypeError):
                    pass


def _convert_dates(item: dict, model_cls: Any) -> None:
    """Convert ISO date strings back to date/datetime objects."""
    for col in model_cls.__table__.columns:
        if col.name in item and item[col.name] is not None:
            col_type_str = str(col.type).upper()
            val = item[col.name]
            if isinstance(val, str):
                if "DATETIME" in col_type_str or "TIMESTAMP" in col_type_str:
                    try:
                        item[col.name] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        pass
                elif "DATE" in col_type_str:
                    try:
                        item[col.name] = date.fromisoformat(val)
                    except (ValueError, TypeError):
                        pass
