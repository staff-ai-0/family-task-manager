"""
Whole-family data export (WS-DEL / compliance).

Builds a ZIP of JSON dumps for every user-facing domain owned by ONE family:
users (sans credentials), tasks, gigs, points/cash, rewards, consequences,
budget (reusing the budget ExportService so that portion stays re-importable),
calendar, meals, shopping, chat + DMs, pets, notifications, Jarvis (chat
history, schedules, pending actions, MCP token metadata), kiosk devices,
onboarding events, subscription/usage, and A2A webhook config.

Uploaded images are NOT bundled — the archive carries a manifest of the file
paths instead (see uploads_manifest.json + README.txt inside the ZIP).

Multi-tenant: every query filters by the caller's family_id.

Size guard: the ZIP is built fully in memory, so export_family refuses
(HTTP 413) when a cheap pre-flight row count exceeds EXPORT_MAX_ROWS or the
finished archive exceeds EXPORT_MAX_BYTES. Follow-up if real family data ever
approaches these caps: rewrite as a streaming/chunked export instead of
raising the limits.
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from functools import reduce
from operator import add
from typing import Any, Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CalendarEvent,
    CashTransaction,
    Consequence,
    DMMessage,
    DMThread,
    FamilyA2AWebhook,
    FamilyChatMessage,
    FamilyChatReaction,
    FamilyInvitation,
    FamilySubscription,
    GigClaim,
    GigOffering,
    JarvisMcpToken,
    JarvisMessage,
    JarvisPendingAction,
    JarvisSchedule,
    KidBankAccount,
    KidPet,
    KioskDevice,
    MealPlanEntry,
    Notification,
    OnboardingEvent,
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
    UsageTracking,
    User,
    UserRewardGoal,
)
from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategorizationRule,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetCustomReport,
    BudgetGoal,
    BudgetPayee,
    BudgetReceiptDraft,
    BudgetRecurringTransaction,
    BudgetSavedFilter,
    BudgetTag,
    BudgetTransaction,
    BudgetTransactionItem,
    BudgetTransactionTag,
)
from app.services.budget.export_service import ExportService, _model_to_dict
from app.services.family_service import FamilyService

# Columns stripped from users.json — credentials/secrets are never exported.
_USER_EXCLUDED_COLUMNS = {"password_hash", "token_version"}

# invited_email belongs to a third party who may never have joined the family
# — masked out of the compliance export. invitation_code is a live bearer
# credential (valid 30 days, grants family membership) — never exported.
_INVITATION_EXCLUDED_COLUMNS = {"invited_email", "invitation_code"}

# Long-lived kiosk display credential — never exported.
_KIOSK_EXCLUDED_COLUMNS = {"token"}

# SHA-256 of the MCP bearer secret — credential material, never exported.
_MCP_TOKEN_EXCLUDED_COLUMNS = {"token_hash"}

# A2A webhook signing secret — credential material, never exported.
_A2A_EXCLUDED_COLUMNS = {"secret"}

# --- Size guard (the archive is built fully in memory) -----------------------
# Pre-flight cap on the summed row count of the high-cardinality tables.
EXPORT_MAX_ROWS = 250_000
# Hard cap on the finished ZIP byte size.
EXPORT_MAX_BYTES = 100 * 1024 * 1024  # 100 MiB

_EXPORT_TOO_LARGE_DETAIL = (
    "Family export is too large to generate as a single download. "
    "Please contact support for an assisted export."
)

# High-cardinality family_id-bearing tables counted by the pre-flight guard.
_PREFLIGHT_COUNT_MODELS = (
    BudgetTransaction,
    BudgetTransactionItem,
    CalendarEvent,
    CashTransaction,
    FamilyChatMessage,
    JarvisMessage,
    Notification,
    OnboardingEvent,
    TaskAssignment,
)

# --- Coverage bookkeeping -----------------------------------------------------
# Every family_id-bearing table must appear in exactly ONE of the two
# collections below; tests/test_family_delete_export.py enforces this against
# Base.metadata so a new family-scoped model cannot silently be left out of
# the export.
EXPORTED_FAMILY_TABLES: frozenset[str] = frozenset(
    model.__tablename__
    for model in (
        # exported directly by this service
        User,
        Task,
        TaskTemplate,
        TaskAssignment,
        GigOffering,
        GigClaim,
        CashTransaction,
        KidBankAccount,
        Reward,
        RewardRedemption,
        UserRewardGoal,
        Consequence,
        CalendarEvent,
        Recipe,
        MealPlanEntry,
        ShoppingList,
        FamilyChatMessage,
        DMThread,
        PupScoreSnapshot,
        Notification,
        FamilyInvitation,
        JarvisMessage,
        JarvisSchedule,
        JarvisPendingAction,
        JarvisMcpToken,
        KioskDevice,
        OnboardingEvent,
        FamilySubscription,
        UsageTracking,
        FamilyA2AWebhook,
        # exported via the re-importable budget backup (budget/budget_data.json)
        BudgetAccount,
        BudgetCategoryGroup,
        BudgetCategory,
        BudgetPayee,
        BudgetTransaction,
        BudgetAllocation,
        BudgetCategorizationRule,
        BudgetGoal,
        BudgetRecurringTransaction,
        # exported via budget/extras.json
        BudgetSavedFilter,
        BudgetTag,
        BudgetCustomReport,
        BudgetReceiptDraft,
        BudgetTransactionItem,
    )
)

# Deliberately excluded family_id-bearing tables → human-readable reason.
# Mirrored in the ZIP README so the exclusions are visible to the user.
EXCLUDED_FAMILY_TABLES: dict[str, str] = {
    "a2a_webhook_deliveries": (
        "internal webhook retry/delivery log; payloads duplicate budget "
        "transactions already exported under budget/"
    ),
    "budget_sync_state": (
        "legacy internal points<->budget sync bookkeeping (decommissioned "
        "sync engine); contains no user-authored content"
    ),
}

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

Exclusions / Exclusiones
------------------------

EN: The following are deliberately NOT included:
    - Credentials and secret material are never exported: password hashes,
      kiosk device tokens, MCP token hashes, webhook signing secrets, push
      notification device keys, and password-reset / email-verification
      tokens. (Non-secret metadata such as kiosk device names or MCP token
      labels IS included.)
    - a2a_webhook_deliveries: internal webhook retry/delivery log — its
      payloads duplicate budget transactions already exported under budget/.
    - budget_sync_state: legacy internal sync bookkeeping with no
      user-authored content.
    - Invitation records are included, but the invited person's email address
      is masked (it belongs to a third party) and the invitation code is
      stripped (it is a live join credential).
    Note: soft-deleted budget records (recycle bin) ARE included, in
    budget/recycle_bin.json — the re-importable budget backup only contains
    live records.

ES: Lo siguiente NO se incluye deliberadamente:
    - Las credenciales y material secreto nunca se exportan: hashes de
      contraseñas, tokens de dispositivos kiosko, hashes de tokens MCP,
      secretos de firma de webhooks, claves de notificaciones push y tokens
      de restablecimiento/verificación. (Los metadatos no secretos, como el
      nombre del kiosko o la etiqueta del token MCP, SÍ se incluyen.)
    - a2a_webhook_deliveries: registro interno de reintentos de webhooks —
      sus datos duplican transacciones ya exportadas en budget/.
    - budget_sync_state: contabilidad interna heredada de sincronización,
      sin contenido creado por el usuario.
    - Las invitaciones se incluyen, pero el correo del invitado se enmascara
      (pertenece a un tercero) y el código de invitación se elimina (es una
      credencial de acceso vigente).
    Nota: los registros de presupuesto borrados (papelera) SÍ se incluyen, en
    budget/recycle_bin.json — el respaldo reimportable solo contiene
    registros activos.
"""


async def _rows(db: AsyncSession, stmt) -> Sequence[Any]:
    return (await db.execute(stmt)).scalars().all()


def _dump(rows: Sequence[Any], exclude: set | None = None) -> list[dict]:
    return [_model_to_dict(r, exclude=exclude) for r in rows]


class FamilyExportService:
    """Builds the whole-family export ZIP."""

    @staticmethod
    async def _estimated_row_count(db: AsyncSession, family_id: UUID) -> int:
        """Cheap pre-flight estimate: summed COUNT(*) over the
        high-cardinality tables, in one round trip."""
        counts = [
            select(func.count())
            .select_from(model)
            .where(model.family_id == family_id)
            .scalar_subquery()
            for model in _PREFLIGHT_COUNT_MODELS
        ]
        counts.append(
            select(func.count())
            .select_from(PointTransaction)
            .join(User, PointTransaction.user_id == User.id)
            .where(User.family_id == family_id)
            .scalar_subquery()
        )
        counts.append(
            select(func.count())
            .select_from(DMMessage)
            .join(DMThread, DMMessage.thread_id == DMThread.id)
            .where(DMThread.family_id == family_id)
            .scalar_subquery()
        )
        total = (await db.execute(select(reduce(add, counts)))).scalar()
        return int(total or 0)

    @classmethod
    async def export_family(cls, db: AsyncSession, family_id: UUID) -> bytes:
        # Size guard: the whole archive is materialized in memory. Refuse
        # up-front when the family is clearly too large (streaming export is
        # the follow-up if this ever fires for legitimate data volumes).
        estimated_rows = await cls._estimated_row_count(db, family_id)
        if estimated_rows > EXPORT_MAX_ROWS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=_EXPORT_TOO_LARGE_DETAIL,
            )

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
        bank_accounts = await _rows(db, fam(KidBankAccount))
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
        jarvis_messages = await _rows(db, fam(JarvisMessage))
        jarvis_schedules = await _rows(db, fam(JarvisSchedule))
        jarvis_pending_actions = await _rows(db, fam(JarvisPendingAction))
        jarvis_mcp_tokens = await _rows(db, fam(JarvisMcpToken))
        kiosk_devices = await _rows(db, fam(KioskDevice))
        onboarding_events = await _rows(db, fam(OnboardingEvent))
        subscriptions = await _rows(db, fam(FamilySubscription))
        usage_tracking = await _rows(db, fam(UsageTracking))
        a2a_webhooks = await _rows(db, fam(FamilyA2AWebhook))

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
        txn_items = await _rows(db, fam(BudgetTransactionItem))

        # Soft-deleted (recycle-bin) budget rows. The re-importable budget
        # backup (budget/budget_data.json) filters deleted_at IS NULL, so
        # without this dump recycle-bin data would silently vanish from a
        # compliance export — and transaction_items above could reference
        # transactions absent from the archive.
        recycle_bin: dict[str, Any] = {}
        for key, model in (
            ("category_groups", BudgetCategoryGroup),
            ("categories", BudgetCategory),
            ("accounts", BudgetAccount),
            ("transactions", BudgetTransaction),
        ):
            deleted_rows = await _rows(
                db, fam(model).where(model.deleted_at.is_not(None))
            )
            recycle_bin[key] = _dump(deleted_rows)

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
            "bank/kid_bank_accounts.json": _dump(bank_accounts),
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
            "jarvis/messages.json": _dump(jarvis_messages),
            "jarvis/schedules.json": _dump(jarvis_schedules),
            "jarvis/pending_actions.json": _dump(jarvis_pending_actions),
            "jarvis/mcp_tokens.json": _dump(
                jarvis_mcp_tokens, exclude=_MCP_TOKEN_EXCLUDED_COLUMNS
            ),
            "kiosk/devices.json": _dump(
                kiosk_devices, exclude=_KIOSK_EXCLUDED_COLUMNS
            ),
            "onboarding_events.json": _dump(onboarding_events),
            "subscription/subscription.json": _dump(subscriptions),
            "subscription/usage_tracking.json": _dump(usage_tracking),
            "a2a/webhook_config.json": _dump(
                a2a_webhooks, exclude=_A2A_EXCLUDED_COLUMNS
            ),
            "budget/extras.json": {
                "saved_filters": _dump(saved_filters),
                "tags": _dump(tags),
                "transaction_tags": _dump(txn_tags),
                "custom_reports": _dump(custom_reports),
                "receipt_drafts": _dump(receipt_drafts),
                "transaction_items": _dump(txn_items),
            },
            "budget/recycle_bin.json": recycle_bin,
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

        data = buf.getvalue()
        # Backstop for anything the row estimate missed (e.g. a few huge
        # JSON/Text payloads): never ship an archive past the byte cap.
        if len(data) > EXPORT_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=_EXPORT_TOO_LARGE_DETAIL,
            )
        return data
