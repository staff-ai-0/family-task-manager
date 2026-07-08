"""
Whole-family data export (WS-DEL / compliance).

Builds a ZIP of JSON dumps for every user-facing domain owned by ONE family:
users (sans credentials), tasks, gigs, points/cash, rewards, consequences,
budget (reusing the budget ExportService so that portion stays re-importable),
calendar, meals, shopping, chat + DMs, pets, and notifications.

Uploaded images are NOT bundled — the archive carries a manifest of the file
paths instead (see uploads_manifest.json + README.txt inside the ZIP).

Multi-tenant: every query filters by the caller's family_id.
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CalendarEvent,
    CashTransaction,
    Consequence,
    DMMessage,
    DMThread,
    FamilyChatMessage,
    FamilyChatReaction,
    FamilyInvitation,
    GigClaim,
    GigOffering,
    KidPet,
    MealPlanEntry,
    Notification,
    PointTransaction,
    PupScoreSnapshot,
    Recipe,
    Reward,
    RewardRedemption,
    ShoppingItem,
    ShoppingList,
    Task,
    TaskAssignment,
    TaskTemplate,
    User,
    UserRewardGoal,
)
from app.models.budget import (
    BudgetCustomReport,
    BudgetReceiptDraft,
    BudgetSavedFilter,
    BudgetTag,
    BudgetTransaction,
    BudgetTransactionTag,
)
from app.services.budget.export_service import ExportService, _model_to_dict
from app.services.family_service import FamilyService

# Columns stripped from users.json — credentials/secrets are never exported.
_USER_EXCLUDED_COLUMNS = {"password_hash", "token_version"}

# invited_email belongs to a third party who may never have joined the family
# — masked out of the compliance export.
_INVITATION_EXCLUDED_COLUMNS = {"invited_email"}

_README = """Family Task Manager — full family data export
==============================================

EN: This archive contains all data stored for your family, grouped by domain
    as JSON files. Uploaded images (task/gig proof photos, receipt scans) are
    NOT included as binaries; uploads_manifest.json lists their storage paths
    instead. The budget/ folder uses the same format as the in-app budget
    backup and can be re-imported from the budget settings page.

ES: Este archivo contiene todos los datos guardados de tu familia, agrupados
    por dominio en archivos JSON. Las imágenes subidas (fotos de prueba de
    tareas/gigs, escaneos de recibos) NO se incluyen como binarios;
    uploads_manifest.json lista sus rutas de almacenamiento. La carpeta
    budget/ usa el mismo formato que el respaldo de presupuesto de la app y
    puede reimportarse desde los ajustes de presupuesto.
"""


async def _rows(db: AsyncSession, stmt) -> Sequence[Any]:
    return (await db.execute(stmt)).scalars().all()


def _dump(rows: Sequence[Any], exclude: set | None = None) -> list[dict]:
    return [_model_to_dict(r, exclude=exclude) for r in rows]


class FamilyExportService:
    """Builds the whole-family export ZIP."""

    @classmethod
    async def export_family(cls, db: AsyncSession, family_id: UUID) -> bytes:
        family = await FamilyService.get_family(db, family_id)

        def fam(model):
            return select(model).where(model.family_id == family_id)

        users = await _rows(db, fam(User))
        tasks = await _rows(db, fam(Task))
        templates = await _rows(db, fam(TaskTemplate))
        assignments = await _rows(db, fam(TaskAssignment))
        offerings = await _rows(db, fam(GigOffering))
        claims = await _rows(db, fam(GigClaim))
        # PointTransaction has no family_id — it is user-scoped.
        points = await _rows(
            db,
            select(PointTransaction)
            .join(User, PointTransaction.user_id == User.id)
            .where(User.family_id == family_id),
        )
        cash = await _rows(db, fam(CashTransaction))
        rewards = await _rows(db, fam(Reward))
        redemptions = await _rows(db, fam(RewardRedemption))
        reward_goals = await _rows(db, fam(UserRewardGoal))
        consequences = await _rows(db, fam(Consequence))
        events = await _rows(db, fam(CalendarEvent))
        recipes = await _rows(db, fam(Recipe))
        meal_plan = await _rows(db, fam(MealPlanEntry))
        shopping_lists = await _rows(db, fam(ShoppingList))
        shopping_items = await _rows(
            db,
            select(ShoppingItem)
            .join(ShoppingList, ShoppingItem.list_id == ShoppingList.id)
            .where(ShoppingList.family_id == family_id),
        )
        chat_messages = await _rows(db, fam(FamilyChatMessage))
        chat_reactions = await _rows(
            db,
            select(FamilyChatReaction)
            .join(
                FamilyChatMessage,
                FamilyChatReaction.message_id == FamilyChatMessage.id,
            )
            .where(FamilyChatMessage.family_id == family_id),
        )
        dm_threads = await _rows(db, fam(DMThread))
        dm_messages = await _rows(
            db,
            select(DMMessage)
            .join(DMThread, DMMessage.thread_id == DMThread.id)
            .where(DMThread.family_id == family_id),
        )
        pets = await _rows(
            db,
            select(KidPet)
            .join(User, KidPet.user_id == User.id)
            .where(User.family_id == family_id),
        )
        pup_snapshots = await _rows(db, fam(PupScoreSnapshot))
        notifications = await _rows(db, fam(Notification))
        invitations = await _rows(db, fam(FamilyInvitation))

        # Budget extras not covered by the re-importable budget backup format.
        saved_filters = await _rows(db, fam(BudgetSavedFilter))
        tags = await _rows(db, fam(BudgetTag))
        # BudgetTransactionTag is a pure link table (no family_id) — scope via tag.
        txn_tags = await _rows(
            db,
            select(BudgetTransactionTag)
            .join(BudgetTag, BudgetTransactionTag.tag_id == BudgetTag.id)
            .where(BudgetTag.family_id == family_id),
        )
        custom_reports = await _rows(db, fam(BudgetCustomReport))
        receipt_drafts = await _rows(db, fam(BudgetReceiptDraft))

        # Uploaded-image manifest (paths only; binaries are not bundled).
        manifest: list[dict] = []
        for a in assignments:
            if a.proof_image_url:
                manifest.append(
                    {"kind": "task_proof", "record_id": str(a.id), "path": a.proof_image_url}
                )
        for c in claims:
            if c.proof_image_url:
                manifest.append(
                    {"kind": "gig_proof", "record_id": str(c.id), "path": c.proof_image_url}
                )
        for d in receipt_drafts:
            if d.image_url:
                manifest.append(
                    {
                        "kind": "receipt_draft",
                        "record_id": str(d.id),
                        "path": f"/uploads/receipt-drafts/{d.id}.jpg",
                    }
                )
        receipt_txns = (
            await db.execute(
                select(BudgetTransaction.id, BudgetTransaction.receipt_image_path).where(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.receipt_image_path.is_not(None),
                )
            )
        ).all()
        for txn_id, gcs_path in receipt_txns:
            manifest.append(
                {"kind": "receipt_image", "record_id": str(txn_id), "path": gcs_path}
            )

        # Values are either a list of records or (budget/extras.json) a dict
        # of named record lists.
        files: dict[str, Any] = {
            "users.json": _dump(users, exclude=_USER_EXCLUDED_COLUMNS),
            "tasks/legacy_tasks.json": _dump(tasks),
            "tasks/task_templates.json": _dump(templates),
            "tasks/task_assignments.json": _dump(assignments),
            "gigs/offerings.json": _dump(offerings),
            "gigs/claims.json": _dump(claims),
            "points/point_transactions.json": _dump(points),
            "points/cash_transactions.json": _dump(cash),
            "rewards/rewards.json": _dump(rewards),
            "rewards/redemptions.json": _dump(redemptions),
            "rewards/reward_goals.json": _dump(reward_goals),
            "consequences.json": _dump(consequences),
            "calendar/events.json": _dump(events),
            "meals/recipes.json": _dump(recipes),
            "meals/meal_plan.json": _dump(meal_plan),
            "shopping/lists.json": _dump(shopping_lists),
            "shopping/items.json": _dump(shopping_items),
            "chat/messages.json": _dump(chat_messages),
            "chat/reactions.json": _dump(chat_reactions),
            "dm/threads.json": _dump(dm_threads),
            "dm/messages.json": _dump(dm_messages),
            "pet/pets.json": _dump(pets),
            "pet/pup_snapshots.json": _dump(pup_snapshots),
            "notifications.json": _dump(notifications),
            "invitations.json": _dump(
                invitations, exclude=_INVITATION_EXCLUDED_COLUMNS
            ),
            "budget/extras.json": {
                "saved_filters": _dump(saved_filters),
                "tags": _dump(tags),
                "transaction_tags": _dump(txn_tags),
                "custom_reports": _dump(custom_reports),
                "receipt_drafts": _dump(receipt_drafts),
            },
            "uploads_manifest.json": manifest,
        }

        metadata = {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "family_id": str(family_id),
            "family_name": family.name,
            # Dict-shaped files (budget/extras.json) report per-key counts so
            # the numbers reflect actual records, not the wrapper.
            "counts": {
                name: (
                    {key: len(rows) for key, rows in content.items()}
                    if isinstance(content, dict)
                    else len(content)
                )
                for name, content in files.items()
            },
        }

        # Re-importable budget backup, reused verbatim from the budget service.
        budget_zip = await ExportService.export_budget(db, family_id)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.txt", _README)
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
            for name, content in files.items():
                zf.writestr(name, json.dumps(content, indent=2, default=str))
            with zipfile.ZipFile(io.BytesIO(budget_zip), "r") as inner:
                for entry in inner.namelist():
                    zf.writestr(f"budget/{entry}", inner.read(entry))
        buf.seek(0)
        return buf.read()
