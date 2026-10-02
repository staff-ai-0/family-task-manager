# UX-D1 follow-up — A Celebrated Rank Never Drops — Design

**Date:** 2026-10-01
**Status:** design approved in conversation 2026-10-01; awaiting written-spec review
**Program:** UX/GUI program, follow-up to sub-project **D1** (streak + rank, PRs #287 / #289).
**Amends:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md` (section "Ranks").

## Goal

A kid never sees their rank name go backwards after they have celebrated it, while the XP numbers stay truthful.

**The problem today.** XP nets parent corrections: reopening a chore or re-splitting a shared gig writes a negative row, and XP drops by that amount (D1, deliberately — otherwise a redone chore would count twice). Rank is read straight from XP, so a correction near a threshold demotes a kid right after the "You're now Explorer!" celebration: at 305 XP, a reopened 20-point chore shows "Helper" again.

**Decision (user, 2026-10-01):** XP keeps netting corrections; the rank shown is never lower than the highest rank the kid has already celebrated. This matches what D2 chose for badges: a number can go down, earned recognition does not.

**Not in this change:** how XP is computed, the rank thresholds or names, the celebration modal, badges, the streak, any new stored field.

## Rule

`users.last_seen_rank` already stores the highest rank whose celebration the kid dismissed (NULL = none; it only ever moves up — `POST /api/progress/me/ack-rank`).

**Shown rank** `= max(rank_for_xp(xp), last_seen_rank or 1)`, clamped to 1–10.

Everything that describes the rank follows the shown rank:

- `rank` — the shown rank.
- `rank_floor_xp` — the threshold of the shown rank.
- `next_rank_xp` — the threshold of the rank after the shown rank (null at rank 10).
- `xp` — unchanged: the true, netted XP. It can now be below `rank_floor_xp`.

Consequences:

- **After a correction below a celebrated rank:** the name and number stay ("Estrella · 4/10"), the bar is empty, and the label gives the true distance ("450 XP para Súper Ayudante"). Earning the points back fills the bar again.
- **No second celebration:** `celebrate_rank` stays `rank if rank > last_seen_rank else None`. With the shown rank this is non-null exactly when the XP rank exceeds the last celebrated one, as before; regaining a held rank never replays the modal.
- **A rank reached but not yet celebrated is not held.** If a correction lands before the kid dismissed that rank's celebration, the rank follows XP. (The modal opens on the kid's next visit, so this window is short.)
- **The ack is unchanged:** it still clamps to the rank the kid's XP supports and only moves up, so the held rank can never be raised by a client.

## Backend

- **`app/services/progress_service.py`** — one new pure function next to `rank_for_xp`:
  `shown_rank(xp: int, last_seen_rank: int | None) -> int` — `max(rank_for_xp(xp), min(max(last_seen_rank or 1, 1), MAX_RANK))`.
  `ProgressService.progress_for` uses it for `rank`, and derives `rank_floor_xp` and `next_rank_xp` from that rank. `celebrate_rank` keeps comparing against `last_seen_rank`.
- **`app/services/oversight_service.py`** — `KidSummary.rank` uses `shown_rank(xp, kid.last_seen_rank)`, so the parent hub row shows the same rank name the kid sees.
- These are the only two places a rank is computed. `ack_rank` is not changed. No schema change, no migration.

## Frontend

No change. `progressView` (`lib/progress.ts`) already clamps the bar at 0 % when `xp` is below `rank_floor_xp` and already prints `next_rank_xp − xp`. One vitest case pins both for an `xp` below the floor.

## Testing

- **Pure (pytest):** `shown_rank` — the celebrated rank wins when XP has dropped; the XP rank wins when it is higher; `None` and 0 behave as rank 1; values above 10 are clamped.
- **Service + API (pytest, test DB):**
  - a kid at rank 4 who acked it, then loses 100 XP to a correction → `GET /api/progress/me` returns `rank 4`, `rank_floor_xp 600`, `next_rank_xp 1000`, the true `xp`, and `celebrate_rank` null;
  - earning the XP back does not produce a `celebrate_rank` for rank 4 again;
  - a kid who reached rank 4 but never acked it, then drops below it → rank follows XP (3);
  - a later real rank-up above the held rank still celebrates;
  - `KidSummary.rank` shows the held rank;
  - `ack-rank` still cannot raise `last_seen_rank` above the XP-supported rank.
- **Frontend (vitest):** `progressView` with `xp` below `rank_floor_xp` → `barPct 0` and the honest "XP to next" label.
- **After deploy (prod, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` only):** `sofia.demo` and `diego.demo` still show the ranks they celebrated; nothing else on the kid home changes.

## Docs

- `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`, section "Ranks": add the shown-rank rule and a pointer to this spec.
- `CLAUDE.md`, Progress row: after the XP definition, add that the rank shown never drops below the last celebrated rank (`shown_rank`), while XP itself nets parent corrections.
