"""Notification service tests (W3.2 + launch i18n/core-loop audit 2026-07-07)."""

import pytest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.notification import Notification, NotificationType
from app.services.notification_service import NotificationService


class TestNotificationService:
    async def test_create_and_list_user_specific(
        self, db_session, test_family, test_child_user
    ):
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Approved",
            body="Nice job",
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert len(rows) == 1
        assert rows[0].title == "Approved"

    async def test_family_wide_visible_to_member(
        self, db_session, test_family, test_child_user
    ):
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=None,  # family-wide
            type=NotificationType.GIG_PENDING_REVIEW,
            title="Pending",
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert any(r.title == "Pending" for r in rows)

    async def test_unread_count(
        self, db_session, test_family, test_child_user
    ):
        for i in range(3):
            await NotificationService.create(
                db_session,
                family_id=test_family.id,
                user_id=test_child_user.id,
                type=NotificationType.GIG_APPROVED,
                title=f"n{i}",
            )
        n = await NotificationService.unread_count(
            db_session, test_child_user.id, test_family.id
        )
        assert n == 3

    async def test_mark_read(
        self, db_session, test_family, test_child_user
    ):
        n = await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Read me",
        )
        updated = await NotificationService.mark_read(
            db_session, n.id, test_child_user.id, test_family.id
        )
        assert updated.is_read is True
        assert updated.read_at is not None
        assert (
            await NotificationService.unread_count(
                db_session, test_child_user.id, test_family.id
            )
            == 0
        )

    async def test_mark_all_read(
        self, db_session, test_family, test_child_user
    ):
        for i in range(4):
            await NotificationService.create(
                db_session,
                family_id=test_family.id,
                user_id=test_child_user.id,
                type=NotificationType.GIG_APPROVED,
                title=f"n{i}",
            )
        count = await NotificationService.mark_all_read(
            db_session, test_child_user.id, test_family.id
        )
        assert count == 4

    async def test_expired_not_returned(
        self, db_session, test_family, test_child_user
    ):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Expired",
            expires_at=past,
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert not any(r.title == "Expired" for r in rows)


# ─── Localized copy (i18n audit 2026-07-07) ──────────────────────────


class TestLocalizedNotifications:
    async def test_create_localized_picks_spanish_for_es_user(
        self, db_session, test_family, test_child_user
    ):
        test_child_user.preferred_lang = "es"
        await db_session.commit()

        n = await NotificationService.create_localized(
            db_session,
            family_id=test_family.id,
            key="goal_reached_kid",
            user_id=test_child_user.id,
            params={"reward": "Cine"},
            link="/rewards",
        )
        assert n.type == NotificationType.GOAL_REACHED
        assert n.title == "🎯 ¡Meta alcanzada!"
        assert "Tienes suficiente para Cine." == n.body

    async def test_create_localized_picks_english_for_en_user(
        self, db_session, test_family, test_parent_user
    ):
        test_parent_user.preferred_lang = "en"
        await db_session.commit()

        n = await NotificationService.create_localized(
            db_session,
            family_id=test_family.id,
            key="redemption_pending_parent",
            user_id=test_parent_user.id,
            params={"name": "Emma", "reward": "Movie night", "pts": 50},
        )
        assert n.title == "🎁 Redemption to approve"
        assert (
            n.body
            == 'Emma wants to redeem "Movie night" (50 pts). Approve or reject.'
        )

    async def test_render_resolves_per_language_params(self):
        # Param values may be {"es":…, "en":…} dicts (late-penalty restriction labels)
        title_es, body_es = NotificationService.render(
            "late_penalty",
            "es",
            {
                "title": "Lavar platos",
                "restriction": {"es": "tiempo de pantalla", "en": "screen time"},
                "days": 2,
            },
        )
        assert title_es == "⏰ Atrasada: Lavar platos"
        assert "sin tiempo de pantalla por 2 día(s)" in body_es

        title_en, body_en = NotificationService.render(
            "late_penalty",
            "en",
            {
                "title": "Do dishes",
                "restriction": {"es": "tiempo de pantalla", "en": "screen time"},
                "days": 2,
            },
        )
        assert title_en == "⏰ Late: Do dishes"
        assert "no screen time for 2 day(s)" in body_en

    async def test_broadcast_defaults_to_spanish(
        self, db_session, test_family
    ):
        n = await NotificationService.create_localized(
            db_session,
            family_id=test_family.id,
            key="gig_pending_review",
            user_id=None,
            params={"child": "Emma", "title": "Lavar el coche"},
            push=False,
        )
        assert n.title == "🛎️ Gig por revisar"
        assert "Emma terminó 'Lavar el coche'" in n.body

    async def test_render_truncates_title_to_column_width(self):
        title, _ = NotificationService.render(
            "calendar_event_added", "en", {"title": "x" * 500, "when": "now"}
        )
        assert len(title) <= 200


# ─── TASK_ASSIGNED on assignment creation (core-loop audit) ──────────


class TestTaskAssignedNotification:
    async def test_shuffle_fires_task_assigned_per_assignee(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        from app.schemas.task_template import TaskTemplateCreate
        from app.services.task_template_service import TaskTemplateService
        from app.services.task_assignment_service import TaskAssignmentService

        test_child_user.preferred_lang = "es"
        test_parent_user.preferred_lang = "en"
        await db_session.commit()

        await TaskTemplateService.create_template(
            db_session,
            TaskTemplateCreate(
                title="Daily chore", points=0, interval_days=1, is_bonus=False
            ),
            test_family.id,
            test_parent_user.id,
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        assert assignments  # sanity

        rows = (
            (
                await db_session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.TASK_ASSIGNED
                    )
                )
            )
            .scalars()
            .all()
        )
        assignees = {a.assigned_to for a in assignments}
        # Exactly one aggregated notification per assignee (no per-row spam)
        assert {n.user_id for n in rows} == assignees
        assert len(rows) == len(assignees)

        # Localized to each recipient's preferred_lang
        by_user = {n.user_id: n for n in rows}
        if test_child_user.id in by_user:
            assert "tarea" in by_user[test_child_user.id].title.lower()
        if test_parent_user.id in by_user:
            assert "chore" in by_user[test_parent_user.id].title.lower()


# ─── Morning 'chores due today' reminder sweep ───────────────────────


async def _make_assignment(db, family_id, template_id, user_id, when, status):
    from app.models.task_assignment import TaskAssignment

    a = TaskAssignment(
        template_id=template_id,
        assigned_to=user_id,
        family_id=family_id,
        status=status,
        assigned_date=when,
        week_of=when - timedelta(days=when.weekday()),
    )
    db.add(a)
    await db.commit()
    return a


_SWEEP_TZ = "America/Mexico_City"


def _family_today() -> date:
    """Today's date in the sweep test timezone (must match family.timezone)."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(_SWEEP_TZ)).date()


class TestMorningReminderSweep:
    async def _template(self, db, family, parent):
        from app.schemas.task_template import TaskTemplateCreate
        from app.services.task_template_service import TaskTemplateService

        # Pin the family timezone so 'due today' in the sweep matches the
        # dates the tests write, regardless of the host/container clock.
        family.timezone = _SWEEP_TZ
        await db.commit()

        return await TaskTemplateService.create_template(
            db,
            TaskTemplateCreate(
                title="Sweep chore", points=0, interval_days=1, is_bonus=False
            ),
            family.id,
            parent.id,
        )

    async def test_counts_only_pending_due_today(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        from app.models.task_assignment import AssignmentStatus
        from app.services.task_assignment_service import TaskAssignmentService

        test_child_user.preferred_lang = "es"
        await db_session.commit()

        tmpl = await self._template(db_session, test_family, test_parent_user)
        today = _family_today()
        # 2 pending today (counted) + 1 tomorrow + 1 completed today (not counted)
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            today, AssignmentStatus.PENDING,
        )
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            today, AssignmentStatus.PENDING,
        )
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            today + timedelta(days=1), AssignmentStatus.PENDING,
        )
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            today, AssignmentStatus.COMPLETED,
        )

        sent = await TaskAssignmentService.send_morning_reminders(db_session)
        assert sent == 1

        rows = (
            (
                await db_session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.TASK_DUE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        n = rows[0]
        assert n.user_id == test_child_user.id
        assert n.title == "📋 Tienes 2 tareas hoy"

    async def test_singular_copy_and_english_recipient(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        from app.models.task_assignment import AssignmentStatus
        from app.services.task_assignment_service import TaskAssignmentService

        test_child_user.preferred_lang = "en"
        await db_session.commit()

        tmpl = await self._template(db_session, test_family, test_parent_user)
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            _family_today(), AssignmentStatus.PENDING,
        )

        sent = await TaskAssignmentService.send_morning_reminders(db_session)
        assert sent == 1

        n = (
            await db_session.execute(
                select(Notification).where(
                    Notification.type == NotificationType.TASK_DUE
                )
            )
        ).scalar_one()
        assert n.title == "📋 You have 1 chore today"

    async def test_sweep_is_idempotent_per_day(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        from app.models.task_assignment import AssignmentStatus
        from app.services.task_assignment_service import TaskAssignmentService

        tmpl = await self._template(db_session, test_family, test_parent_user)
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            _family_today(), AssignmentStatus.PENDING,
        )

        first = await TaskAssignmentService.send_morning_reminders(db_session)
        second = await TaskAssignmentService.send_morning_reminders(db_session)
        assert first == 1
        assert second == 0  # restart/duplicate tick must not double-send

        rows = (
            (
                await db_session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.TASK_DUE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_no_reminder_when_nothing_due(
        self, db_session, test_family, test_child_user
    ):
        from app.services.task_assignment_service import TaskAssignmentService

        sent = await TaskAssignmentService.send_morning_reminders(db_session)
        assert sent == 0

    async def test_pending_approval_member_not_reminded(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A join-code signup awaiting parental approval is is_active=True
        but cannot log in — the sweep must skip it even when it holds
        due-today PENDING rows (legacy data from before the shuffle
        approval gate). The approved sibling is still reminded."""
        from app.models.task_assignment import AssignmentStatus
        from app.models.user import APPROVAL_PENDING, User, UserRole
        from app.services.task_assignment_service import TaskAssignmentService

        pending = User(
            email="pending-sweep@test.com",
            name="Pending Kid",
            role=UserRole.CHILD,
            family_id=test_family.id,
            approval_status=APPROVAL_PENDING,
            points=0,
        )
        db_session.add(pending)
        await db_session.commit()
        await db_session.refresh(pending)

        tmpl = await self._template(db_session, test_family, test_parent_user)
        today = _family_today()
        await _make_assignment(
            db_session, test_family.id, tmpl.id, pending.id,
            today, AssignmentStatus.PENDING,
        )
        await _make_assignment(
            db_session, test_family.id, tmpl.id, test_child_user.id,
            today, AssignmentStatus.PENDING,
        )

        sent = await TaskAssignmentService.send_morning_reminders(db_session)
        assert sent == 1  # only the approved member

        rows = (
            (
                await db_session.execute(
                    select(Notification).where(
                        Notification.type == NotificationType.TASK_DUE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {n.user_id for n in rows} == {test_child_user.id}
