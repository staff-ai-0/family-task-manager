"""P1-W4 task mechanics tests.

Covers:
- Rotation determinism (persisted cursor; no duplicate/missing assignments;
  continuity across 3+ weekly cycles; idempotent re-shuffle).
- Interval recurrence ('every N days since last completion').
- Photo-proof-required completion flow (mandatory chores → approval queue).
- Kid-proposed gigs (draft → parent approve/edit/reject).
- 1-tap parent quick points.
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.models.gig import GigOffering, GigOfferingStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.gig_offering_service import GigOfferingService
from app.services.task_assignment_service import TaskAssignmentService

MONDAY = date(2026, 7, 13)  # a Monday


async def _make_kids(db: AsyncSession, family, n: int) -> list[User]:
    from app.core.security import get_password_hash

    kids = []
    for i in range(n):
        u = User(
            email=f"w4kid{i}@test.local",
            password_hash=get_password_hash("password123"),
            name=f"W4 Kid {i}",
            role=UserRole.CHILD,
            family_id=family.id,
            email_verified=True,
            points=0,
        )
        db.add(u)
        kids.append(u)
    await db.commit()
    for k in kids:
        await db.refresh(k)
    return kids


async def _rotate_template(
    db: AsyncSession, family, kids, interval_days=1, title="Rotate chore"
) -> TaskTemplate:
    t = TaskTemplate(
        id=uuid.uuid4(),
        title=title,
        points=10,
        interval_days=interval_days,
        assignment_type=AssignmentType.ROTATE,
        assigned_user_ids=[str(k.id) for k in kids],
        is_bonus=False,
        is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


def _sequence(assignments) -> list[str]:
    """Assignee ids ordered by date (rotation order)."""
    return [
        str(a.assigned_to)
        for a in sorted(assignments, key=lambda a: a.assigned_date)
    ]


# ─────────────────────────────────────────────────────────────────────
# 1. Rotation determinism
# ─────────────────────────────────────────────────────────────────────


class TestRotationDeterminism:
    @pytest.mark.asyncio
    async def test_daily_rotation_no_dup_no_missing(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 3)
        await _rotate_template(db_session, test_family, kids, interval_days=1)

        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=MONDAY
        )
        # 7 days, exactly one assignment per day — never 0, never 2.
        assert len(assignments) == 7
        dates = sorted(a.assigned_date for a in assignments)
        assert dates == [MONDAY + timedelta(days=i) for i in range(7)]

        # Round-robin follows assigned_user_ids order, starting at cursor 0.
        expected = [str(kids[i % 3].id) for i in range(7)]
        assert _sequence(assignments) == expected

    @pytest.mark.asyncio
    async def test_reshuffle_same_week_is_identical(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 3)
        await _rotate_template(db_session, test_family, kids)

        first = _sequence(
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY
            )
        )
        second = _sequence(
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY
            )
        )
        third = _sequence(
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY
            )
        )
        assert first == second == third

    @pytest.mark.asyncio
    async def test_rotation_continues_across_three_weeks_balanced(
        self, db_session, test_family
    ):
        kids = await _make_kids(db_session, test_family, 3)
        tmpl = await _rotate_template(db_session, test_family, kids)

        sequences = []
        for w in range(3):
            week = MONDAY + timedelta(weeks=w)
            rows = await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=week
            )
            sequences.append(_sequence(rows))

        # Week 2 picks up exactly where week 1 ended (cursor persisted):
        # 21 consecutive occurrences must be one uninterrupted round-robin.
        flat = [uid for seq in sequences for uid in seq]
        expected = [str(kids[i % 3].id) for i in range(21)]
        assert flat == expected

        # Perfectly balanced: 21 occurrences / 3 kids = 7 each.
        for k in kids:
            assert flat.count(str(k.id)) == 7

        # Cursor state persisted on the template. The cursor stores the NEXT
        # start (start used for week 3 = 14, + 7 daily occurrences) so
        # continuity never depends on re-deriving week 3's schedule from the
        # template's mutable interval_days.
        await db_session.refresh(tmpl)
        assert tmpl.rotation_week_of == MONDAY + timedelta(weeks=2)
        assert tmpl.rotation_cursor == 21

    @pytest.mark.asyncio
    async def test_interval_change_between_weeks_keeps_continuity(
        self, db_session, test_family
    ):
        """Parent changes the frequency between weeks: the round-robin must
        continue from the persisted post-week cursor, not from a count
        re-derived from the NEW interval (which skipped/repeated kids)."""
        kids = await _make_kids(db_session, test_family, 3)
        tmpl = await _rotate_template(
            db_session, test_family, kids, interval_days=3
        )  # Mon/Thu/Sun → 3 occurrences

        week1 = _sequence(
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY
            )
        )
        assert week1 == [str(kids[i % 3].id) for i in range(3)]

        # Parent switches the chore to daily before next week's shuffle.
        tmpl.interval_days = 1
        await db_session.commit()

        week2 = _sequence(
            await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY + timedelta(weeks=1)
            )
        )
        # Week 1 consumed exactly 3 occurrences → week 2 starts at index 3
        # (kids[0] again), NOT at 0 + occurrences(new daily interval) = 7.
        assert week2 == [str(kids[(3 + i) % 3].id) for i in range(7)]

    @pytest.mark.asyncio
    async def test_weekly_rotation_single_row_cycles_kids(
        self, db_session, test_family
    ):
        kids = await _make_kids(db_session, test_family, 3)
        await _rotate_template(
            db_session, test_family, kids, interval_days=7, title="Trash weekly"
        )

        picks = []
        for w in range(6):
            rows = await TaskAssignmentService.shuffle_tasks(
                db_session, test_family.id, week_of=MONDAY + timedelta(weeks=w)
            )
            # Weekly rotate = exactly ONE assignment (the duplicate-per-day
            # expansion was the bug class this feature guards against).
            assert len(rows) == 1
            picks.append(str(rows[0].assigned_to))

        expected = [str(kids[i % 3].id) for i in range(6)]
        assert picks == expected

    @pytest.mark.asyncio
    async def test_preview_does_not_advance_cursor(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 3)
        tmpl = await _rotate_template(db_session, test_family, kids)

        await TaskAssignmentService.preview_shuffle(
            db_session, test_family.id, week_of=MONDAY
        )
        await db_session.refresh(tmpl)
        assert tmpl.rotation_week_of is None
        assert tmpl.rotation_cursor == 0


# ─────────────────────────────────────────────────────────────────────
# 2. Interval recurrence ('every N days since last completion')
# ─────────────────────────────────────────────────────────────────────


async def _interval_template(
    db, family, kids, n_days=3, assignment_type=AssignmentType.FIXED,
    requires_proof=False,
) -> TaskTemplate:
    t = TaskTemplate(
        id=uuid.uuid4(),
        title="Water the plants",
        points=5,
        interval_days=7,
        recurrence_mode="since_completion",
        recur_every_n_days=n_days,
        requires_proof=requires_proof,
        assignment_type=assignment_type,
        assigned_user_ids=(
            [str(k.id) for k in kids]
            if assignment_type in (AssignmentType.FIXED, AssignmentType.ROTATE)
            else None
        ),
        is_bonus=False,
        is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


class TestIntervalRecurrence:
    @pytest.mark.asyncio
    async def test_first_spawn_then_idempotent(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 1)
        tmpl = await _interval_template(db_session, test_family, kids)

        d0 = date.today()
        created = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0
        )
        assert len(created) == 1
        assert created[0].assigned_to == kids[0].id
        assert created[0].assigned_date == d0
        assert created[0].status == AssignmentStatus.PENDING

        # Same day again → open row exists → nothing new.
        again = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0
        )
        assert again == []

        # Even N days later, the still-open (would-be OVERDUE) row blocks a
        # second spawn — no pile-up while the kid hasn't done it.
        later = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0 + timedelta(days=10)
        )
        assert later == []
        _ = tmpl  # silence unused

    @pytest.mark.asyncio
    async def test_respawns_n_days_after_completion(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 1)
        await _interval_template(db_session, test_family, kids, n_days=3)

        d0 = date.today()
        created = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0
        )
        assert len(created) == 1

        # Kid completes it today.
        await TaskAssignmentService.complete_assignment(
            db_session, created[0].id, test_family.id, kids[0].id
        )

        # Not due yet at +2 days.
        early = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0 + timedelta(days=2)
        )
        assert early == []

        # Due at +3 days.
        due = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0 + timedelta(days=3)
        )
        assert len(due) == 1
        assert due[0].assigned_date == d0 + timedelta(days=3)

    @pytest.mark.asyncio
    async def test_rotates_assignee_across_spawns(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 2)
        await _interval_template(
            db_session, test_family, kids, n_days=1,
            assignment_type=AssignmentType.ROTATE,
        )

        d = date.today()
        picks = []
        for i in range(4):
            created = await TaskAssignmentService.spawn_interval_assignments_for_family(
                db_session, test_family.id, today=d + timedelta(days=i)
            )
            assert len(created) == 1
            picks.append(str(created[0].assigned_to))
            await TaskAssignmentService.complete_assignment(
                db_session, created[0].id, test_family.id, created[0].assigned_to
            )

        expected = [str(kids[i % 2].id) for i in range(4)]
        assert picks == expected

    @pytest.mark.asyncio
    async def test_excluded_from_weekly_shuffle(self, db_session, test_family):
        kids = await _make_kids(db_session, test_family, 2)
        tmpl = await _interval_template(db_session, test_family, kids)

        rows = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=MONDAY
        )
        assert all(a.template_id != tmpl.id for a in rows)

    @pytest.mark.asyncio
    async def test_shuffle_preserves_open_interval_rows_and_cursor(
        self, db_session, test_family
    ):
        """Regression: the weekly shuffle's PENDING-row delete must NOT wipe
        interval-spawned rows (they are excluded from the re-expansion, so a
        (re-)shuffle silently vanished the chore and the re-spawn advanced
        the rotation cursor a second time, skipping a kid)."""
        kids = await _make_kids(db_session, test_family, 2)
        tmpl = await _interval_template(
            db_session, test_family, kids, n_days=3,
            assignment_type=AssignmentType.ROTATE,
        )

        # Spawn mid-week (Tuesday of the shuffled week).
        tuesday = MONDAY + timedelta(days=1)
        created = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=tuesday
        )
        assert len(created) == 1
        row_id = created[0].id
        await db_session.refresh(tmpl)
        assert tmpl.rotation_cursor == 1  # advanced once by the spawn

        # Parent (re-)shuffles the SAME week.
        await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=MONDAY
        )

        # The interval row survives untouched…
        survivor = (await db_session.execute(
            select(TaskAssignment).where(TaskAssignment.id == row_id)
        )).scalar_one_or_none()
        assert survivor is not None
        assert survivor.status == AssignmentStatus.PENDING
        assert survivor.assigned_to == created[0].assigned_to

        # …the cursor did not advance a second time…
        await db_session.refresh(tmpl)
        assert tmpl.rotation_cursor == 1
        assert tmpl.rotation_week_of is None  # weekly shuffle never touched it

        # …and the sweep spawns no duplicate while the row stays open.
        again = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=tuesday
        )
        assert again == []

    @pytest.mark.asyncio
    async def test_pending_approval_blocks_respawn(
        self, db_session, test_family, test_parent_user
    ):
        """A proof-required interval chore that is COMPLETED but awaiting
        parent review counts as OPEN: the sweep must not spawn the next
        occurrence (a later rejection re-opens the first row, which would
        leave two open rows for the same template)."""
        kids = await _make_kids(db_session, test_family, 1)
        tmpl = await _interval_template(
            db_session, test_family, kids, n_days=1, requires_proof=True
        )

        d0 = date.today()
        created = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0
        )
        assert len(created) == 1

        # Kid completes with photo → parks in the approval queue.
        done = await TaskAssignmentService.complete_assignment(
            db_session, created[0].id, test_family.id, kids[0].id,
            proof_image_url="/uploads/gig-proofs/test-w4-interval.jpg",
        )
        assert done.status == AssignmentStatus.COMPLETED
        assert done.approval_status == ApprovalStatus.PENDING

        # Due date reached but review still pending → blocked.
        blocked = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0 + timedelta(days=1)
        )
        assert blocked == []

        # Parent approves → the row closes and the next occurrence spawns.
        await TaskAssignmentService.approve_gig(
            db_session, created[0].id, test_family.id, test_parent_user.id,
            approve=True,
        )
        due = await TaskAssignmentService.spawn_interval_assignments_for_family(
            db_session, test_family.id, today=d0 + timedelta(days=1)
        )
        assert len(due) == 1
        assert due[0].template_id == tmpl.id
        assert due[0].assigned_date == d0 + timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────
# 3. Photo-proof-required completion flow
# ─────────────────────────────────────────────────────────────────────


async def _proof_chore_with_assignment(db, family, kid):
    tmpl = TaskTemplate(
        id=uuid.uuid4(),
        title="Clean the bathroom",
        points=20,
        effort_level=1,
        interval_days=1,
        requires_proof=True,
        assignment_type=AssignmentType.AUTO,
        is_bonus=False,
        is_active=True,
        family_id=family.id,
    )
    db.add(tmpl)
    await db.flush()
    a = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=kid.id,
        family_id=family.id,
        status=AssignmentStatus.PENDING,
        assigned_date=date.today(),
        week_of=TaskAssignmentService._get_monday(date.today()),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return tmpl, a


class TestProofRequiredFlow:
    @pytest.mark.asyncio
    async def test_complete_requires_photo(
        self, db_session, test_family, test_child_user
    ):
        _, a = await _proof_chore_with_assignment(
            db_session, test_family, test_child_user
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.complete_assignment(
                db_session, a.id, test_family.id, test_child_user.id
            )

    @pytest.mark.asyncio
    async def test_photo_completion_parks_in_approval_queue_no_points(
        self, db_session, test_family, test_child_user, test_parent_user
    ):
        tmpl, a = await _proof_chore_with_assignment(
            db_session, test_family, test_child_user
        )
        balance_before = test_child_user.points

        done = await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, test_child_user.id,
            proof_text="listo",
            proof_image_url="/uploads/gig-proofs/test-w4.jpg",
        )
        assert done.status == AssignmentStatus.COMPLETED
        assert done.approval_status == ApprovalStatus.PENDING
        assert done.proof_image_url == "/uploads/gig-proofs/test-w4.jpg"

        await db_session.refresh(test_child_user)
        assert test_child_user.points == balance_before  # nothing credited yet

        # Shows in the parent approval queue.
        pending = await TaskAssignmentService.list_pending_approvals(
            db_session, test_family.id
        )
        assert any(r.id == a.id for r in pending)

        # Parent approves → effective_points credited as TASK_COMPLETED.
        await TaskAssignmentService.approve_gig(
            db_session, a.id, test_family.id, test_parent_user.id, approve=True
        )
        await db_session.refresh(test_child_user)
        assert test_child_user.points == balance_before + tmpl.effective_points

        tx = (await db_session.execute(
            select(PointTransaction).where(
                PointTransaction.assignment_id == a.id
            )
        )).scalars().all()
        assert len(tx) == 1
        assert tx[0].type == TransactionType.TASK_COMPLETED
        assert tx[0].points == tmpl.effective_points

        # Approval must NOT touch the gig trust streak (chores ≠ gigs).
        await db_session.refresh(test_child_user)
        assert test_child_user.gig_trust_streak == 0

    @pytest.mark.asyncio
    async def test_reject_reopens_assignment_without_points(
        self, db_session, test_family, test_child_user, test_parent_user
    ):
        _, a = await _proof_chore_with_assignment(
            db_session, test_family, test_child_user
        )
        balance_before = test_child_user.points

        await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, test_child_user.id,
            proof_text=None,
            proof_image_url="/uploads/gig-proofs/test-w4b.jpg",
        )
        rejected = await TaskAssignmentService.approve_gig(
            db_session, a.id, test_family.id, test_parent_user.id,
            approve=False, notes="Falta el espejo",
        )
        assert rejected.approval_status == ApprovalStatus.REJECTED
        assert rejected.status == AssignmentStatus.PENDING  # re-opened
        assert rejected.completed_at is None

        await db_session.refresh(test_child_user)
        assert test_child_user.points == balance_before

        # Kid can redo it (photo again) → pending approval once more.
        redo = await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, test_child_user.id,
            proof_image_url="/uploads/gig-proofs/test-w4c.jpg",
        )
        assert redo.approval_status == ApprovalStatus.PENDING


# ─────────────────────────────────────────────────────────────────────
# 4. Kid-proposed gigs
# ─────────────────────────────────────────────────────────────────────


class TestKidProposedGigs:
    @pytest.mark.asyncio
    async def test_proposal_is_pending_and_hidden_from_board(
        self, db_session, test_family, test_child_user
    ):
        offering = await GigOfferingService.propose(
            db_session,
            family_id=test_family.id,
            created_by=test_child_user.id,
            title="Organizar el garage",
            points=80,
        )
        assert offering.status == GigOfferingStatus.PENDING.value
        assert offering.is_active is False

        board = await GigOfferingService.list_for_family(
            db_session, test_family.id, test_child_user.id
        )
        assert all(item["offering"].id != offering.id for item in board)

        mine = await GigOfferingService.list_my_proposals(
            db_session, test_family.id, test_child_user.id
        )
        assert [o.id for o in mine] == [offering.id]

    @pytest.mark.asyncio
    async def test_parent_approve_with_edits_publishes(
        self, db_session, test_family, test_child_user, test_parent_user
    ):
        offering = await GigOfferingService.propose(
            db_session,
            family_id=test_family.id,
            created_by=test_child_user.id,
            title="Lavar el coche",
            points=200,
        )
        reviewed = await GigOfferingService.review_proposal(
            db_session,
            offering_id=offering.id,
            family_id=test_family.id,
            reviewer_id=test_parent_user.id,
            approve=True,
            points=100,  # parent lowers the suggested pay
        )
        assert reviewed.status == GigOfferingStatus.APPROVED.value
        assert reviewed.is_active is True
        assert reviewed.points == 100
        assert reviewed.reviewed_by == test_parent_user.id

        board = await GigOfferingService.list_for_family(
            db_session, test_family.id, test_child_user.id
        )
        assert any(item["offering"].id == offering.id for item in board)

        # Second decision on the same proposal is rejected.
        with pytest.raises(ValidationException):
            await GigOfferingService.review_proposal(
                db_session,
                offering_id=offering.id,
                family_id=test_family.id,
                reviewer_id=test_parent_user.id,
                approve=False,
            )

    @pytest.mark.asyncio
    async def test_reject_keeps_it_off_board_with_notes(
        self, db_session, test_family, test_child_user, test_parent_user
    ):
        offering = await GigOfferingService.propose(
            db_session,
            family_id=test_family.id,
            created_by=test_child_user.id,
            title="Cuidar al perro del vecino",
            points=500,
        )
        rejected = await GigOfferingService.review_proposal(
            db_session,
            offering_id=offering.id,
            family_id=test_family.id,
            reviewer_id=test_parent_user.id,
            approve=False,
            notes="Muy caro, propon otra cosa",
        )
        assert rejected.status == GigOfferingStatus.REJECTED.value
        assert rejected.is_active is False
        assert rejected.review_notes == "Muy caro, propon otra cosa"

        mine = await GigOfferingService.list_my_proposals(
            db_session, test_family.id, test_child_user.id
        )
        assert mine and mine[0].status == GigOfferingStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_update_activate_pending_proposal_is_implicit_approval(
        self, db_session, test_family, test_child_user, test_parent_user
    ):
        """The generic parent edit path (PUT /offerings/{id}) can set
        is_active=True. On a pending/rejected kid proposal that must behave
        as an approval — status flips to 'approved' with the review stamp —
        never a live-but-still-'pending' gig the kid sees as undecided."""
        offering = await GigOfferingService.propose(
            db_session,
            family_id=test_family.id,
            created_by=test_child_user.id,
            title="Barrer la banqueta",
            points=40,
        )
        updated = await GigOfferingService.update(
            db_session,
            offering_id=offering.id,
            family_id=test_family.id,
            acting_user_id=test_parent_user.id,
            is_active=True,
        )
        assert updated.is_active is True
        assert updated.status == GigOfferingStatus.APPROVED.value
        assert updated.reviewed_by == test_parent_user.id
        assert updated.reviewed_at is not None

        # It is on the board and no longer in the kid's pending list.
        board = await GigOfferingService.list_for_family(
            db_session, test_family.id, test_child_user.id
        )
        assert any(item["offering"].id == offering.id for item in board)
        mine = await GigOfferingService.list_my_proposals(
            db_session, test_family.id, test_child_user.id
        )
        assert all(o.id != offering.id for o in mine)

        # Plain edits (no activation) on an approved offering keep working
        # and do not re-stamp the review.
        renamed = await GigOfferingService.update(
            db_session,
            offering_id=offering.id,
            family_id=test_family.id,
            acting_user_id=test_parent_user.id,
            title="Barrer banqueta y cochera",
        )
        assert renamed.title == "Barrer banqueta y cochera"
        assert renamed.status == GigOfferingStatus.APPROVED.value

    @pytest.mark.asyncio
    async def test_route_parent_cannot_propose(
        self, client: AsyncClient, auth_headers
    ):
        r = await client.post(
            "/api/gigs/offerings/propose",
            json={"title": "Parent gig", "points": 10},
            headers=auth_headers,
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_route_child_proposes_and_parent_lists(
        self, client: AsyncClient, test_child_user, auth_headers
    ):
        login = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        assert login.status_code == 200, login.text
        child_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }

        r = await client.post(
            "/api/gigs/offerings/propose",
            json={"title": "Regar plantas del patio", "points": 30},
            headers=child_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["is_active"] is False

        # Kid sees it under "mine".
        mine = await client.get(
            "/api/gigs/offerings/proposals/mine", headers=child_headers
        )
        assert mine.status_code == 200
        assert any(o["id"] == body["id"] for o in mine.json())

        # Parent sees it in the pending review queue (with proposer name).
        pending = await client.get(
            "/api/gigs/offerings/proposals/pending", headers=auth_headers
        )
        assert pending.status_code == 200
        rows = pending.json()
        assert any(row["offering"]["id"] == body["id"] for row in rows)
        assert rows[0]["proposer_name"]

        # Kid cannot review their own proposal.
        deny = await client.post(
            f"/api/gigs/offerings/{body['id']}/review",
            json={"approve": True},
            headers=child_headers,
        )
        assert deny.status_code == 403

        # Parent approves via route.
        ok = await client.post(
            f"/api/gigs/offerings/{body['id']}/review",
            json={"approve": True, "points": 25},
            headers=auth_headers,
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "approved"
        assert ok.json()["points"] == 25


# ─────────────────────────────────────────────────────────────────────
# 5. 1-tap quick points
# ─────────────────────────────────────────────────────────────────────


class TestQuickPoints:
    @pytest.mark.asyncio
    async def test_parent_quick_award_and_deduct(
        self, client: AsyncClient, db_session, test_child_user, auth_headers
    ):
        r = await client.post(
            "/api/users/points/quick-adjust",
            json={"user_id": str(test_child_user.id), "points": 5},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["points"] == 5
        assert body["balance_after"] == 105  # fixture starts at 100
        assert body["type"] == "parent_adjustment"
        assert body["description"]  # default reason filled in

        r2 = await client.post(
            "/api/users/points/quick-adjust",
            json={
                "user_id": str(test_child_user.id),
                "points": -10,
                "reason": "Sin recoger juguetes",
            },
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["balance_after"] == 95
        assert r2.json()["description"] == "Sin recoger juguetes"

        await db_session.refresh(test_child_user)
        assert test_child_user.points == 95

    @pytest.mark.asyncio
    async def test_zero_points_rejected(
        self, client: AsyncClient, test_child_user, auth_headers
    ):
        r = await client.post(
            "/api/users/points/quick-adjust",
            json={"user_id": str(test_child_user.id), "points": 0},
            headers=auth_headers,
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_parent_target_rejected(
        self, client: AsyncClient, test_parent_user, auth_headers
    ):
        """Quick-adjust is a kid affordance — a parent must not be able to
        bump another parent's (or their own) balance through it."""
        r = await client.post(
            "/api/users/points/quick-adjust",
            json={"user_id": str(test_parent_user.id), "points": 50},
            headers=auth_headers,
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_child_forbidden(
        self, client: AsyncClient, test_child_user, test_teen_user
    ):
        login = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        assert login.status_code == 200
        child_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        r = await client.post(
            "/api/users/points/quick-adjust",
            json={"user_id": str(test_teen_user.id), "points": 5},
            headers=child_headers,
        )
        assert r.status_code == 403
