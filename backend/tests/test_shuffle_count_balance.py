"""Balance = points AND chore-count AND turn-taking, not points alone.

Prod 2026-08-10 (Juan's family): the balancer hit near-perfect point parity
(170/170/170/180) while handing one member 17 chores vs 13 — and the
member-balance pass concentrated 4 of 6 turns of a pinned rotation on the
point-lightest member (1/1/4), destroying the "take turns" intent. Points
stay the PRIMARY fairness metric; these tests pin the secondary invariants:

1. A pinned rotation's occurrences never concentrate beyond a member's fair
   share ceil(occurrences / list_size) — balancing moves must respect turns.
2. Chore COUNTS converge (spread <= 1) whenever the template mix makes that
   feasible at point parity — via point-neutral bundle swaps (one 20-pt
   chore for two 10-pt chores).
"""

import math
import random
import uuid
from collections import Counter
from datetime import date

from app.models.task_template import TaskTemplate, AssignmentType
from app.models.user import User, UserRole
from app.services.task_assignment_service import TaskAssignmentService

WEEK = date(2026, 8, 10)


def _member(family, name, role=UserRole.PARENT):
    u = User(
        email=f"{name.lower()}@example.test",
        password_hash="x",
        name=name,
        role=role,
        family_id=family.id,
        is_active=True,
    )
    u.id = uuid.uuid4()
    return u


def _tmpl(family, title, points, interval, atype, members=None, roles=None):
    t = TaskTemplate(
        title=title,
        points=points,
        effort_level=1,
        interval_days=interval,
        is_bonus=False,
        assignment_type=atype,
        assigned_user_ids=[str(m.id) for m in members] if members else None,
        allowed_roles=roles,
        family_id=family.id,
    )
    t.id = uuid.uuid4()
    return t


def _run(family, templates, members, rest_days=None):
    rng = random.Random(f"{family.id}:{WEEK.isoformat()}")
    assignments, totals, skipped = TaskAssignmentService._compute_assignments(
        rng,
        family.id,
        WEEK,
        regular_templates=templates,
        bonus_templates=[],
        members=members,
        today=WEEK,
        rest_days=rest_days,
    )
    assert skipped == []
    return assignments


def _counts(assignments, members):
    c = Counter(a.assigned_to for a in assignments)
    return [c.get(m.id, 0) for m in members]


def _points(assignments, templates, members):
    pts = {t.id: t.points for t in templates}
    tot = Counter()
    for a in assignments:
        tot[a.assigned_to] += pts[a.template_id]
    return [tot.get(m.id, 0) for m in members]


class TestRotationConcentrationCap:
    def test_balancing_never_dumps_a_rotation_on_one_member(self, test_family):
        # Prod repro: 20-pt daily rotation over three members, two of whom
        # each carry a FIXED daily 10-pt chore. Point-balancing used to give
        # the unpinned member 5 of the 7 rotation turns (prod: 1/1/4).
        # Turn-taking bound: nobody exceeds ceil(7/3) = 3 turns.
        a, b, m = (_member(test_family, n) for n in ("Ana", "Ariana", "Mayra"))
        rot = _tmpl(test_family, "rot20", 20, 1, AssignmentType.ROTATE,
                    members=[a, b, m])
        fixed_a = _tmpl(test_family, "fixA", 10, 1, AssignmentType.FIXED,
                        members=[a])
        fixed_b = _tmpl(test_family, "fixB", 10, 1, AssignmentType.FIXED,
                        members=[b])
        assignments = _run(test_family, [rot, fixed_a, fixed_b], [a, b, m])

        turns = Counter(x.assigned_to for x in assignments
                        if x.template_id == rot.id)
        occurrences = sum(turns.values())
        assert occurrences == 7
        cap = math.ceil(occurrences / 3)
        assert max(turns.values()) <= cap, (
            f"rotation concentrated: {sorted(turns.values())} (cap {cap})"
        )


class TestCountBalance:
    def test_counts_converge_when_denominations_allow(self, test_family):
        # Two members. A carries a FIXED daily 10-pt chore (7 occ, 70 pts).
        # Shared pool: one 20-pt daily AUTO + one 10-pt daily AUTO. Point
        # parity (140/140) is reachable at counts 11/10 (A: fixed 7 + 3x20
        # + 1x10). The old balancer stopped at point parity with counts
        # like 13/8 — count spread must now close to <= 1.
        a, b = _member(test_family, "Juan"), _member(test_family, "Ana")
        fixed_a = _tmpl(test_family, "fixJ", 10, 1, AssignmentType.FIXED,
                        members=[a])
        t20 = _tmpl(test_family, "auto20", 20, 1, AssignmentType.AUTO)
        t10 = _tmpl(test_family, "auto10", 10, 1, AssignmentType.AUTO)
        templates = [fixed_a, t20, t10]
        assignments = _run(test_family, templates, [a, b])

        counts = _counts(assignments, [a, b])
        points = _points(assignments, templates, [a, b])
        assert max(points) - min(points) <= 20, points  # parity stays primary
        assert max(counts) - min(counts) <= 1, (
            f"counts diverged: {counts} at points {points}"
        )

    def test_prod_family_mirror_counts_and_turns(self, test_family):
        # Exact mirror of the prod family config (post 2026-08-10 change:
        # Juan added to both 20-pt rotations; Sunday rest day). 57 chores,
        # 690 pts over 4 members. Feasible: counts {15,14,14,14} at point
        # spread <= 20. Old balancer: counts 13..16 (spread 3 on prod,
        # 2 in this mirror) and "2ndo piso" turns 1/1/4/0.
        ana = _member(test_family, "Ana", UserRole.TEEN)
        ari = _member(test_family, "Ariana", UserRole.TEEN)
        may = _member(test_family, "Mayra", UserRole.PARENT)
        juan = _member(test_family, "Juan", UserRole.PARENT)
        members = [ana, ari, may, juan]
        pt = ["parent", "teen"]
        f = test_family
        rot, fix, auto = (AssignmentType.ROTATE, AssignmentType.FIXED,
                          AssignmentType.AUTO)
        templates = [
            _tmpl(f, "cocinar", 10, 7, rot, roles=pt),
            _tmpl(f, "3er piso", 10, 1, fix, members=[juan]),
            _tmpl(f, "escaleras", 10, 1, auto),
            _tmpl(f, "2ndo piso", 20, 1, rot, members=[ana, ari, may, juan]),
            _tmpl(f, "planta baja", 20, 1, rot, members=[ana, ari, juan]),
            _tmpl(f, "platos", 10, 1, rot, roles=pt),
            _tmpl(f, "patio", 10, 7, fix, members=[juan]),
            _tmpl(f, "bano 1er", 10, 7, rot, members=[ana, ari, may]),
            _tmpl(f, "bano 3er", 10, 7, fix, members=[juan]),
            _tmpl(f, "bano estancia", 10, 7, rot, roles=pt),
            _tmpl(f, "barra", 10, 1, rot, members=[ana, ari]),
            _tmpl(f, "ordenar 3er", 10, 7, fix, members=[juan]),
            _tmpl(f, "closet", 10, 7, rot, roles=pt),
            _tmpl(f, "pasear", 10, 1, rot, members=[ana, ari, juan], roles=pt),
            _tmpl(f, "basura banos", 10, 3, rot, members=[ana, ari]),
            _tmpl(f, "basura cocina", 10, 1, rot, roles=pt),
        ]
        assignments = _run(f, templates, members, rest_days=[6])

        counts = _counts(assignments, members)
        points = _points(assignments, templates, members)
        assert sum(counts) == 57
        assert max(points) - min(points) <= 20, points
        assert max(counts) - min(counts) <= 1, (
            f"counts diverged: {counts} at points {points}"
        )

        # Turn-taking on every pinned rotation.
        by_title = {t.title: t for t in templates}
        for title in ("2ndo piso", "planta baja", "barra", "pasear"):
            t = by_title[title]
            turns = Counter(x.assigned_to for x in assignments
                            if x.template_id == t.id)
            occ = sum(turns.values())
            cap = math.ceil(occ / len(t.assigned_user_ids))
            assert max(turns.values()) <= cap, (
                f"{title}: turns {sorted(turns.values())} exceed cap {cap}"
            )
