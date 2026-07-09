"""Forensic-audit fixes for the task workflow (2026-07-09).

Regression tests for the confirmed findings of the task-workflow audit:

- ROTATE templates with null/empty/stale assigned_user_ids were silently
  skipped by the shuffle (8 of 9 prod templates generated ZERO assignments
  while the API reported success). Now they fall back to all participating
  members (role-filtered, stable order); FIXED without members is rejected
  at the schema and reported as skipped by the shuffle.
- Re-shuffle deleted only PENDING rows but regenerated every slot, duplicating
  completed/claimed/overdue occurrences (and enabling double points).
- Mid-week shuffles minted past-dated PENDING rows that the overdue sweep
  instantly flipped OVERDUE (auto late penalties for days before the schedule
  existed).
- due_date was never written anywhere → API is_overdue permanently false.
- AUTO daily greedy handed the same daily chore to one member all week when
  the cross-week carry was skewed.
- Auto-approval (trust streak / AI) bypassed the monthly gig approval cap.
- patch_assignment revive/cancel never reconciled awarded points.
- Completing future-dated assignments let a kid bank the whole week Monday.
- Competition gigs could be completed directly, bypassing first-claim-wins.
- Deactivating a member left their open assignments rotting forever.
- No duplicate-title guard (prod had two active 'Wash Dishes').
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models.point_transaction import PointTransaction
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.core.exceptions import ValidationException
from app.core.security import get_password_hash
from app.schemas.task_template import TaskTemplateCreate
from app.services.task_assignment_service import TaskAssignmentService
from app.services.task_template_service import TaskTemplateService


# ─── Helpers ─────────────────────────────────────────────────────────

async def _template(db, family_id, parent_id, **kwargs):
    defaults = {
        "title": f"Chore {uuid4().hex[:6]}",
        "points": 10,
        "interval_days": 1,
        "is_bonus": False,
    }
    defaults.update(kwargs)
    data = TaskTemplateCreate(**defaults)
    return await TaskTemplateService.create_template(db, data, family_id, parent_id)


async def _extra_user(db, family_id, email, role=UserRole.CHILD):
    user = User(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0].title(),
        role=role,
        family_id=family_id,
        email_verified=True,
        points=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _week_monday() -> date:
    today = date.today()
    if today.weekday() == 6:
        return today + timedelta(days=1)
    return today - timedelta(days=today.weekday())


async def _direct_assignment(
    db, template, user_id, family_id, assigned_date, status=AssignmentStatus.PENDING
):
    row = TaskAssignment(
        template_id=template.id,
        assigned_to=user_id,
        family_id=family_id,
        status=status,
        assigned_date=assigned_date,
        week_of=assigned_date - timedelta(days=assigned_date.weekday()),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ─── A. Rotation null/stale member lists ─────────────────────────────

class TestRotateFallback:
    async def test_rotate_null_members_falls_back_to_all(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """ROTATE with no member list must rotate over ALL participating
        members instead of silently generating nothing (the prod 8/9 bug)."""
        teen = await _extra_user(
            db_session, test_family.id, "teen-rot@test.com", UserRole.TEEN
        )
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Rotate Null", assignment_type=AssignmentType.ROTATE,
            interval_days=1, assigned_user_ids=None,
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=_week_monday()
        )
        assert len(assignments) == 7  # daily — not skipped
        assignees = {a.assigned_to for a in assignments}
        assert assignees == {test_parent_user.id, test_child_user.id, teen.id}
        # Round-robin over 3 members: 3/2/2 split
        counts = sorted(
            [sum(1 for a in assignments if a.assigned_to == uid) for uid in assignees]
        )
        assert counts == [2, 2, 3]

    async def test_rotate_null_members_respects_allowed_roles(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """The null-list fallback must honor allowed_roles (kids-only chore
        never lands on a parent)."""
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Kids Rotate", assignment_type=AssignmentType.ROTATE,
            interval_days=1, assigned_user_ids=None,
            allowed_roles=["child", "teen"],
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=_week_monday()
        )
        assert len(assignments) == 7
        assert all(a.assigned_to == test_child_user.id for a in assignments)

    async def test_rotate_explicit_list_overrides_allowed_roles(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """An explicit member list is authoritative — a mismatched
        allowed_roles filter must not kill the template."""
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Explicit Rotate", assignment_type=AssignmentType.ROTATE,
            interval_days=7, assigned_user_ids=[test_parent_user.id],
            allowed_roles=["child"],
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=_week_monday()
        )
        assert len(assignments) == 1
        assert assignments[0].assigned_to == test_parent_user.id

    async def test_rotate_stale_ids_fall_back_to_all(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A member list containing only departed users (post-merge reality)
        must fall back to all participating members, not go dead."""
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Stale Rotate", assignment_type=AssignmentType.ROTATE,
            interval_days=1, assigned_user_ids=[uuid4()],
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=_week_monday()
        )
        assert len(assignments) == 7
        assert {a.assigned_to for a in assignments} == {
            test_parent_user.id, test_child_user.id
        }

    async def test_fixed_without_members_rejected_at_schema(self):
        """FIXED has no sane fallback — creating one without members is a
        validation error."""
        with pytest.raises(Exception):
            TaskTemplateCreate(
                title="Fixed No Members",
                assignment_type=AssignmentType.FIXED,
                assigned_user_ids=None,
            )

    async def test_shuffle_reports_skipped_templates(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A template the shuffle cannot expand (legacy FIXED without members)
        must be reported, not silently swallowed."""
        # Bypass the new schema guard — legacy rows exist in prod.
        tmpl = TaskTemplate(
            title="Legacy Fixed", points=10, interval_days=1,
            assignment_type=AssignmentType.FIXED, assigned_user_ids=None,
            family_id=test_family.id, created_by=test_parent_user.id,
            is_bonus=False,
        )
        db_session.add(tmpl)
        await db_session.commit()

        assignments, skipped = await TaskAssignmentService.shuffle_tasks_detailed(
            db_session, test_family.id, today=_week_monday()
        )
        assert assignments == []
        assert len(skipped) == 1
        assert skipped[0]["template_id"] == tmpl.id
        assert "member" in skipped[0]["reason"].lower()


# ─── B. Re-shuffle safety ────────────────────────────────────────────

class TestReshuffleSafety:
    async def test_reshuffle_preserves_completed_without_duplicate(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A completed occurrence must survive a re-shuffle WITHOUT the
        shuffle regenerating a twin slot for the same template+date."""
        monday = _week_monday()
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Dup Check", interval_days=1,
        )
        first = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=monday
        )
        target = first[0]
        await TaskAssignmentService.complete_assignment(
            db_session, target.id, test_family.id, target.assigned_to
        )

        second = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=monday
        )

        rows = (await db_session.execute(
            select(TaskAssignment).where(
                TaskAssignment.family_id == test_family.id,
                TaskAssignment.template_id == target.template_id,
                TaskAssignment.assigned_date == target.assigned_date,
            )
        )).scalars().all()
        assert len(rows) == 1  # the completed row only — no twin
        assert rows[0].status == AssignmentStatus.COMPLETED
        # And the re-shuffle did not regenerate that date
        assert all(a.assigned_date != target.assigned_date for a in second)

    async def test_shuffle_skips_past_dates_mid_week(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Shuffling on Wednesday must not mint Monday/Tuesday rows that the
        sweep would instantly flip OVERDUE (with auto late penalties)."""
        monday = _week_monday()
        wednesday = monday + timedelta(days=2)
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Midweek Daily", interval_days=1,
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=monday, today=wednesday
        )
        assert len(assignments) == 5  # Wed..Sun only
        assert all(a.assigned_date >= wednesday for a in assignments)

    async def test_shuffle_rejects_past_week(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Shuffling an already-finished week only mints instant-overdue rows
        — reject it."""
        monday = _week_monday()
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Past Week", interval_days=1,
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id,
                week_of=monday - timedelta(weeks=1), today=monday,
            )

    async def test_shuffle_populates_due_date(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Every generated row carries a real end-of-day deadline so the API
        is_overdue field finally means something."""
        monday = _week_monday()
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Due Date Check", interval_days=1,
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=monday
        )
        for a in assignments:
            assert a.due_date is not None
            assert a.due_date.date() >= a.assigned_date  # end of local day (UTC fam tz)


# ─── C. Fairness ─────────────────────────────────────────────────────

class TestAutoFairness:
    async def test_auto_daily_spreads_even_with_carry_skew(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A skewed 2-week carry must not hand one member the same daily
        chore all 7 days — the daily rotation spreads people day-to-day."""
        monday = _week_monday()
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Skewed Daily", interval_days=1,
        )
        # Give the child heavy prior-week carry (assigned points last week)
        last_monday = monday - timedelta(weeks=1)
        for i in range(7):
            await _direct_assignment(
                db_session, tmpl, test_child_user.id, test_family.id,
                last_monday + timedelta(days=i),
                status=AssignmentStatus.COMPLETED,
            )

        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=monday, today=monday
        )
        this_week = [a for a in assignments if a.week_of == monday]
        parent_n = sum(1 for a in this_week if a.assigned_to == test_parent_user.id)
        child_n = sum(1 for a in this_week if a.assigned_to == test_child_user.id)
        assert parent_n + child_n == 7
        # Low-carry member (parent) leads, but NEVER takes the whole week
        assert parent_n >= child_n
        assert child_n >= 3


# ─── D. Lifecycle ────────────────────────────────────────────────────

class TestLifecycle:
    async def test_complete_future_dated_blocked(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Future Chore", interval_days=1,
        )
        future = date.today() + timedelta(days=2)
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, future
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.complete_assignment(
                db_session, row.id, test_family.id, test_child_user.id
            )

    async def test_auto_approve_respects_monthly_cap(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Trust-streak auto-approval must consume the same monthly gig cap
        as parent approvals — at the cap it falls back to the manual queue."""
        from app.services.usage_service import UsageService

        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Capped Gig", interval_days=1, is_bonus=True, points=10,
        )
        today = date.today()
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, today
        )
        # Earn auto-approval, then exhaust the free plan's monthly cap (3)
        test_child_user.gig_trust_streak = 99
        await db_session.commit()
        seeded = await UsageService.try_increment_within_limit(
            db_session, test_family.id, "gig_completion", limit=3, amount=3
        )
        await db_session.commit()
        assert seeded == 3

        before = test_child_user.points
        result = await TaskAssignmentService.complete_assignment(
            db_session, row.id, test_family.id, test_child_user.id,
            proof_text="did it",
        )
        # NOT auto-approved — queued for the parent instead
        assert result.approval_status == ApprovalStatus.PENDING
        refreshed = await db_session.get(User, test_child_user.id)
        await db_session.refresh(refreshed)
        assert refreshed.points == before  # nothing credited

    async def test_revive_completed_mandatory_claws_back_points(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Revive Chore", interval_days=1, points=10,
        )
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        before = test_child_user.points
        await TaskAssignmentService.complete_assignment(
            db_session, row.id, test_family.id, test_child_user.id
        )
        user = await db_session.get(User, test_child_user.id)
        await db_session.refresh(user)
        assert user.points == before + 10

        await TaskAssignmentService.patch_assignment(
            db_session, row.id, test_family.id, status=AssignmentStatus.PENDING
        )
        await db_session.refresh(user)
        assert user.points == before  # clawed back
        txs = (await db_session.execute(
            select(PointTransaction).where(
                PointTransaction.assignment_id == row.id
            )
        )).scalars().all()
        assert any(t.points < 0 for t in txs)  # explicit reversal entry

    async def test_cancel_completed_mandatory_claws_back_points(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Cancel Chore", interval_days=1, points=10,
        )
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        before = test_child_user.points
        await TaskAssignmentService.complete_assignment(
            db_session, row.id, test_family.id, test_child_user.id
        )
        await TaskAssignmentService.patch_assignment(
            db_session, row.id, test_family.id, status=AssignmentStatus.CANCELLED
        )
        user = await db_session.get(User, test_child_user.id)
        await db_session.refresh(user)
        assert user.points == before

    async def test_revive_approved_gig_blocked(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """An approved gig has credited points + advanced the trust streak —
        reviving it via PATCH must be rejected (reject/decide flows instead)."""
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Approved Gig", interval_days=1, is_bonus=True, points=10,
        )
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        await TaskAssignmentService.complete_assignment(
            db_session, row.id, test_family.id, test_child_user.id,
            proof_text="done",
        )
        await TaskAssignmentService.approve_gig(
            db_session, row.id, test_family.id, test_parent_user.id, approve=True
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.patch_assignment(
                db_session, row.id, test_family.id,
                status=AssignmentStatus.PENDING,
            )

    async def test_competition_gig_requires_claim_before_complete(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Comp Gig", interval_days=1, is_bonus=True, points=10,
            gig_mode="competition",
        )
        row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.complete_assignment(
                db_session, row.id, test_family.id, test_child_user.id,
                proof_text="won it",
            )

    async def test_deactivate_cancels_open_assignments(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        from app.services.auth_service import AuthService

        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Ghost Chore", interval_days=1,
        )
        open_row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        overdue_row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id,
            date.today() - timedelta(days=1), status=AssignmentStatus.OVERDUE,
        )
        done_row = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id,
            date.today() - timedelta(days=2), status=AssignmentStatus.COMPLETED,
        )

        await AuthService.deactivate_user(db_session, test_child_user.id)

        for row, expected in (
            (open_row, AssignmentStatus.CANCELLED),
            (overdue_row, AssignmentStatus.CANCELLED),
            (done_row, AssignmentStatus.COMPLETED),
        ):
            refreshed = await db_session.get(TaskAssignment, row.id)
            await db_session.refresh(refreshed)
            assert refreshed.status == expected


# ─── E. Template guards ──────────────────────────────────────────────

class TestTemplateGuards:
    async def test_duplicate_active_title_rejected(
        self, db_session, test_family, test_parent_user
    ):
        await _template(
            db_session, test_family.id, test_parent_user.id, title="Wash Dishes"
        )
        with pytest.raises(ValidationException):
            await _template(
                db_session, test_family.id, test_parent_user.id,
                title="wash dishes",  # case-insensitive duplicate
            )

    async def test_duplicate_title_allowed_when_original_inactive(
        self, db_session, test_family, test_parent_user
    ):
        first = await _template(
            db_session, test_family.id, test_parent_user.id, title="Old Chore"
        )
        first.is_active = False
        await db_session.commit()
        second = await _template(
            db_session, test_family.id, test_parent_user.id, title="Old Chore"
        )
        assert second.id != first.id

    async def test_kid_view_exposes_effective_points(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Kids must see the points they'll actually earn (effort multiplier
        applied), not the raw base points."""
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Hard Chore", points=10, effort_level=3,  # ×2.0 → 20
        )
        await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, date.today()
        )
        rows = await TaskAssignmentService.list_for_user_today_with_locks(
            db_session, test_child_user.id, test_family.id
        )
        assert rows and rows[0]["points"] == 20
