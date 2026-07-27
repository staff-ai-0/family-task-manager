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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
        """
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
        """
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

        NOTE on the missing rollback here: EmailService.create_verification_
        token commits internally (for every caller, not just this one) before
        the network send is even attempted, so by the time send_verification_
        email can raise, that token row is already durably committed on its
        own — a deliberate, pre-existing split outside this task's scope, not
        an oversight. There is nothing uncommitted on this session left to
        roll back at the point of failure, so staging the error audit row and
        committing it directly (no rollback first) is correct here.
        """
        user = await _load_user(db, user_id)
        try:
            sent = await EmailService.send_verification_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="user.resend_verification",
                target_family_id=user.family_id,
                target_user_id=user.id,
                params={"reason": reason},
                result="error",
                error=str(exc),
            )
            await db.commit()
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

        NOTE on the missing rollback here: same as resend_verification —
        EmailService.create_password_reset_token commits internally, for
        every caller, before the network send is attempted. That is a
        pre-existing, out-of-scope split, not an oversight: nothing is left
        uncommitted on this session at the point send_password_reset_email
        can raise, so there is nothing to roll back before staging the error
        audit row.
        """
        user = await _load_user(db, user_id)
        try:
            sent = await EmailService.send_password_reset_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="user.password_reset",
                target_family_id=user.family_id,
                target_user_id=user.id,
                params={"reason": reason},
                result="error",
                error=str(exc),
            )
            await db.commit()
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
