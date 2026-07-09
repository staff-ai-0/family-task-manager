"""Family Cup + cooperative boss battle (P2).

Covers:
  * weekly leaderboard window correctness (only this Mon-Sun counts) + family
    isolation (another family's points never leak in);
  * boss HP is the sum of assigned mandatory task points, and decreases only
    when a task is completed/approved — a not-yet-approved completion deals no
    damage;
  * the battle is COOPERATIVE: a missed/overdue task deals no damage, never
    reduces a member's leaderboard standing, and never writes a penalty. At
    worst the boss survives the week.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, select

from app.models.family import Family
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.family_cup_service import FamilyCupService
from app.services.task_assignment_service import TaskAssignmentService


# ─── helpers ─────────────────────────────────────────────────────────


def _week_start_dt() -> datetime:
    """Monday 00:00 UTC of the current week (test families default to UTC)."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def _monday(d):
    return d - timedelta(days=d.weekday())


async def _add_points(db, user_id, points, when, *, balance_before=0):
    db.add(
        PointTransaction(
            type=TransactionType.TASK_COMPLETED,
            points=points,
            user_id=user_id,
            balance_before=balance_before,
            balance_after=balance_before + points,
            created_at=when,
        )
    )


async def _mandatory_template(db, family_id, points, *, requires_proof=False):
    t = TaskTemplate(
        id=uuid4(),
        title=f"Chore {points}",
        points=points,
        interval_days=1,
        assignment_type=AssignmentType.AUTO,
        is_bonus=False,
        is_active=True,
        requires_proof=requires_proof,
        family_id=family_id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _assignment(db, template, user_id, family_id, status):
    today = datetime.now(timezone.utc).date()
    a = TaskAssignment(
        id=uuid4(),
        template_id=template.id,
        assigned_to=user_id,
        family_id=family_id,
        assigned_date=today,
        week_of=_monday(today),
        status=status,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


# ─── Family Cup leaderboard ──────────────────────────────────────────


async def test_leaderboard_window_and_winner(
    db_session, test_family, test_child_user, test_teen_user
):
    """Only the current Mon-Sun window counts; the top scorer is the winner."""
    week_start = _week_start_dt()
    in_window = week_start + timedelta(hours=1)
    last_week = week_start - timedelta(hours=1)  # Sunday 23:00 last week

    # Child: 20 + 10 in-window = 30. Plus a huge last-week txn (excluded) and an
    # in-window redemption (negative → excluded by the points > 0 filter).
    await _add_points(db_session, test_child_user.id, 20, in_window)
    await _add_points(db_session, test_child_user.id, 10, in_window)
    await _add_points(db_session, test_child_user.id, 500, last_week)
    db_session.add(
        PointTransaction(
            type=TransactionType.REWARD_REDEEMED,
            points=-50,
            user_id=test_child_user.id,
            balance_before=100,
            balance_after=50,
            created_at=in_window,
        )
    )
    # Teen: 10 in-window.
    await _add_points(db_session, test_teen_user.id, 10, in_window)
    await db_session.commit()

    result = await FamilyCupService.weekly_leaderboard(db_session, test_family.id)

    entries = {e["name"]: e for e in result["entries"]}
    assert entries[test_child_user.name]["points"] == 30
    assert entries[test_teen_user.name]["points"] == 10
    # Winner is the top scorer, highlighted; runner-up is not.
    assert result["winner_user_id"] == test_child_user.id
    assert entries[test_child_user.name]["is_winner"] is True
    assert entries[test_teen_user.name]["is_winner"] is False
    # Ordering is descending by points.
    assert result["entries"][0]["user_id"] == test_child_user.id


async def test_leaderboard_family_isolation(
    db_session, test_family, test_child_user
):
    """A different family's points can never appear in this family's cup."""
    other = Family(name="Iso Family", timezone="UTC")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_kid = User(
        email="iso-kid@test.com",
        name="Iso Kid",
        role=UserRole.CHILD,
        family_id=other.id,
        email_verified=True,
    )
    db_session.add(other_kid)
    await db_session.commit()
    await db_session.refresh(other_kid)

    when = _week_start_dt() + timedelta(hours=1)
    await _add_points(db_session, test_child_user.id, 20, when)
    await _add_points(db_session, other_kid.id, 999, when)  # huge, other family
    await db_session.commit()

    result = await FamilyCupService.weekly_leaderboard(db_session, test_family.id)

    names = [e["name"] for e in result["entries"]]
    assert "Iso Kid" not in names
    assert all(e["user_id"] != other_kid.id for e in result["entries"])
    # Despite the other family's 999, our family's winner is our 20-pt child.
    assert result["winner_user_id"] == test_child_user.id
    assert result["entries"][0]["points"] == 20


# ─── Cooperative boss battle ─────────────────────────────────────────


async def test_boss_max_hp_from_assigned_task_points(
    db_session, test_family, test_child_user
):
    """Max HP = Σ points of assigned mandatory tasks; starts undamaged."""
    a = await _mandatory_template(db_session, test_family.id, 30)
    b = await _mandatory_template(db_session, test_family.id, 20)
    await _assignment(
        db_session, a, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )
    await _assignment(
        db_session, b, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )

    boss = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert boss["max_hp"] == 50
    assert boss["damage"] == 0
    assert boss["current_hp"] == 50
    assert boss["active"] is True
    assert boss["defeated"] is False
    # A boss is always named (deterministic weekly rotation).
    assert boss["name_es"] and boss["name_en"] and boss["emoji"]


async def test_boss_hp_decreases_on_completion(
    db_session, test_family, test_child_user
):
    """A mandatory chore completed (silent) immediately deals its points."""
    a = await _mandatory_template(db_session, test_family.id, 30)
    b = await _mandatory_template(db_session, test_family.id, 20)
    asg_a = await _assignment(
        db_session, a, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )
    await _assignment(
        db_session, b, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )

    before = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert before["current_hp"] == 50

    await TaskAssignmentService.complete_assignment(
        db_session, asg_a.id, test_family.id, test_child_user.id
    )

    after = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert after["damage"] == 30
    assert after["current_hp"] == 20
    assert after["current_hp"] >= 0
    assert after["defeated"] is False


async def test_boss_only_approved_deals_damage(
    db_session, test_family, test_child_user, test_parent_user
):
    """A proof-required chore deals NO damage until a parent APPROVES it."""
    a = await _mandatory_template(
        db_session, test_family.id, 40, requires_proof=True
    )
    b = await _mandatory_template(db_session, test_family.id, 20)
    asg_a = await _assignment(
        db_session, a, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )
    await _assignment(
        db_session, b, test_child_user.id, test_family.id, AssignmentStatus.PENDING
    )

    # Completed WITH a photo → parked for review (approval PENDING): no damage.
    await TaskAssignmentService.complete_assignment(
        db_session,
        asg_a.id,
        test_family.id,
        test_child_user.id,
        proof_image_url="/uploads/gig-proofs/proof.jpg",
    )
    pending = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert pending["max_hp"] == 60
    assert pending["damage"] == 0  # awaiting approval → no damage yet
    assert pending["current_hp"] == 60

    # Parent approves → now it deals its 40 points of damage.
    await TaskAssignmentService.approve_gig(
        db_session, asg_a.id, test_family.id, test_parent_user.id, approve=True
    )
    approved = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert approved["damage"] == 40
    assert approved["current_hp"] == 20


async def test_boss_is_cooperative_missed_task_no_damage_no_penalty(
    db_session, test_family, test_child_user
):
    """A missed (overdue) task deals no damage, never reduces the member's
    leaderboard standing, and never writes a penalty transaction."""
    done = await _mandatory_template(db_session, test_family.id, 30)
    missed = await _mandatory_template(db_session, test_family.id, 20)

    # One completed (with the +30 it earned), one still just PENDING.
    await _assignment(
        db_session, done, test_child_user.id, test_family.id,
        AssignmentStatus.COMPLETED,
    )
    await _add_points(
        db_session, test_child_user.id, 30, _week_start_dt() + timedelta(hours=2)
    )
    await db_session.commit()

    standing_before = await FamilyCupService.weekly_leaderboard(
        db_session, test_family.id
    )
    child_before = next(
        e["points"] for e in standing_before["entries"]
        if e["user_id"] == test_child_user.id
    )
    assert child_before == 30

    # Now the second task is missed → OVERDUE.
    await _assignment(
        db_session, missed, test_child_user.id, test_family.id,
        AssignmentStatus.OVERDUE,
    )

    boss = await FamilyCupService.boss_battle(db_session, test_family.id)
    # Overdue task adds to HP but deals ZERO damage; HP never goes negative.
    assert boss["max_hp"] == 50
    assert boss["damage"] == 30
    assert boss["current_hp"] == 20
    assert boss["current_hp"] >= 0

    # The miss did NOT reduce the member's standing.
    standing_after = await FamilyCupService.weekly_leaderboard(
        db_session, test_family.id
    )
    child_after = next(
        e["points"] for e in standing_after["entries"]
        if e["user_id"] == test_child_user.id
    )
    assert child_after == child_before == 30

    # No penalty / negative point transaction was created for the miss.
    negatives = (
        await db_session.execute(
            select(PointTransaction).where(
                and_(
                    PointTransaction.user_id == test_child_user.id,
                    PointTransaction.points < 0,
                )
            )
        )
    ).scalars().all()
    assert negatives == []


async def test_boss_survives_when_all_tasks_missed(
    db_session, test_family, test_child_user
):
    """At worst the boss survives the week — missed tasks never damage anyone."""
    a = await _mandatory_template(db_session, test_family.id, 30)
    b = await _mandatory_template(db_session, test_family.id, 20)
    await _assignment(
        db_session, a, test_child_user.id, test_family.id, AssignmentStatus.OVERDUE
    )
    await _assignment(
        db_session, b, test_child_user.id, test_family.id, AssignmentStatus.OVERDUE
    )

    boss = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert boss["max_hp"] == 50
    assert boss["damage"] == 0
    assert boss["current_hp"] == 50
    assert boss["defeated"] is False
    assert boss["active"] is True


async def test_record_and_list_past_season(
    db_session, test_family, test_child_user
):
    """Closing a season persists the winner (idempotent upsert per week)."""
    when = _week_start_dt() + timedelta(hours=1)
    await _add_points(db_session, test_child_user.id, 42, when)
    await db_session.commit()

    today = datetime.now(timezone.utc).date()
    rec = await FamilyCupService.record_season_winner(
        db_session, test_family.id, week_of=today
    )
    assert rec["winner_name"] == test_child_user.name
    assert rec["winner_points"] == 42

    seasons = await FamilyCupService.list_past_seasons(db_session, test_family.id)
    assert len(seasons) == 1
    assert seasons[0]["winner_name"] == test_child_user.name

    # Re-close the same week → upsert, not a duplicate row.
    await _add_points(db_session, test_child_user.id, 8, when)
    await db_session.commit()
    rec2 = await FamilyCupService.record_season_winner(
        db_session, test_family.id, week_of=today
    )
    assert rec2["winner_points"] == 50
    seasons2 = await FamilyCupService.list_past_seasons(db_session, test_family.id)
    assert len(seasons2) == 1


async def test_boss_ignores_bonus_gigs_and_cancelled(
    db_session, test_family, test_child_user
):
    """HP comes from mandatory chores only — bonus gigs and cancelled rows are
    excluded (claim-mode gigs create a row per member and would inflate HP)."""
    chore = await _mandatory_template(db_session, test_family.id, 30)
    gig = TaskTemplate(
        id=uuid4(), title="Gig", points=99, interval_days=7,
        assignment_type=AssignmentType.AUTO, is_bonus=True, is_active=True,
        family_id=test_family.id,
    )
    db_session.add(gig)
    await db_session.commit()
    await db_session.refresh(gig)

    await _assignment(
        db_session, chore, test_child_user.id, test_family.id,
        AssignmentStatus.PENDING,
    )
    await _assignment(
        db_session, gig, test_child_user.id, test_family.id,
        AssignmentStatus.PENDING,
    )
    await _assignment(
        db_session, chore, test_child_user.id, test_family.id,
        AssignmentStatus.CANCELLED,
    )

    boss = await FamilyCupService.boss_battle(db_session, test_family.id)
    assert boss["max_hp"] == 30  # only the single PENDING mandatory chore
