# Chore rules v2 — expiry, weekly pay ladder, teen alarms (project 1 of 3)

Status: DRAFT for approval · 2026-11-12 · builds on Early Bird (PRs #312–314,
spec `2026-11-07-early-bird-deadline-design.md`).

Program (agreed order, one design each):
1. **This doc** — chore cutoff + up-for-grabs, weekly pay ladder, teen alarms.
2. Rules announcement to all members + "I understand and accept" checkbox.
3. Monthly show-and-tell + AI baseline photos per task.

## Intent and why

The parents want chores to have real consequences and a real reward for
doing them early: a chore not done by the evening cutoff stops paying its
owner and becomes available to anyone; finishing the week fully and early
pays extra; finishing under 60% pays no base pay. Teens get reminded.
The "why" the parents gave is accountability for teens; the design keeps
every rung explainable to a kid in one sentence.

## The rules (as agreed)

All percentages are over the **Mon–Sun week**, family timezone, counting
the family's *covered* chores (mandatory chores; bonus tasks and templates
flagged `early_bird_exempt` stay out, as today).

1. **Cutoff** (default **20:30**, configurable per family). A chore not
   completed by the cutoff of its due day **does not count as completed**
   and pays its owner nothing.
2. **Up for grabs: 20:30 → 22:30** (both configurable; grab window end is
   configurable too). During the window any active family member (not only
   kids with a clear list) may take an unfinished chore. Taker gets an
   ordinary row (ordinary points, never early). After 22:30 the chore is
   closed as missed for the owner.
3. **Pay ladder** (non-`flat` allowance modes):

   | Completed by cutoff | Pay |
   |---|---|
   | < 60 % | no base pay for the week |
   | 60–99 % | variable: each completed task pays its own value |
   | 100 % | all tasks pay, **plus** a bonus on base pay by early share |

   Early share = % of the week's chores done **before the early deadline
   (11:00 default)**: ≥80 % → +5 %, ≥90 % → +10 %, 100 % → +15 %.
   Under 80 % early → no bonus. **The bonus requires 100 % completion.**
4. **Streak prize** stays, unchanged in mechanism (every 3rd consecutive
   fully-early week), default amount **$380** (was $500).
5. **Teen alarms**: two pushes/day listing the teen's pending chores;
   default **15:00 and 19:00**, configurable. Teens (role TEEN) only.

## Goals / non-goals / anti-goals

Goals: one weekly number drives every rung; projection, release and
receipt-scan agree on it; kids see a live meter.
Non-goals: the rules announcement/acceptance (project 2); reference photos
and AI grading (project 3); changing the per-chore +20 % early bonus
(`early_bird_bonus_pct`) — untouched.
Anti-goals: two sources of truth for "% done"; a bonus computed anywhere
but `BankService`; a cutoff that silently differs between the kid card,
the sweep and the paycheck.

## Approaches considered (picked: A)

- **A. Extend Early Bird in place** (picked) — new config columns next to
  the existing ones; `week_status` stays the only place a week result is
  computed; ladder applied in `BankService._early_bird_bonus` + one new
  floor check in the same paycheck path. Trade-off: feature stays
  per-family opt-in.
- B. Parallel "rules v2" module — duplicates week/deadline logic. Rejected.
- C. Versioned rules table — best for project 2 but rewrites week-old
  logic. Rejected for now; instead a `families.rules_version` integer that
  bumps when parents change these settings, which is all project 2 needs.

## Design

**Config** (new `families` columns, Alembic, nullable-safe defaults):
`chore_cutoff` Time (20:30), `grab_window_end` Time (22:30),
`teen_alarm_1` / `teen_alarm_2` Time (15:00 / 19:00), `rules_version`
Integer (default 1, bumped on any change to the settings above, the
early deadline, or the streak amount). `early_bird_streak_cents` default
for NEW families → 38000; existing families keep their stored value
unless the parent changes it (data decision, see Left to the builder).
`early_bird_week_pct` is retired as a flat bonus (ladder replaces it);
column kept, no longer read.

**Pure rules** (`early_bird_rules.py`): add `cutoff` to `DayTimes`;
`chore_state` gains `done_by_cutoff` vs `early` distinction (a chore done
after the cutoff counts "missed" even if the owner later ticks it);
new `week_ladder(completed, covered, early)` returning
`{no_pay | per_task | full_bonus(pct)}`.

**Service/bank**: `week_status` returns completed %, early %, tier.
`BankService` pays per the ladder: <60 % → base 0; 60–99 % → existing
per-task unit math (`_chore_units`) over completed rows only; 100 % →
all units + `_early_bird_bonus` (pct from the ladder). Modes: applies to
`chore_proportional`, `chore_gated`, `points_rate`; `flat` excluded as
today. Receipt-scan confirm and top-up still pay the receipt amount; the
ladder only drives the computed base the adjustment is measured against.

**Expiry/grabs**: grabs derive on read (as today) but open at the cutoff
and close at `grab_window_end`; the owner cannot complete an expired row
(409, copy: "this chore is open to the family"). Take-eligibility widens
to any active member whose role is in the template's `allowed_roles`.
Both halves of a take stay locked (existing invariant).

**Alarms**: `ping_service` gets a teen-only sweep at the two times
(hourly job already runs; fire when family-local hour matches, once per
slot per day; notification row is the only send record). Skips teens with
nothing pending. Feature-off families get nothing.

**UI**: parent settings → family (`earlyBirdSettings.ts`) gets cutoff,
grab end, alarm times, streak amount; kid card (`EarlyBirdCard.astro`)
shows the weekly meter "72 % this week — 60 % to get paid, 100 % for the
bonus". Copy only in `lib/earlyBird.ts`. ES/EN.

**Tests**: ladder boundaries (59/60/79/99/100 %, early 79/80/89/90/99/100),
bonus-needs-100 %, cutoff exactness, grab window open/closed, owner 409,
alarm once-per-slot, `rules_version` bump, migration round-trip, plus an
exact mirror of the real family (4 members) per repo convention.

## Left to the builder (my calls, mark if wrong)

- Streak prize for existing families: keep stored value (prod has $500)
  vs bulk-set to $380 — I'd NOT bulk-update money config; surface it in
  settings. **Needs the parents' say before deploy.**
- "Completed" counts a chore PENDING review with the existing grace rule.
- A chore graded `missed` or `partial` counts as not-completed for the
  ladder percentage (partial pays its scaled points under per-task).
- `chore_gated` already gates payout; reconcile so the 60 % floor and its
  gate do not double-apply.
