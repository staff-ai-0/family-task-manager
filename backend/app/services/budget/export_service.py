"""
Budget Export/Import Service

Handles exporting all budget data as a ZIP archive and restoring from backup.
"""

import io
import json
import zipfile
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.exceptions import ValidationError

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

BACKUP_MEMBER = "budget_data.json"
# A real export of a large family is a few MB of JSON; 200 MB is generous while
# still refusing an archive engineered to exhaust memory on decompression.
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


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
            "exported_at": datetime.now(timezone.utc).isoformat(),
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
            # Only the COMPRESSED upload was capped (25 MB). DEFLATE reaches
            # ~1000:1 on repetitive input, so that bound allowed tens of GB to
            # be decompressed into memory before any of our code looked at it.
            try:
                info = zf.getinfo(BACKUP_MEMBER)
            except KeyError:
                raise ValidationError(
                    f"Backup archive is missing {BACKUP_MEMBER}"
                )
            if info.file_size > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError(
                    "Backup archive is too large once decompressed "
                    f"({info.file_size // (1024 * 1024)} MB, limit "
                    f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB)."
                )
            total = sum(i.file_size for i in zf.infolist())
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError(
                    "Backup archive expands to more than "
                    f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB in total."
                )
            data_str = zf.read(BACKUP_MEMBER).decode("utf-8")
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

        # Primary keys and foreign keys arrive from an untrusted file. Reusing
        # them verbatim let a crafted archive point this family's rows at ANOTHER
        # family's account/category/payee — the FK constraints reference the
        # global tables, so such a row inserts cleanly. Every id is reminted and
        # every reference is remapped through this map; anything that does not
        # resolve WITHIN the archive is rejected rather than silently dropped.
        id_map: dict[str, UUID] = {}
        # column name -> the archive section whose ids it points at
        fk_sources = {
            "account_id": "accounts",
            "transfer_account_id": "accounts",
            "group_id": "category_groups",
            "category_id": "categories",
            "payee_id": "payees",
            "parent_id": "transactions",
        }

        def _remap(item: dict, model_cls: Any, key: str) -> None:
            columns = {c.name for c in model_cls.__table__.columns}
            for column, _source in fk_sources.items():
                if column not in columns:
                    continue
                raw = item.get(column)
                if raw in (None, ""):
                    item[column] = None
                    continue
                mapped = id_map.get(str(raw))
                if mapped is None:
                    raise ValidationError(
                        f"Backup archive is inconsistent: {key}.{column} "
                        f"references {raw}, which is not in the archive."
                    )
                item[column] = mapped

        for key, model_cls in _import_map:
            items = budget_data.get(key, [])
            count = 0
            deferred_parents: list[tuple[Any, str]] = []
            for item_dict in items:
                item_dict = dict(item_dict)
                old_id = str(item_dict.get("id") or "")
                # Never trust a client-supplied primary key.
                item_dict.pop("id", None)
                item_dict["family_id"] = family_id
                _convert_uuids(item_dict, model_cls)
                _convert_dates(item_dict, model_cls)

                # A split child may appear before its parent, so parent_id is
                # resolved after the whole section is mapped.
                parent_ref = None
                if "parent_id" in item_dict and item_dict.get("parent_id"):
                    parent_ref = str(item_dict["parent_id"])
                    item_dict["parent_id"] = None
                _remap(item_dict, model_cls, key)

                # transfer_pair_id is a shared id, not an FK; reminting it keeps
                # both legs joined without colliding with a live pair.
                if item_dict.get("transfer_pair_id"):
                    pair_key = f"pair:{item_dict['transfer_pair_id']}"
                    if pair_key not in id_map:
                        id_map[pair_key] = uuid4()
                    item_dict["transfer_pair_id"] = id_map[pair_key]

                obj = model_cls(**item_dict)
                obj.id = uuid4()
                if old_id:
                    id_map[old_id] = obj.id
                db.add(obj)
                if parent_ref:
                    deferred_parents.append((obj, parent_ref))
                count += 1

            for obj, parent_ref in deferred_parents:
                mapped = id_map.get(parent_ref)
                if mapped is None:
                    raise ValidationError(
                        f"Backup archive is inconsistent: {key}.parent_id "
                        f"references {parent_ref}, which is not in the archive."
                    )
                obj.parent_id = mapped

            await db.flush()
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
