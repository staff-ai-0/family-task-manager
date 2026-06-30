"""Two-currency economy: chores award points, gigs award cash.

Covers the validator/constraint removal (the prod task-creation 422), the
mandatory-chore points award, and the gig→cash switch.
"""

import pytest
from datetime import date

from app.schemas.task_template import TaskTemplateCreate
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.models.task_assignment import TaskAssignment, AssignmentStatus


# ── Task 2: mandatory tasks may carry points ─────────────────────────────────

def test_migration_enum_labels_match_orm_names():
    """Guard the prod-only enum-case trap: SQLEnum(CashTransactionType) has no
    values_callable, so SQLAlchemy binds the member NAME (uppercase). The
    migration must create the postgres enum with those same UPPERCASE labels —
    not the lowercase values — or every cash write 500s on a migrated DB while
    create_all-based tests stay green.
    """
    import pathlib
    from app.models.cash_transaction import CashTransactionType

    candidates = [
        pathlib.Path("migrations/versions/2026_06_30_two_currency_economy.py"),
        pathlib.Path("/app/migrations/versions/2026_06_30_two_currency_economy.py"),
    ]
    src = next((p.read_text() for p in candidates if p.exists()), None)
    assert src is not None, "migration file not found"
    # The ENUM(...) call must list every member NAME (uppercase). The lowercase
    # value may legitimately appear in comments, so we only require the names.
    for member in CashTransactionType:
        assert f'"{member.name}"' in src, (
            f"migration missing UPPERCASE enum label {member.name!r}; SQLEnum binds "
            f"the NAME, so a lowercase-only label breaks every cash write in prod"
        )


def test_mandatory_task_can_have_points_schema():
    # Previously raised: "Mandatory tasks (is_bonus=false) must have points=0"
    t = TaskTemplateCreate(title="Sweep", is_bonus=False, points=10,
                           assignment_type="auto", gig_mode="claim")
    assert t.points == 10
    assert t.is_bonus is False


@pytest.mark.asyncio
async def test_mandatory_template_with_points_persists(db, family):
    t = TaskTemplate(title="Sweep", points=10, interval_days=1,
                     is_bonus=False, is_active=True, family_id=family.id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    assert t.points == 10  # no chk_mandatory_zero_points violation


# ── Task 4: PointsService.award_assignment_completion (no-commit) ─────────────

@pytest.mark.asyncio
async def test_award_assignment_completion_no_commit_credits_points(db, family):
    from app.services.points_service import PointsService
    u = User(email="kidp@test.com", name="Kid", role=UserRole.CHILD,
             family_id=family.id, email_verified=True, points=5)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    tx = await PointsService.award_assignment_completion(db, u.id, None, 10)
    await db.commit()
    await db.refresh(u)
    assert u.points == 15
    assert tx.points == 10


# ── Task 5: mandatory completion awards effective_points ──────────────────────

@pytest.mark.asyncio
async def test_mandatory_completion_awards_effective_points(
    db, family, mandatory_template_factory
):
    from app.services.task_assignment_service import TaskAssignmentService
    kid = User(email="kidm@test.com", name="Kid", role=UserRole.CHILD,
               family_id=family.id, email_verified=True, points=0)
    db.add(kid)
    await db.commit()
    await db.refresh(kid)
    tmpl = await mandatory_template_factory(family=family, points=10)  # effort 1 → 10
    a = TaskAssignment(template_id=tmpl.id, family_id=family.id,
                       assigned_to=kid.id, assigned_date=date.today(),
                       week_of=date.today(), status=AssignmentStatus.PENDING)
    db.add(a)
    await db.commit()
    await db.refresh(a)

    await TaskAssignmentService.complete_assignment(db, a.id, family.id, kid.id)
    await db.refresh(kid)
    assert kid.points == 10      # privilege points credited
    assert kid.cash_cents == 0   # mandatory never touches cash


# ── Bonus task (is_bonus) awards POINTS, not cash ────────────────────────────
# Bonus tasks are optional extra-credit chores — they pay privilege points like
# mandatory chores. Only the /gigs board pays cash (see below).

@pytest.mark.asyncio
async def test_bonus_task_completion_awards_points_not_cash(
    db, family, gig_template_factory
):
    from app.core.config import settings
    from app.services.task_assignment_service import TaskAssignmentService
    kid = User(email="kidg@test.com", name="Kid", role=UserRole.CHILD,
               family_id=family.id, email_verified=True, points=0, cash_cents=0,
               gig_trust_streak=max(1, settings.GIG_AUTO_APPROVE_STREAK))
    db.add(kid)
    await db.commit()
    await db.refresh(kid)
    tmpl = await gig_template_factory(family=family, points=20)  # effort 1 → 20 pts
    a = TaskAssignment(template_id=tmpl.id, family_id=family.id,
                       assigned_to=kid.id, assigned_date=date.today(),
                       week_of=date.today(), status=AssignmentStatus.PENDING)
    db.add(a)
    await db.commit()
    await db.refresh(a)

    await TaskAssignmentService.complete_assignment(
        db, a.id, family.id, kid.id, proof_text="did it")
    await db.refresh(kid)
    assert kid.points == 20       # bonus task pays privilege points
    assert kid.cash_cents == 0    # bonus task does NOT pay cash


# ── Gig BOARD approval awards CASH, not points ───────────────────────────────

@pytest.mark.asyncio
async def test_gig_board_approval_credits_cash_not_points(
    db, family
):
    """The /gigs board (GigOffering/GigClaim) is the only thing that pays cash."""
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory
    from app.services.gig_claim_service import GigClaimService
    parent = User(email="par-gb@test.com", name="Parent", role=UserRole.PARENT,
                  family_id=family.id, email_verified=True)
    kid = User(email="kid-gb@test.com", name="Kid", role=UserRole.CHILD,
               family_id=family.id, email_verified=True, points=0, cash_cents=0)
    db.add_all([parent, kid])
    await db.commit()
    await db.refresh(parent)
    await db.refresh(kid)

    offering = GigOffering(family_id=family.id, created_by=parent.id,
                           title="Mow lawn", points=50, difficulty=1,
                           category=GigCategory.CHORES)
    db.add(offering)
    await db.commit()
    await db.refresh(offering)
    claim = GigClaim(gig_id=offering.id, family_id=family.id,
                     claimed_by=kid.id, status=GigClaimStatus.COMPLETED)
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    await GigClaimService.approve(db=db, claim_id=claim.id, family_id=family.id,
                                  approver_id=parent.id, approved=True, notes=None)
    await db.refresh(kid)
    assert kid.cash_cents == 5000   # $50 → 5000 cents
    assert kid.points == 0          # gig board does NOT touch points
