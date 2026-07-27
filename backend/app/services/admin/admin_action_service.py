"""The bounded set of write actions an operator may perform.

Every method reuses an existing service rather than writing raw SQL, and
stages its audit row on the SAME session as the mutation. On the happy path
the mutation and the "ok" audit row land in exactly one commit; if that
commit (or the mutation itself) raises, the whole attempt is rolled back —
undoing the mutation together with the audit row that was staged alongside
it — and a best-effort "error" audit row is staged and committed in its
place. So a rolled-back action can never leave an "ok" audit row behind, and
a failed action still leaves a record of the failure rather than nothing at
all. "Best-effort" is deliberate: see ``_record_failure`` — if the recovery
attempt itself fails, the client still gets the original error, not a crash.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import FamilyAppException
from app.core.modules import TOGGLABLE_MODULES
from app.models.family import Family
from app.models.user import User
from app.services.admin.operator_audit_service import OperatorAuditService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

# Deactivating a user also bulk-cancels their PENDING/CLAIMED/OVERDUE
# assignments; reactivating does NOT restore them. Surfaced to the operator
# rather than hidden, because the support case usually cares.
DEACTIVATE_WARNING = (
    "Deactivating also cancels this user's pending, claimed and overdue "
    "assignments. Reactivating does not restore them."
)


async def _load_family(db: AsyncSession, family_id: UUID) -> Family:
    family = await db.scalar(select(Family).where(Family.id == family_id))
    if family is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return family


async def _load_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


async def _record_failure(
    db: AsyncSession,
    *,
    operator_id: UUID,
    operator_email: str,
    action: str,
    target_family_id: Optional[UUID],
    target_user_id: Optional[UUID],
    params: dict,
    exc: Exception,
) -> None:
    """Roll back the failed action, then best-effort stage+commit an
    ``error`` audit row for it.

    ``operator_id``/``operator_email`` must be plain values captured BEFORE
    the caller's try block — never the live ``operator`` ORM object.
    ``db.rollback()`` expires every object on this session (not just the
    ones the failed mutation touched), so `operator` — loaded earlier, on
    this same session, by ``require_superadmin`` — is expired too by the
    time we get here. Re-reading an expired attribute on an async ORM
    object outside an explicit awaited refresh raises
    ``sqlalchemy.exc.MissingGreenlet``; refreshing it would add a second
    unguarded round of IO with its own failure modes (a dead connection, or
    the operator row itself being concurrently deleted) that could pre-empt
    the audit write entirely. Passing a detached stand-in with just the two
    fields ``OperatorAuditService.record`` actually reads avoids all of
    that — no second query, nothing left to expire.

    This whole recovery sequence is itself best-effort: if the rollback, the
    staging, or the recovery commit fails too (e.g. the connection is
    genuinely gone), that secondary failure is logged and swallowed rather
    than raised — the caller still raises the ORIGINAL exception to the
    client either way, so a broken audit write never turns a clear 500 into
    a confusing, unrelated one. The trade-off is explicit: in that
    (rare, catastrophic) case there is no audit row, but the operator still
    gets a coherent error response, and the failure is on the server log.
    """
    try:
        await db.rollback()
        OperatorAuditService.record(
            db,
            actor=SimpleNamespace(id=operator_id, email=operator_email),
            action=action,
            target_family_id=target_family_id,
            target_user_id=target_user_id,
            params=params,
            result="error",
            error=str(exc),
        )
        await db.commit()
    except Exception:
        logger.error(
            "admin action %s: failed to write error-audit row after %r",
            action,
            exc,
            exc_info=True,
        )


class AdminActionService:
    """Operator write actions."""

    @staticmethod
    async def comp_plus_month(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        days: int,
        reason: str,
    ) -> dict:
        """Grant free Plus for ``days`` from now.

        Writes families.referral_bonus_until directly and ABSOLUTELY, rather
        than calling ReferralService._grant_referral_month — that helper is
        private, does not commit, stacks +30d per invocation, and is Plus-only.
        An operator comp must be idempotent in intent: "Plus until date X".
        """
        operator_id, operator_email = operator.id, operator.email
        family = await _load_family(db, family_id)
        until = datetime.now(timezone.utc) + timedelta(days=days)
        family.referral_bonus_until = until
        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="family.comp_plus",
                target_family_id=family_id,
                params={"days": days, "reason": reason, "until": until.isoformat()},
            )
            await db.commit()
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="family.comp_plus",
                target_family_id=family_id,
                target_user_id=None,
                params={"days": days, "reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"comp plus failed: {exc}"
            ) from exc
        return {"referral_bonus_until": until.isoformat()}

    @staticmethod
    async def set_family_active(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        suspended: bool,
        reason: str,
    ) -> dict:
        """Suspend or reinstate a whole family.

        Deliberately NOT implemented via the soft-delete tombstone: that would
        conflate abuse suspension with account closure and arm the 30-day
        purge sweep against a family the operator may want to reinstate.

        Refuses to suspend the OPERATOR's OWN family: per CLAUDE.md the sole
        superadmin is a PARENT in the real production family, and the
        families list puts his own family in the same table as everyone
        else's, one click from Suspend. There is no in-app recovery from
        that — the frontend guard 404s /admin and password login refuses —
        recovery would need psql on the prod host. Reinstating (suspended=
        False) is always allowed; it's the recovery direction.
        """
        if suspended and family_id == operator.family_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "cannot suspend your own family — this would lock you out "
                "with no in-app recovery",
            )
        operator_id, operator_email = operator.id, operator.email
        family = await _load_family(db, family_id)
        family.is_active = not suspended
        action = "family.suspend" if suspended else "family.unsuspend"
        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action=action,
                target_family_id=family_id,
                params={"reason": reason},
            )
            await db.commit()
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action=action,
                target_family_id=family_id,
                target_user_id=None,
                params={"reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"suspend failed: {exc}"
            ) from exc
        return {"is_active": not suspended}

    @staticmethod
    async def set_modules(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        enabled_modules: Optional[list[str]],
        reason: str,
    ) -> dict:
        """Rewrite a family's module registry.

        ``None`` restores the default, which means ALL modules on — not none.
        """
        if enabled_modules is not None:
            unknown = set(enabled_modules) - set(TOGGLABLE_MODULES)
            if unknown:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"unknown modules: {sorted(unknown)}",
                )
        operator_id, operator_email = operator.id, operator.email
        family = await _load_family(db, family_id)
        family.enabled_modules = enabled_modules
        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="family.set_modules",
                target_family_id=family_id,
                params={"enabled_modules": enabled_modules, "reason": reason},
            )
            await db.commit()
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="family.set_modules",
                target_family_id=family_id,
                target_user_id=None,
                params={"enabled_modules": enabled_modules, "reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"set modules failed: {exc}"
            ) from exc
        return {"enabled_modules": enabled_modules}

    @staticmethod
    async def set_user_active(
        db: AsyncSession,
        *,
        operator: User,
        user_id: UUID,
        active: bool,
        reason: str,
    ) -> dict:
        """Deactivate or reactivate one member, via AuthService.

        AuthService.activate_user/deactivate_user are called with
        commit=False so the member mutation — and, on deactivate, the bulk
        cancellation of PENDING/CLAIMED/OVERDUE assignments performed inside
        it — lands in the SAME transaction as the audit row below. An
        earlier version let AuthService commit on its own before the audit
        row was even staged: if the second (audit) commit then failed, the
        member stayed permanently deactivated with zero audit trail.
        `user_family_id`/`operator_id`/`operator_email` are captured into
        local variables up front, before any rollback can happen — see
        ``_record_failure`` for why the failure path must not re-read
        attributes off `user` or `operator` themselves.

        Refuses to deactivate the OPERATOR's OWN account, for the same
        no-in-app-recovery reason as ``set_family_active`` refusing to
        suspend the operator's own family. Reactivating (active=True) is
        always allowed; it's the recovery direction.
        """
        if not active and user_id == operator.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "cannot deactivate your own account — this would lock you "
                "out with no in-app recovery",
            )
        from app.services.auth_service import AuthService

        user = await _load_user(db, user_id)
        user_family_id = user.family_id
        operator_id, operator_email = operator.id, operator.email
        action = "user.activate" if active else "user.deactivate"
        try:
            if active:
                await AuthService.activate_user(db, user.id, commit=False)
            else:
                await AuthService.deactivate_user(db, user.id, commit=False)
            OperatorAuditService.record(
                db,
                actor=operator,
                action=action,
                target_family_id=user_family_id,
                target_user_id=user_id,
                params={"reason": reason},
            )
            await db.commit()
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action=action,
                target_family_id=user_family_id,
                target_user_id=user_id,
                params={"reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, f"set active failed: {exc}"
            ) from exc
        return {
            "is_active": active,
            "warning": None if active else DEACTIVATE_WARNING,
        }

    @staticmethod
    async def resend_verification(
        db: AsyncSession, *, operator: User, user_id: UUID, reason: str
    ) -> dict:
        """Send a fresh email-verification link.

        Routed through ``_record_failure`` on error, same as every other
        action, so the recovery (stage error row + commit) is guarded rather
        than a bare, unguarded ``db.commit()``: if the exception that landed
        us here WAS itself a DBAPI error (e.g. the internal commit inside
        EmailService.create_verification_token failed), the session is
        already in a failed transaction state and a second bare commit
        raises PendingRollbackError — turning the intended 502 into an
        unrelated 500 and losing the audit row with it.

        ``_record_failure`` opens with ``await db.rollback()`` before
        staging the error row. That is safe here even though the
        verification token is committed in ITS OWN, separate transaction
        (see create_verification_token): if the token's commit is what
        failed, the rollback is exactly the cleanup needed before the
        session can commit again; if instead the token committed fine and
        only the later network send raised, the rollback has nothing
        pending to discard and the already-durable token row is untouched.
        """
        user = await _load_user(db, user_id)
        user_family_id = user.family_id
        operator_id, operator_email = operator.id, operator.email
        try:
            sent = await EmailService.send_verification_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="user.resend_verification",
                target_family_id=user_family_id,
                target_user_id=user_id,
                params={"reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"email send failed: {exc}"
            ) from exc

        OperatorAuditService.record(
            db,
            actor=operator,
            action="user.resend_verification",
            target_family_id=user.family_id,
            target_user_id=user.id,
            params={"reason": reason},
            result="ok" if sent else "error",
            error=None if sent else "email provider returned false",
        )
        await db.commit()
        return {"sent": bool(sent)}

    @staticmethod
    async def trigger_password_reset(
        db: AsyncSession, *, operator: User, user_id: UUID, reason: str
    ) -> dict:
        """Send a reset link AND invalidate outstanding sessions.

        EmailService.send_password_reset_email does not bump token_version —
        the public route does. An operator reset that skipped the bump would
        leave a compromised session alive, which is usually the whole reason
        support is resetting the password.

        Routed through ``_record_failure`` on error, same as resend_
        verification and every other action — see its docstring for why a
        bare, unguarded ``db.commit()`` here is unsafe (a DBAPI error from
        the internal commit inside EmailService.create_password_reset_token
        would leave the session in a failed transaction state) and why
        ``_record_failure``'s leading ``await db.rollback()`` is still
        correct even though the reset token itself commits in ITS OWN,
        separate transaction. The second-order consequence of the bug this
        fixes: without a guarded recovery, a failure here could leave a live
        reset link (its token already committed and mailed) with
        token_version un-bumped and no audit trail — the token_version bump
        below only ever runs on the success path, so that gap is closed by
        making sure the FAILURE path is always durably recorded, not by
        moving the bump.
        """
        user = await _load_user(db, user_id)
        user_family_id = user.family_id
        operator_id, operator_email = operator.id, operator.email
        try:
            sent = await EmailService.send_password_reset_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="user.password_reset",
                target_family_id=user_family_id,
                target_user_id=user_id,
                params={"reason": reason},
                exc=exc,
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"email send failed: {exc}"
            ) from exc

        user.token_version = (user.token_version or 0) + 1
        OperatorAuditService.record(
            db,
            actor=operator,
            action="user.password_reset",
            target_family_id=user.family_id,
            target_user_id=user.id,
            params={"reason": reason},
            result="ok" if sent else "error",
            error=None if sent else "email provider returned false",
        )
        await db.commit()
        return {"sent": bool(sent), "sessions_invalidated": True}

    @staticmethod
    async def cancel_deletion(
        db: AsyncSession, *, operator: User, family_id: UUID, reason: str
    ) -> dict:
        """Reinstate a family inside its 30-day recovery window.

        ``operator_id``/``operator_email`` are captured into locals BEFORE the
        try, and the error path uses ``_record_failure`` rather than a
        hand-rolled ``OperatorAuditService.record(db, actor=operator, ...)`` —
        see ``_record_failure``'s docstring: db.rollback() expires `operator`
        (loaded earlier, on this same session, by require_superadmin), so
        reading `.id`/`.email` off it after rollback raises MissingGreenlet.

        FamilyDeletionService.cancel_deletion itself raises HTTPException for
        its own domain checks (not-pending / retention-window), but the
        FamilyService.get_family lookup it calls first raises NotFoundException
        (a FamilyAppException, not HTTPException) for a nonexistent family_id —
        the same HTTPException/FamilyAppException split as undo_chore_approval,
        so both are caught here too.
        """
        from app.services.family_deletion_service import FamilyDeletionService

        operator_id, operator_email = operator.id, operator.email
        try:
            result = await FamilyDeletionService.cancel_deletion(
                db, family_id=family_id
            )
        except (HTTPException, FamilyAppException) as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="family.cancel_deletion",
                target_family_id=family_id,
                target_user_id=None,
                params={"reason": reason},
                exc=exc,
            )
            raise

        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.cancel_deletion",
            target_family_id=family_id,
            params={"reason": reason},
        )
        await db.commit()
        return result

    @staticmethod
    async def release_paycheck(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        kid_id: UUID,
        week_of: date,
        reason: str,
    ) -> dict:
        """Force-release a stuck chore paycheck for one kid and week.

        Idempotent per (kid, week) inside BankService. released_by carries the
        OPERATOR's id — cash_transactions.created_by is a nullable FK with
        ON DELETE SET NULL, so a cross-family actor is valid at the DB level
        and truthful in the ledger.

        BankService.release_chore_paycheck commits exactly once, at the very
        end, after every mutation (verified: its ledger-writing helpers —
        CashService.credit_split_rows / credit_single_jar — are documented
        "no commit, caller commits"; PointsService.award_assignment_completion
        is not on this path). So the audit row is staged BEFORE calling it,
        not after: that single internal commit then persists the mutation and
        the audit row together, atomically, with no separate commit needed
        here. If release_chore_paycheck raises before reaching its commit,
        nothing (mutation or staged row) is durable, the except below rolls
        back and stages a fresh "error" row instead — there is no window
        where an "ok" row survives a failed release. ``operator_id``/
        ``operator_email`` are captured into locals BEFORE the try for the
        same reason as ``cancel_deletion`` above.
        """
        from app.services.bank_service import BankService

        kid = await _load_user(db, kid_id)
        if kid.family_id != family_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        operator_id, operator_email = operator.id, operator.email
        params = {"week_of": week_of.isoformat(), "reason": reason}
        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="bank.release_paycheck",
                target_family_id=family_id,
                target_user_id=kid_id,
                params=params,
            )
            result = await BankService.release_chore_paycheck(
                db,
                kid,
                family_id,
                week_of,
                entitled=True,
                released_by=operator.id,
            )
        except HTTPException as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="bank.release_paycheck",
                target_family_id=family_id,
                target_user_id=kid_id,
                params=params,
                exc=exc,
            )
            raise

        return result

    @staticmethod
    async def undo_chore_approval(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        assignment_id: UUID,
        reason: str,
    ) -> dict:
        """Revert a mistakenly-approved CHORE back to PENDING.

        TaskAssignmentService.patch_assignment claws the points back and
        clears the grade — which matters, because a leftover `partial` grade
        keeps haircutting the kid's payday math. It REFUSES bonus and gig
        reversals; that refusal is surfaced to the operator verbatim.

        patch_assignment signals that refusal (and any other domain rule
        violation — cross-family reassignment, an unknown assignment) via
        FamilyAppException subclasses (ValidationException/ForbiddenException/
        NotFoundException from app.core.exceptions), NOT FastAPI's
        HTTPException — those two exception families are unrelated in this
        codebase (see app/core/exception_handlers.py), so both are caught
        here to guarantee the audit row; the original exception is
        re-raised as-is and the existing global handler for its exact type
        maps it to the right status code for the client.

        patch_assignment commits exactly once, at the very end, after every
        mutation (its points clawback — PointsService.award_assignment_
        completion — is documented "caller commits", i.e. no commit of its
        own). So, like release_paycheck, the audit row is staged BEFORE
        calling patch_assignment: its single internal commit then persists
        the mutation and the audit row together. The one value the OK row
        needs that isn't known from the request — target_user_id, i.e. who
        the assignment belongs to — is fetched with a cheap read-only lookup
        BEFORE staging (pre-existing data, not something the mutation
        computes), rather than deferred to patch_assignment's return value,
        which would arrive only after its commit has already happened.
        ``operator_id``/``operator_email`` are captured into locals BEFORE
        the try for the same reason as ``cancel_deletion`` above.
        """
        from app.models.task_assignment import AssignmentStatus, TaskAssignment
        from app.services.task_assignment_service import TaskAssignmentService

        operator_id, operator_email = operator.id, operator.email
        assigned_to = await db.scalar(
            select(TaskAssignment.assigned_to).where(
                TaskAssignment.id == assignment_id,
                TaskAssignment.family_id == family_id,
            )
        )
        params = {"assignment_id": str(assignment_id), "reason": reason}
        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="assignment.undo_approval",
                target_family_id=family_id,
                target_user_id=assigned_to,
                params=params,
            )
            await TaskAssignmentService.patch_assignment(
                db,
                assignment_id,
                family_id,
                status=AssignmentStatus.PENDING,
            )
        except (HTTPException, FamilyAppException) as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="assignment.undo_approval",
                target_family_id=family_id,
                target_user_id=assigned_to,
                params=params,
                exc=exc,
            )
            raise

        return {"assignment_id": str(assignment_id), "status": "pending"}

    @staticmethod
    async def restore_recycled(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        item_type: str,
        item_id: UUID,
        reason: str,
    ) -> dict:
        """Restore one soft-deleted budget row from the recycle bin.

        Every RecycleBinService.restore_* commits exactly once, at the very
        end, after its mutations (each ends in ``await db.commit()`` followed
        only by a read-only ``db.refresh()``) — so, like release_paycheck and
        undo_chore_approval, the audit row is staged BEFORE calling the
        restorer and needs no separate commit of its own: the restorer's
        commit persists both together. The realistic failure mode here is an
        operator typo — an unknown item_type, or an item_id that doesn't
        exist / belongs to another family / is already live — and both are
        now audited: the unknown-item_type 422 never reaches a restorer (no
        mutation is possible), so it is recorded directly via
        ``_record_failure``; a downstream NotFoundException from any restorer
        is caught the same way.
        """
        from app.services.budget.recycle_bin_service import RecycleBinService

        restorers = {
            "transaction": RecycleBinService.restore_transaction,
            "account": RecycleBinService.restore_account,
            "category": RecycleBinService.restore_category,
            "category_group": RecycleBinService.restore_category_group,
        }
        operator_id, operator_email = operator.id, operator.email
        params = {"item_type": item_type, "item_id": str(item_id), "reason": reason}
        restore = restorers.get(item_type)
        if restore is None:
            exc = HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown item_type: {item_type}",
            )
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="budget.restore",
                target_family_id=family_id,
                target_user_id=None,
                params=params,
                exc=exc,
            )
            raise exc

        try:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="budget.restore",
                target_family_id=family_id,
                params=params,
            )
            await restore(db, item_id, family_id)
        except (HTTPException, FamilyAppException) as exc:
            await _record_failure(
                db,
                operator_id=operator_id,
                operator_email=operator_email,
                action="budget.restore",
                target_family_id=family_id,
                target_user_id=None,
                params=params,
                exc=exc,
            )
            raise

        return {"restored": True, "item_type": item_type}
