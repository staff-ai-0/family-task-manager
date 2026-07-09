"""
Self-serve whole-family deletion (WS-DEL / compliance) — two-phase soft delete.

Phase 1 — SOFT delete (``delete_family``, parent-only, re-authenticated),
synchronous with the DELETE /api/families/me request:
 1. Re-auth: password accounts must re-enter their password; Google-only
    accounts (no password hash) must type the exact family name.
 2. If the family has ANY PayPal subscription id (live, in dunning, or even
    locally "terminal" — local status can lie when a /cancel PayPal call
    failed) or a staged checkout, cancel it at PayPal now — best-effort,
    deletion proceeds even if PayPal errors — so nothing keeps billing during
    the grace window.
 3. Stamp ``families.deleted_at`` and every member's ``users.deleted_at``, and
    bump each member's ``token_version``. The account is now closed: auth 401s
    every member (get_current_user re-reads the user each request; the
    token_version bump kills outstanding refresh tokens). No separate Redis
    session store exists. NO data is deleted — every row survives so the
    compliance export taken beforehand stays valid and a mistaken deletion is
    recoverable until the purge.
 4. Uploaded files on disk + GCS receipt blobs are deliberately NOT touched
    here — that cleanup happens at purge time.

Phase 2 — HARD purge (``purge_expired`` → ``_hard_purge_family``), run by the
daily purge sweep (scheduler leader only) once ``deleted_at`` is older than
``PURGE_RETENTION_DAYS``:
 5. Collect the family's uploaded files on disk (gig/task proofs, receipt
    drafts) AND its scanned-receipt object keys in GCS
    (BudgetTransaction.receipt_image_path) BEFORE the rows disappear, then
    remove them after the DB delete. GCS removal is best-effort — an unset
    bucket or a GCS error never blocks the purge.
 6. Delete the family row. ORM cascade (Family.members et al.) removes users
    and their owned rows; DB-level ON DELETE CASCADE covers the rest.
    family_invitations is the one table with NO delete rule on its FKs
    (families + users), so it is deleted explicitly first.

Anonymized audit lines (UUIDs + counts only, no names/emails) are logged for
both phases.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
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
UPLOADS_ROOT = settings.UPLOADS_ROOT
GIG_PROOFS_DIR = os.path.join(UPLOADS_ROOT, "gig-proofs")
RECEIPT_DRAFTS_DIR = os.path.join(UPLOADS_ROOT, "receipt-drafts")

class FamilyDeletionService:
    """Orchestrates soft-delete + eventual hard purge of a family's data."""

    # Grace window between soft delete (deleted_at stamped) and the hard purge.
    # Data is fully retained for this many days so a mistaken account closure is
    # recoverable and the compliance export stays valid.
    PURGE_RETENTION_DAYS = 30

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
    async def _cancel_paypal_subscriptions(
        db: AsyncSession, family_id: UUID
    ) -> List[str]:
        """Cancel every possibly-still-billing PayPal subscription (best-effort).

        Cancels ANY paypal_subscription_id regardless of local status, plus
        any staged checkout id. Local status is deliberately NOT trusted here:
        /cancel swallows a PayPal cancel failure with a warning and the sweep
        later flips the row to 'cancelled' locally, so a "terminal" local
        status can hide a PayPal agreement that is still billing. Cancelling
        an already-cancelled/expired sub at PayPal is a harmless best-effort
        failure that lands in the existing failed-ids audit trail. Deletion
        is a user right and must proceed even if PayPal errors — failures are
        logged loudly and returned so the operator audit line records the ids
        that may keep charging.
        """
        sub = (
            await db.execute(
                select(FamilySubscription).where(
                    FamilySubscription.family_id == family_id
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            return []

        from app.services.paypal_service import PayPalService

        to_cancel = set()
        if sub.paypal_subscription_id:
            to_cancel.add(sub.paypal_subscription_id)
        # A staged upgrade/downgrade checkout holds its own PayPal id.
        if sub.pending_paypal_subscription_id:
            to_cancel.add(sub.pending_paypal_subscription_id)

        failed: List[str] = []
        for paypal_id in to_cancel:
            try:
                await asyncio.to_thread(
                    PayPalService.cancel_subscription,
                    paypal_id,
                    reason="Family account deleted",
                )
            except Exception as exc:  # best-effort: deletion must proceed
                failed.append(paypal_id)
                logger.error(
                    "PayPal cancel failed during family deletion (%s) — the "
                    "agreement may keep charging; operator follow-up needed: %s",
                    paypal_id,
                    exc,
                )
        return failed

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
        """Soft-delete the caller's family (Phase 1).

        Stamps ``deleted_at`` on the family + every member, bumps each member's
        ``token_version`` (kills refresh tokens), and cancels PayPal so nothing
        keeps billing. NO data is removed and NO files are touched — every row
        survives ``PURGE_RETENTION_DAYS`` so the compliance export stays valid
        and a mistaken closure is recoverable. The daily purge sweep does the
        actual hard delete once the grace window elapses.
        """
        family = await FamilyService.get_family(db, family_id)
        cls.verify_reauth(requesting_user, family, password, confirm_name)

        # Idempotent: a retried / double-submitted DELETE is a no-op once the
        # family is already closed (don't re-cancel PayPal or re-bump tokens).
        if family.deleted_at is not None:
            return

        # Capture audit facts.
        requester_id = requesting_user.id
        member_count = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.family_id == family_id)
            )
        ).scalar() or 0

        # Cancel PayPal NOW (best-effort) so no agreement keeps billing during
        # the grace window. Uploads/GCS cleanup is deferred to purge time.
        paypal_cancel_failures = await cls._cancel_paypal_subscriptions(
            db, family_id
        )

        now = datetime.now(timezone.utc)
        family.deleted_at = now
        # Close + invalidate every member in one statement: deleted_at 401s
        # access tokens on the next request (get_current_user), the
        # token_version bump invalidates outstanding refresh tokens.
        await db.execute(
            update(User)
            .where(User.family_id == family_id)
            .values(deleted_at=now, token_version=User.token_version + 1)
        )
        await db.commit()

        # Anonymized audit line: identifiers + counts only.
        # paypal_cancel_failed lists PayPal subscription ids the soft delete
        # could NOT cancel — those agreements may keep charging and need
        # manual operator follow-up at PayPal.
        logger.info(
            "family_soft_deleted family_id=%s members=%d requested_by_user_id=%s "
            "paypal_cancel_failed=%s purge_after_days=%d",
            family_id,
            member_count,
            requester_id,
            ",".join(paypal_cancel_failures) if paypal_cancel_failures else "-",
            cls.PURGE_RETENTION_DAYS,
        )

    @classmethod
    async def purge_expired(
        cls,
        db: AsyncSession,
        *,
        retention_days: Optional[int] = None,
    ) -> int:
        """Hard-purge every family soft-deleted longer than the grace window.

        Phase 2 — invoked by the daily purge sweep (scheduler leader only).
        Each family is purged in isolation: a single failure is logged and
        rolled back without aborting the rest of the batch. Returns the number
        of families hard-deleted.
        """
        days = cls.PURGE_RETENTION_DAYS if retention_days is None else retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        family_ids = (
            await db.execute(
                select(Family.id).where(
                    Family.deleted_at.is_not(None),
                    Family.deleted_at < cutoff,
                )
            )
        ).scalars().all()

        purged = 0
        for fid in family_ids:
            try:
                await cls._hard_purge_family(db, fid)
                purged += 1
            except Exception:
                logger.exception("Family purge failed for family_id=%s", fid)
                await db.rollback()
        return purged

    @classmethod
    async def _hard_purge_family(cls, db: AsyncSession, family_id: UUID) -> None:
        """Hard-delete a (soft-deleted) family and everything it owns.

        Removes on-disk uploads + GCS receipt blobs, then cascades the whole
        family out of the database. PayPal was already cancelled at soft-delete
        time, so it is NOT re-attempted here.
        """
        member_count = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.family_id == family_id)
            )
        ).scalar() or 0

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

        logger.info(
            "family_purged family_id=%s members=%d uploads_removed=%d "
            "gcs_receipts_removed=%d",
            family_id,
            member_count,
            removed,
            gcs_removed,
        )
