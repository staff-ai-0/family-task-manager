"""Partial-credit (grade) arithmetic for the parent review queue.

ONE formula, one place. The award path and the parent payouts dashboard each
used to roll their own and they disagreed: awards used integer half-up while
the dashboard used Python's ``round()``, which is banker's rounding — so a
25-point chore graded at 50% credited the kid 13 points but the dashboard
showed 12. Every grade-scaling call site must come through here.

Inputs are non-negative integers (``partial_credit_pct`` is CHECK-constrained
0..100 and template points are never negative), which is what makes floor
division genuine half-up here — it would round .5 the wrong way for a negative
input, a case these call sites cannot produce.

Two scales exist because the weekly paycheck sums many graded chores before it
rounds once: ``grade_credit_units`` keeps the ×100 (points × percent) scale so
the sum stays exact, and ``units_to_points`` collapses it at the very end under
the same half-up rule.
"""

# One unit = one template point × one percent of credit.
UNIT_SCALE = 100


def grade_credit_units(points: int, pct: int) -> int:
    """Grade-scaled credit of `points` at `pct` percent, in ×100 units."""
    return int(points) * int(pct)


def units_to_points(units: int) -> int:
    """Collapse ×100 credit units back to whole points, half-up."""
    return (int(units) + UNIT_SCALE // 2) // UNIT_SCALE


def grade_credit_points(points: int, pct: int) -> int:
    """Whole points credited for `points` graded at `pct` percent, half-up.

    25 points at 50% is 13, not 12 — the boundary the two old copies split on.
    """
    return units_to_points(grade_credit_units(points, pct))
