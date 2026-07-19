"""Per-family module registry.

A family may switch optional product modules off to keep the app focused
(scope segregation). ``families.enabled_modules`` stores the list of ENABLED
togglable keys; NULL means "all on" (the pre-feature default, and what every
existing family keeps seeing). Core surfaces — tasks, rewards, consequences,
points, members, settings — are not togglable and never appear in the list.

Gating is a UX concern (nav + page redirects); backend API routes stay live
for all modules — the data is same-family either way.
"""
from __future__ import annotations

from typing import Iterable, Optional

# Keys map to product surfaces, not single pages:
#   meals · shopping · calendar · pet — standalone organizers
#   chat  — family chat + DMs
#   budget — the full budget module
#   gigs  — gig board + Family Bank cash surfaces (kid bank page, payouts)
TOGGLABLE_MODULES = frozenset(
    {"meals", "shopping", "calendar", "pet", "chat", "budget", "gigs"}
)


def effective_modules(enabled: Optional[Iterable[str]]) -> set[str]:
    """Resolve a stored enabled_modules value to the effective enabled set.

    NULL/None → every togglable module (all on). Unknown keys are ignored
    defensively (schema validation rejects them on write).
    """
    if enabled is None:
        return set(TOGGLABLE_MODULES)
    return {m for m in enabled if m in TOGGLABLE_MODULES}
