"""Notification service (W3.2).

Localized copy (launch i18n audit 2026-07-07): in-app/push notification
strings live in the keyed bilingual ``_COPY`` table below (mirrors
email_service's _COPY/_t). Callers should prefer ``create_localized(key=...)``
— it resolves the recipient's ``preferred_lang`` — and keep raw ``create()``
only for genuinely dynamic content (chat/DM/Jarvis message previews).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.notification import Notification, NotificationType as NT


# ---------------------------------------------------------------------------
# Bilingual copy — key → {type, title{es,en}, body{es,en}|None}
#
# Templates are str.format templates. Param values may themselves be
# per-language dicts ({"es": ..., "en": ...}) and are resolved before
# formatting (see render()).
# ---------------------------------------------------------------------------

_COPY = {
    # ── Core chore loop ────────────────────────────────────────────
    "task_assigned": {
        "type": NT.TASK_ASSIGNED,
        "title": {
            "es": "📋 Tienes {count} tareas nuevas",
            "en": "📋 You have {count} new chores",
        },
        "body": {
            "es": "Se asignaron tus tareas de la semana. Revisa tu tablero.",
            "en": "Your chores for the week were assigned. Check your board.",
        },
    },
    "task_assigned_one": {
        "type": NT.TASK_ASSIGNED,
        "title": {
            "es": "📋 Tienes una tarea nueva",
            "en": "📋 You have a new chore",
        },
        "body": {
            "es": "Se asignó tu tarea de la semana. Revisa tu tablero.",
            "en": "Your chore for the week was assigned. Check your board.",
        },
    },
    "task_due_today": {
        "type": NT.TASK_DUE,
        "title": {
            "es": "📋 Tienes {count} tareas hoy",
            "en": "📋 You have {count} chores today",
        },
        "body": {
            "es": "¡Complétalas para ganar puntos!",
            "en": "Complete them to earn points!",
        },
    },
    "task_due_today_one": {
        "type": NT.TASK_DUE,
        "title": {
            "es": "📋 Tienes 1 tarea hoy",
            "en": "📋 You have 1 chore today",
        },
        "body": {
            "es": "¡Complétala para ganar puntos!",
            "en": "Complete it to earn points!",
        },
    },
    # ── Bonus-task gigs (task_assignment_service) ──────────────────
    "gig_approved": {
        "type": NT.GIG_APPROVED,
        "title": {"es": "✅ +{pts} pts", "en": "✅ +{pts} pts"},
        "body": {
            "es": "'{title}' aprobada por tus papás.",
            "en": "'{title}' approved by parent.",
        },
    },
    "gig_approved_auto": {
        "type": NT.GIG_APPROVED,
        "title": {"es": "✅ +{pts} pts", "en": "✅ +{pts} pts"},
        "body": {
            "es": "'{title}' aprobada automáticamente. {reason}",
            "en": "'{title}' approved automatically. {reason}",
        },
    },
    "gig_rejected": {
        "type": NT.GIG_REJECTED,
        "title": {"es": "❌ Gig rechazado", "en": "❌ Gig rejected"},
        "body": {
            "es": "'{title}' no fue aprobada. {notes}",
            "en": "'{title}' was not approved. {notes}",
        },
    },
    "gig_pending_review": {
        "type": NT.GIG_PENDING_REVIEW,
        "title": {"es": "🛎️ Gig por revisar", "en": "🛎️ Gig pending review"},
        "body": {
            "es": "{child} terminó '{title}'. Aprueba o rechaza en Aprobaciones.",
            "en": "{child} finished '{title}'. Approve or reject in Approvals.",
        },
    },
    "task_approved_push": {
        # Used only via render() for the immediate push in approve_gig.
        "type": NT.GIG_APPROVED,
        "title": {"es": "¡Tarea aprobada! 🎉", "en": "Task approved! 🎉"},
        "body": {"es": "{title} — {pts} pts", "en": "{title} — {pts} pts"},
    },
    "late_penalty": {
        "type": NT.LATE_PENALTY_APPLIED,
        "title": {"es": "⏰ Atrasada: {title}", "en": "⏰ Late: {title}"},
        "body": {
            "es": "Penalización automática: sin {restriction} por {days} día(s).",
            "en": "Auto-penalty applied: no {restriction} for {days} day(s).",
        },
    },
    # ── Gig board (gig_claim_service) ───────────────────────────────
    "gig_claim_pending": {
        "type": NT.GIG_PENDING_REVIEW,
        "title": {"es": "📋 Gig por revisar", "en": "📋 Gig to review"},
        "body": {
            "es": "{claimer} completó '{title}' — revisa y aprueba.",
            "en": "{claimer} completed '{title}' — review and approve.",
        },
    },
    "gig_claim_approved": {
        "type": NT.GIG_APPROVED,
        "title": {"es": "✅ +${pesos} MXN", "en": "✅ +${pesos} MXN"},
        "body": {"es": "'{title}' aprobada.", "en": "'{title}' approved."},
    },
    "gig_claim_approved_auto": {
        "type": NT.GIG_APPROVED,
        "title": {"es": "⚡ +${pesos} MXN", "en": "⚡ +${pesos} MXN"},
        "body": {
            "es": "'{title}' aprobada al instante (¡buena racha!).",
            "en": "'{title}' approved instantly (great streak!).",
        },
    },
    "gig_claim_rejected": {
        "type": NT.GIG_REJECTED,
        "title": {
            "es": "↩️ Gig necesita otro intento",
            "en": "↩️ Gig needs another try",
        },
        "body": {"es": "{reason}", "en": "{reason}"},
    },
    # ── Calendar ────────────────────────────────────────────────────
    "calendar_event_added": {
        "type": NT.CALENDAR_EVENT_ADDED,
        "title": {"es": "📅 {title}", "en": "📅 {title}"},
        "body": {
            "es": "Agregado desde escaneo · {when}",
            "en": "Added from scan · {when}",
        },
    },
    # ── Reward goals ────────────────────────────────────────────────
    "goal_reached_kid": {
        "type": NT.GOAL_REACHED,
        "title": {"es": "🎯 ¡Meta alcanzada!", "en": "🎯 Goal reached!"},
        "body": {
            "es": "Tienes suficiente para {reward}.",
            "en": "You have enough for {reward}.",
        },
    },
    "goal_reached_parent": {
        "type": NT.GOAL_REACHED,
        "title": {
            "es": "🎯 {kid} alcanzó su meta",
            "en": "🎯 {kid} reached their goal",
        },
        "body": {"es": "{reward} — {pts} pts", "en": "{reward} — {pts} pts"},
    },
    # ── Reward redemptions ─────────────────────────────────────────
    "redemption_pending_parent": {
        "type": NT.REWARD_REDEEMED,
        "title": {"es": "🎁 Canje por aprobar", "en": "🎁 Redemption to approve"},
        "body": {
            "es": '{name} quiere canjear "{reward}" ({pts} pts). Aprueba o rechaza.',
            "en": '{name} wants to redeem "{reward}" ({pts} pts). Approve or reject.',
        },
    },
    "reward_redeemed_parent": {
        "type": NT.REWARD_REDEEMED,
        "title": {"es": "🎁 Recompensa canjeada", "en": "🎁 Reward redeemed"},
        "body": {
            "es": '{name} canjeó "{reward}" por {pts} puntos.',
            "en": '{name} redeemed "{reward}" for {pts} points.',
        },
    },
    "redemption_approved": {
        "type": NT.REWARD_REDEEMED,
        "title": {"es": "🎁 ¡Canje aprobado!", "en": "🎁 Redemption approved!"},
        "body": {
            "es": 'Tu canje de "{reward}" fue aprobado.',
            "en": 'Your "{reward}" redemption was approved.',
        },
    },
    "redemption_declined": {
        "type": NT.REWARD_REDEEMED,
        "title": {"es": "Canje rechazado", "en": "Redemption declined"},
        "body": {
            "es": 'Tu canje de "{reward}" fue rechazado.',
            "en": 'Your "{reward}" redemption was declined.',
        },
    },
    # ── Membership approval ────────────────────────────────────────
    "member_pending_approval": {
        "type": NT.MEMBER_PENDING_APPROVAL,
        "title": {
            "es": "Nuevo miembro pendiente de aprobación",
            "en": "New member pending approval",
        },
        "body": {
            "es": (
                "{name} ({email}) se registró con el código de tu familia "
                "y espera tu aprobación."
            ),
            "en": (
                "{name} ({email}) signed up with your family code and is "
                "waiting for your approval."
            ),
        },
    },
    "member_approved": {
        "type": NT.MEMBER_APPROVED,
        "title": {
            "es": "¡Tu cuenta fue aprobada!",
            "en": "Your account was approved!",
        },
        "body": {
            "es": "{parent} aprobó tu cuenta. Ya puedes iniciar sesión.",
            "en": "{parent} approved your account. You can now log in.",
        },
    },
    # ── Virtual pet ─────────────────────────────────────────────────
    "pet_starving": {
        "type": NT.PET_NEEDS_ATTENTION,
        "title": {"es": "🥺 {pet} está hambriento", "en": "🥺 {pet} is starving"},
        "body": {
            "es": "Aliméntalo antes de que se ponga peor.",
            "en": "Feed them before they get too hungry.",
        },
    },
    "pet_sad": {
        "type": NT.PET_NEEDS_ATTENTION,
        "title": {"es": "😞 {pet} está triste", "en": "😞 {pet} is sad"},
        "body": {
            "es": "Juega o dale de comer para animarlo.",
            "en": "Play or feed them to cheer them up.",
        },
    },
}


def _normalize_lang(raw: Optional[str]) -> str:
    """Collapse a preferred_lang value to 'es' | 'en' (Mexico-first default)."""
    if not raw:
        return "es"
    return "es" if raw.lower().startswith("es") else "en"


class NotificationService:
    # ── Localization ────────────────────────────────────────────────

    @staticmethod
    def render(
        key: str, lang: str, params: Optional[dict] = None
    ) -> Tuple[str, Optional[str]]:
        """Resolve a _COPY key to (title, body) in ``lang``.

        Param values may be per-language dicts ({"es":…, "en":…}) — they are
        resolved to ``lang`` before formatting. Title is truncated to the
        column width (200).
        """
        lang = _normalize_lang(lang)
        entry = _COPY[key]
        resolved = {
            k: (v.get(lang, v.get("en", "")) if isinstance(v, dict) else v)
            for k, v in (params or {}).items()
        }
        title_tpl = entry["title"].get(lang, entry["title"]["en"])
        title = title_tpl.format(**resolved)[:200]
        body = None
        if entry.get("body"):
            body = (
                entry["body"].get(lang, entry["body"]["en"])
                .format(**resolved)
                .strip()
            )
        return title, body

    @staticmethod
    def copy_type(key: str) -> str:
        """The NotificationType associated with a _COPY key."""
        return _COPY[key]["type"]

    @staticmethod
    async def _recipient_lang(db: AsyncSession, user_id: Optional[UUID]) -> str:
        if user_id is None:
            return "es"
        from app.models.user import User

        try:
            user = await db.get(User, user_id)
        except Exception:
            return "es"
        return _normalize_lang(getattr(user, "preferred_lang", None) if user else None)

    @staticmethod
    async def create_localized(
        db: AsyncSession,
        family_id: UUID,
        key: str,
        *,
        user_id: Optional[UUID] = None,
        params: Optional[dict] = None,
        link: Optional[str] = None,
        lang: Optional[str] = None,
        type: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        push: bool = True,
    ) -> Notification:
        """Create a notification from a _COPY key, localized to the
        recipient's preferred_lang (or an explicit ``lang`` override).

        Family-wide broadcasts (user_id=None) default to Spanish unless
        ``lang`` says otherwise (Mexico-first product).
        """
        if lang is None:
            lang = await NotificationService._recipient_lang(db, user_id)
        title, body = NotificationService.render(key, lang, params)
        return await NotificationService.create(
            db,
            family_id=family_id,
            type=type or NotificationService.copy_type(key),
            title=title,
            body=body,
            link=link,
            user_id=user_id,
            expires_at=expires_at,
            push=push,
        )

    @staticmethod
    async def create_localized_no_commit(
        db: AsyncSession,
        family_id: UUID,
        key: str,
        *,
        user_id: Optional[UUID] = None,
        params: Optional[dict] = None,
        link: Optional[str] = None,
        lang: Optional[str] = None,
        type: Optional[str] = None,
    ) -> Notification:
        """Localized variant of create_no_commit (caller owns the txn; no push)."""
        if lang is None:
            lang = await NotificationService._recipient_lang(db, user_id)
        title, body = NotificationService.render(key, lang, params)
        return await NotificationService.create_no_commit(
            db,
            family_id=family_id,
            type=type or NotificationService.copy_type(key),
            title=title,
            body=body,
            link=link,
            user_id=user_id,
        )

    # ── Raw create (dynamic content only — prefer create_localized) ─
    @staticmethod
    async def create(
        db: AsyncSession,
        family_id: UUID,
        type: str,
        title: str,
        body: Optional[str] = None,
        link: Optional[str] = None,
        user_id: Optional[UUID] = None,
        expires_at: Optional[datetime] = None,
        push: bool = True,
    ) -> Notification:
        """Create a notification. user_id=None broadcasts to whole family.

        When ``push`` is True and ``user_id`` is set, fires a web-push
        message after the commit so the kid's device buzzes immediately.
        Failures in push are swallowed — the in-app feed entry is what
        matters; push is a nice-to-have.
        """
        n = Notification(
            family_id=family_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            expires_at=expires_at,
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)

        if push and user_id is not None:
            # Rate limit: skip push (but keep in-app feed entry) when
            # this user has already received many notifications in the
            # last 60 minutes. Saves the family from a buzzing device.
            try:
                recent = await NotificationService._recent_count(
                    db, user_id, minutes=60
                )
            except Exception:
                recent = 0
            if recent <= 10:
                try:
                    from app.services.push_service import PushService
                    await PushService.send_to_user(
                        db,
                        user_id,
                        {
                            "title": title,
                            "body": body or "",
                            "url": link or "/notifications",
                        },
                    )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "push fan-out failed for notification %s", n.id
                    )
        return n

    @staticmethod
    async def _recent_count(
        db: AsyncSession, user_id: UUID, minutes: int = 60
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        q = (
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.user_id == user_id,
                    Notification.created_at >= cutoff,
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def create_no_commit(
        db: AsyncSession,
        family_id: UUID,
        type: str,
        title: str,
        body: Optional[str] = None,
        link: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> Notification:
        """Same as create() but defers commit so callers can batch in their own txn."""
        n = Notification(
            family_id=family_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
        )
        db.add(n)
        return n

    @staticmethod
    async def list_for_user(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        now = datetime.now(timezone.utc)
        q = (
            select(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    or_(
                        Notification.expires_at.is_(None),
                        Notification.expires_at > now,
                    ),
                )
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        if only_unread:
            q = q.where(Notification.is_read.is_(False))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def unread_count(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> int:
        now = datetime.now(timezone.utc)
        q = (
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    Notification.is_read.is_(False),
                    or_(
                        Notification.expires_at.is_(None),
                        Notification.expires_at > now,
                    ),
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def mark_read(
        db: AsyncSession,
        notif_id: UUID,
        user_id: UUID,
        family_id: UUID,
    ) -> Notification:
        q = select(Notification).where(
            and_(
                Notification.id == notif_id,
                Notification.family_id == family_id,
                or_(
                    Notification.user_id == user_id,
                    Notification.user_id.is_(None),
                ),
            )
        )
        n = (await db.execute(q)).scalar_one_or_none()
        if not n:
            raise NotFoundException("Notification not found")
        n.is_read = True
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(n)
        return n

    @staticmethod
    async def mark_all_read(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            sql_update(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    Notification.is_read.is_(False),
                )
            )
            .values(is_read=True, read_at=now)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0
