"""Shuffle rotation mode: gigs with gig_mode=rotation produce one row
cycled per week (W4.1b)."""

import random
from datetime import date, timedelta

import pytest

from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.task_assignment_service import TaskAssignmentService


def _members(family, count: int) -> list[User]:
    out = []
    for i in range(count):
        u = User(
            id=None,  # generated
            email=f"u{i}@example.test",
            password_hash="x",
            name=f"User {i}",
            role=UserRole.CHILD,
            family_id=family.id,
            is_active=True,
        )
        # Service requires .id to be a UUID; populate via uuid4().
        import uuid
        u.id = uuid.uuid4()
        out.append(u)
    return out


class TestRotationGigShuffle:
    def test_rotation_one_assignment_per_week(self, test_family):
        members = _members(test_family, 3)
        tmpl = TaskTemplate(
            title="Trash duty",
            points=20,
            effort_level=1,
            interval_days=7,
            is_bonus=True,
            gig_mode="rotation",
            family_id=test_family.id,
        )
        import uuid
        tmpl.id = uuid.uuid4()

        rng = random.Random("seed")
        week_monday = date(2026, 6, 1)  # a Monday
        assignments, _, _ = TaskAssignmentService._compute_assignments(
            rng,
            test_family.id,
            week_monday,
            regular_templates=[],
            bonus_templates=[tmpl],
            members=members,
        )
        # Rotation + interval_days=7 should produce exactly one row.
        assert len(assignments) == 1

    def test_rotation_cycles_member_by_week(self, test_family):
        members = _members(test_family, 3)
        tmpl = TaskTemplate(
            title="Trash duty",
            points=20,
            effort_level=1,
            interval_days=7,
            is_bonus=True,
            gig_mode="rotation",
            family_id=test_family.id,
        )
        import uuid
        tmpl.id = uuid.uuid4()

        rng = random.Random("seed")
        picks = []
        for w in range(6):
            week_monday = date(2026, 6, 1) + timedelta(weeks=w)
            assignments, _, _ = TaskAssignmentService._compute_assignments(
                rng,
                test_family.id,
                week_monday,
                regular_templates=[],
                bonus_templates=[tmpl],
                members=members,
            )
            picks.append(assignments[0].assigned_to)
        # Different members should appear; not all the same.
        assert len(set(picks)) >= 2

    def test_claim_mode_one_per_member(self, test_family):
        members = _members(test_family, 3)
        tmpl = TaskTemplate(
            title="Open gig",
            points=20,
            effort_level=1,
            interval_days=7,
            is_bonus=True,
            gig_mode="claim",
            family_id=test_family.id,
        )
        import uuid
        tmpl.id = uuid.uuid4()

        rng = random.Random("seed")
        week_monday = date(2026, 6, 1)
        assignments, _, _ = TaskAssignmentService._compute_assignments(
            rng,
            test_family.id,
            week_monday,
            regular_templates=[],
            bonus_templates=[tmpl],
            members=members,
        )
        # claim mode: one row per member
        assert len(assignments) == 3
