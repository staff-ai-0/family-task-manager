# Remove the evening release — a chore stays its owner's all day

Date: 2026-11-25. Approved by the owner in chat ("dale"). Supersedes the
"evening cutoff" and "up for grabs" rules of
`2026-11-12-chore-rules-v2-design.md` (R6 and the grab window). Everything
else in that spec stands.

## Intent and why

Chore rules v2 released a chore to the family at the evening cutoff (20:30 in
the owner's family): the owner could no longer report it and any member could
take it until 22:30. In real use this does not work for the family — chores
are still being done and reported in the evening. Owner's ruling:

> "vamos a remover el que la tarea se libere a las 8 pm, nunca se libera, el
> owner la puede reportar hasta 11:59pm"

Prod evidence (2026-11-25): one family has Early Bird on (since 2026-11-16),
cutoff 20:30 / grab end 22:30; exactly ONE chore was ever taken.

## The rule now

- A chore is never released. It is its owner's for its whole due day.
- The owner can report it until 23:59 family-local (the day ends at midnight).
- After midnight it behaves exactly as an untaken chore did after the old grab
  window: not done for the weekly pay ladder, gone from the kid's lists and
  gates, still visible to parents as a miss, and a parent can still record it
  with "mark done for kid" (never early, exempt from the time test).

## Goals / non-goals / anti-goals

- Goal: the owner can complete a covered chore any time on its due day.
- Goal: no "up for grabs" anywhere — no cards, pushes, endpoints or settings.
- Non-goal: changing the early deadline (11:00), the per-chore bonus, the
  weekly ladder thresholds, the streak, teen alarms, rules acceptance.
- Non-goal: a late-reporting path the next day ("Atrasadas" for covered
  chores). Rejected by the owner's wording ("hasta 11:59pm").
- Anti-goal: rewriting history. The one existing take (owner row `taken`,
  taker row with `taken_from_id`) stays valid and locked as it is today.

## Approaches considered (picked: B)

- **A — settings only.** Raise the cutoff in parent settings. Caps at 23:00
  and the grab window still opens. Does not meet the ruling.
- **B — the day's cutoff becomes midnight, grabs removed (picked).**
  `day_times().cutoff` is the start of the next family-local day; every
  consumer that already asks `day_times` (expiry, "completed in time", week
  finality, alarm expiry) follows with no new rule. The grab feature is
  deleted end to end. `chore_cutoff` / `grab_window_end` stay in the table,
  unread (same treatment as the retired `early_bird_week_pct`): no schema
  migration, trivial rollback.
- **C — full teardown.** Also drop the two columns, the `taken` status and
  `taken_from_id`. Needs an enum-value removal and a rewrite of a row that
  really happened, for no user-visible gain. Rejected.

## Design

Backend
- `early_bird_rules.py`: `EarlyBirdConfig` loses `cutoff` and `grab_end`;
  `DayTimes` loses `grab_end`; `day_times().cutoff` = midnight ending the day.
  `DAY_END_LABEL = "23:59"` is the one display value for "last minute".
  Removed: `grab_window_open`, `GRABS_PUSH_WINDOW`, `role_may_take`, the
  `"grabs"` reminder stage. `alarm_slot` no longer clamps to the cutoff (an
  alarm is at most 23:00 + 30 min, always inside the day).
- `early_bird_service.py`: removed `GrabRow`, `grabbable`, `can_take`,
  `caller_block`, `_not_eligible`, `take`, `grab_list`, `_push_grabs`, and the
  sweep's `grabs` counter. `/me` keeps `cutoff_at` (now the end of the day —
  the kid card counts down to it) and drops `grab_end_at`, `grabs`,
  `take_block`. No mobile client reads these (checked the sibling repos).
- Routes: `GET /api/early-bird/grabs` and `POST …/grabs/{id}/take` removed.
- Family settings: `chore_cutoff` / `grab_window_end` leave `FamilyUpdate`,
  `FamilyResponse`, the cross-field checks and the rules-version trigger.
  Alarms keep their own checks (06:00–23:00, first before second).
- Rules: `RulesSnapshot` drops `cutoff` / `grab_end`, gains `day_end`
  ("23:59"). Stored snapshots of earlier acceptances keep their old keys (they
  record what was shown then).
- Data migration `remove_evening_release`: `rules_version + 1` for every
  family, so each member re-reads and re-accepts the changed rules (the sheet
  shows on their next visit; no notification is sent by the deploy). The
  downgrade subtracts one, never below 1.
- Kept as is: `AssignmentStatus.TAKEN`, `taken_from_id` / `taken_by` /
  `taken_at`, the locks on both halves of a take, `expired_for_owner` and its
  consumers, `NotificationType.UP_FOR_GRABS` / `CHORE_TAKEN` and their
  templates (old notification rows carry those types), `ChoreExpiredException`.
- Teen alarm text: "due by 23:59" (param `cutoff` = `DAY_END_LABEL`).

Frontend
- Deleted: `components/home/UpForGrabs.astro`, `components/home/GrabsCard.astro`
  and their mounts (kid home, parent hub + its `/api/early-bird/grabs` fetch).
- `lib/earlyBird.ts`: grab types, copy and helpers removed; card state `late`
  removed (unreachable — after midnight "today" is a new day);
  `before_cutoff` headline says the chores can be reported until 23:59.
- `lib/completeMessages.ts`: `chore_expired` says the chore's day is over and
  that a parent can mark it.
- Settings (`parent/settings/family.astro`, `lib/earlyBirdSettings.ts`): the
  "evening cutoff" and "end of up for grabs" fields, their validation and
  payload keys are removed; the alarm hint no longer mentions the cutoff.
- `lib/rulesNotice.ts`: the cutoff and grabs lines become one "end of day"
  line rendered from `rules.day_end`.

Docs: `docs/USER_GUIDE_{ES,EN}.md` Early Bird section, `CLAUDE.md` (Early bird
row + current state), a superseded note in the v2 spec.

Tests: grab tests deleted; cutoff tests re-pinned to midnight (a completion
at 21:00 succeeds and counts for the ladder; the same chore after midnight is
409 `chore_expired`); settings/rules/sweep/frontend tests follow the removed
fields.

## Left to the builder (my calls)

- Rule line wording (ES/EN) and the exact `chore_expired` message.
- Whether helper names keep the word "cutoff" (they do: it is still the
  day's cutoff, only its instant moved).
- Bumping `rules_version` for every family rather than only those with Early
  Bird on: a family that accepted v1 and later switched off would otherwise
  come back on with a stale acceptance.
