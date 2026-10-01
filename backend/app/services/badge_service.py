"""UX-D2 badges: 8 families × 3 tiers, earned from history and kept forever —
see docs/superpowers/specs/2026-10-01-ux-d2-badges-design.md.

Counts are derived on read (like UX-D1); only EARNED tiers are stored
(`user_badges`), so a later parent correction never takes a badge away.
Thresholds live here and nowhere else; names and emoji live only in
frontend/src/lib/badges.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.modules import effective_modules


@dataclass(frozen=True)
class BadgeDef:
    thresholds: tuple[int, int, int]   # count needed for bronze, silver, gold
    module: Optional[str] = None       # togglable module this family belongs to


# Insertion order is the catalog order every surface renders.
BADGES: dict[str, BadgeDef] = {
    "chores": BadgeDef((10, 50, 200)),
    "streak": BadgeDef((7, 30, 100)),
    "perfect_week": BadgeDef((1, 4, 12)),
    "extra_mile": BadgeDef((1, 10, 50)),
    "gigs": BadgeDef((1, 10, 50), module="gigs"),
    "saver": BadgeDef((1, 3, 10), module="gigs"),
    "rewards": BadgeDef((1, 5, 20)),
    "cup": BadgeDef((1, 3, 10)),
}
MAX_TIER = 3


def tiers_for(count: int, thresholds: tuple[int, ...]) -> int:
    """How many tiers a count has reached (0..MAX_TIER)."""
    return sum(1 for threshold in thresholds if count >= threshold)


def next_target(tier: int, thresholds: tuple[int, ...]) -> Optional[int]:
    """The count needed for the tier after `tier`; None once gold is held."""
    return thresholds[tier] if 0 <= tier < len(thresholds) else None


def visible_badges(enabled_modules: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Catalog keys a family sees: a family whose module is off is skipped
    (not evaluated, not returned). Stored rows are kept regardless."""
    on = effective_modules(enabled_modules)
    return tuple(key for key, badge in BADGES.items() if badge.module is None or badge.module in on)
