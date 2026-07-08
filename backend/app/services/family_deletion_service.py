"""
Self-serve whole-family deletion (WS-DEL / compliance).

Flow (parent-only, re-authenticated):
 1. Re-auth: password accounts must re-enter their password; Google-only
    accounts (no password hash) must type the exact family name.
 2. If a PayPal subscription is live (or a checkout is staged), cancel it at
    PayPal first — best-effort, deletion proceeds even if PayPal errors.
 3. Collect the family's uploaded files on disk (gig/task proofs, receipt
    drafts) AND its scanned-receipt object keys in GCS
    (BudgetTransaction.receipt_image_path) BEFORE the rows disappear, then
    remove them after the DB delete. GCS removal is best-effort like the
    PayPal step — an unset bucket or a GCS error never blocks deletion.
 4. Delete the family row. ORM cascade (Family.members et al.) removes users
    and their owned rows; DB-level ON DELETE CASCADE covers the rest.
    family_invitations is the one table with NO delete rule on its FKs
    (families + users), so it is deleted explicitly first.
 5. Sessions: JWTs die with the user rows — get_current_user re-reads the
    user on every request, so deleted users 401 immediately (no separate
    Redis session store exists).

An anonymized audit line (UUIDs + counts only, no names/emails) is logged.
"""

import asyncio
import logging
import os
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenException, ValidationException
from app.core.security import verify_password
from app.models import FamilyInvitation, User
from app.models.budget import BudgetReceiptDraft, BudgetTransaction
from app.models.family import Family
from app.models.gig import GigClaim
from app.models.subscription import FamilySubscription
from app.models.task_assignment import TaskAssignment
from app.services.family_service import FamilyService

logger = logging.getLogger(__name__)

# Canonical upload locations inside the backend container. Keep in sync with
# app/api/routes/uploads.py (gig proofs) and
# app/services/budget/receipt_scanner_service.py (receipt drafts).
UPLOADS_ROOT = "/app/uploads"
GIG_PROOFS_DIR = os.path.join(UPLOADS_ROOT, "gig-proofs")
RECEIPT_DRAFTS_DIR = os.path.join(UPLOADS_ROOT, "receipt-drafts")

# Subscription states whose PayPal billing agreement may still charge.
_LIVE_SUBSCRIPTION_STATUSES = ("active", "past_due", "payment_failed", "pending")


class FamilyDeletionService:
    """Orchestrates permanent deletion of a family and all its data."""

    @staticmethod
    def verify_reauth(
        user: User,
        family: Family,
        password: Optional[str],
        confirm_name: Optional[str],
    ) -> None:
        """Re-authenticate the requesting parent before deletion.

        Password accounts re-enter their password. Google-only accounts
        (``password_hash`` is NULL) type the family name instead.
        """
        if user.password_hash:
            if not password or not verify_password(password, user.password_hash):
                raise ForbiddenException("Incorrect password")
        else:
            expected = (family.name or "").strip().casefold()
            given = (confirm_name or "").strip().casefold()
            if not given or given != expected:
                raise ValidationException(
                    "Family name confirmation does not match"
                )

    @staticmethod
    async def _cancel_paypal_subscriptions(db: AsyncSession, family_id: UUID) -> None:
        """Cancel live + staged PayPal subscriptions at PayPal (best-effort)."""
        sub = (
            await db.execute(
                select(FamilySubscription).where(
                    FamilySubscription.family_id == family_id
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            return

        from app.services.paypal_service import PayPalService

        to_cancel = set()
        if sub.paypal_subscription_id and sub.status in _LIVE_SUBSCRIPTION_STATUSES:
            to_cancel.add(sub.paypal_subscription_id)
        # A staged upgrade/downgrade checkout holds its own PayPal id.
        if sub.pending_paypal_subscription_id:
            to_cancel.add(sub.pending_paypal_subscription_id)

        for paypal_id in to_cancel:
            try:
                await asyncio.to_thread(
                    PayPalService.cancel_subscription,
                    paypal_id,
                    reason="Family account deleted",
                )
            except Exception as exc:  # best-effort: deletion must proceed
                logger.warning(
                    "PayPal cancel failed during family deletion (%s): %s",
                    paypal_id,
                    exc,
                )

    @staticmethod
    async def _collect_upload_paths(db: AsyncSession, family_id: UUID) -> List[str]:
        """Absolute on-disk paths of the family's uploaded files.

        Collected BEFORE the DB rows are deleted. Paths are rebuilt from the
        basename against the known upload roots (no traversal possible).
        """
        paths: List[str] = []

        proof_urls = (
            await db.execute(
                select(TaskAssignment.proof_image_url).where(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.proof_image_url.is_not(None),
                )
            )
        ).scalars().all()
        claim_urls = (
            await db.execute(
                select(GigClaim.proof_image_url).where(
                    GigClaim.family_id == family_id,
                    GigClaim.proof_image_url.is_not(None),
                )
            )
        ).scalars().all()
        for url in [*proof_urls, *claim_urls]:
            if url and url.startswith("/uploads/gig-proofs/"):
                paths.append(os.path.join(GIG_PROOFS_DIR, os.path.basename(url)))

        draft_ids = (
            await db.execute(
                select(BudgetReceiptDraft.id).where(
                    BudgetReceiptDraft.family_id == family_id,
                    BudgetReceiptDraft.image_url.is_not(None),
                )
            )
        ).scalars().all()
        for draft_id in draft_ids:
            paths.append(os.path.join(RECEIPT_DRAFTS_DIR, f"{draft_id}.jpg"))

        return paths

    @staticmethod
    async def _collect_gcs_receipt_paths(
        db: AsyncSession, family_id: UUID
    ) -> List[str]:
        """GCS object keys of the family's scanned receipt images.

        BudgetTransaction.receipt_image_path stores the object key
        (``<family_id>/<txn_id>.<ext>``) under GCS_RECEIPT_BUCKET. Collected
        BEFORE the DB rows are deleted.
        """
        return list(
            (
                await db.execute(
                    select(BudgetTransaction.receipt_image_path).where(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.receipt_image_path.is_not(None),
                    )
                )
            ).scalars().all()
        )

    @staticmethod
    def _delete_gcs_receipts(paths: List[str]) -> int:
        """Best-effort blob deletion of scanned receipts (sync — threadpool it).

        If GCS_RECEIPT_BUCKET is unset (e.g. on-prem), the keys point at
        nothing reachable from this environment; skip without failing.
        """
        if not paths:
            return 0
        if not settings.GCS_RECEIPT_BUCKET:
            logger.warning(
                "Family deletion: %d receipt image(s) referenced in GCS but "
                "GCS_RECEIPT_BUCKET is not configured; skipping blob deletion.",
                len(paths),
            )
            return 0

        from app.services.storage.gcs_receipt_service import GCSReceiptStorage

        removed = 0
        for path in paths:
            try:
                GCSReceiptStorage.delete(path)
                removed += 1
            except Exception as exc:  # best-effort: deletion must proceed
                logger.warning(
                    "GCS receipt delete failed during family deletion (%s): %s",
                    path,
                    exc,
                )
        return removed

    @staticmethod
    def _delete_files(paths: List[str]) -> int:
        removed = 0
        for path in paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            except OSError as exc:
                logger.warning("Could not remove upload %s: %s", path, exc)
        return removed

    @classmethod
    async def delete_family(
        cls,
        db: AsyncSession,
        *,
        family_id: UUID,
        requesting_user: User,
        password: Optional[str] = None,
        confirm_name: Optional[str] = None,
    ) -> None:
        """Permanently delete the caller's family and every row it owns."""
        family = await FamilyService.get_family(db, family_id)
        cls.verify_reauth(requesting_user, family, password, confirm_name)

        # Capture audit facts before the rows (incl. requesting_user) vanish.
        requester_id = requesting_user.id
        member_count = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.family_id == family_id)
            )
        ).scalar() or 0

        await cls._cancel_paypal_subscriptions(db, family_id)

        upload_paths = await cls._collect_upload_paths(db, family_id)
        gcs_receipt_paths = await cls._collect_gcs_receipt_paths(db, family_id)

        # family_invitations FKs (families.id, users.id) carry NO delete rule
        # in the deployed schema — remove them explicitly so neither the ORM
        # user cascade nor the family delete hits an FK violation.
        await db.execute(
            delete(FamilyInvitation).where(FamilyInvitation.family_id == family_id)
        )

        # ORM cascade: members (users) + their owned rows via relationship
        # cascades; everything else via DB-level ON DELETE CASCADE.
        await FamilyService.delete_family(db, family_id)

        # Only after the DB commit succeeded do the files go away.
        removed = cls._delete_files(upload_paths)
        gcs_removed = await asyncio.to_thread(
            cls._delete_gcs_receipts, gcs_receipt_paths
        )

        # Anonymized audit line: identifiers + counts only.
        logger.info(
            "family_deleted family_id=%s members=%d uploads_removed=%d "
            "gcs_receipts_removed=%d requested_by_user_id=%s",
            family_id,
            member_count,
            removed,
            gcs_removed,
            requester_id,
        )
