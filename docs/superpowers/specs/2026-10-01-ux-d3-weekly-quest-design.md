# UX-D3 — Weekly Quest — Design

**Date:** 2026-10-01
**Status:** design approved in conversation 2026-10-01; awaiting written-spec review
**Program:** UX/GUI program, sub-project **D3** of D (progression & engagement loop). D1 streak + rank (PRs #287, #289) and D2 badges (PR #290) shipped. D4 = mystery reward + app-icon badge + smart pushes.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row D; layered progression — daily streak → weekly challenge → rank → badges — outlasts pet/points novelty; PointUp and Nimbi both run weekly challenges).
**Builds on:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`, `docs/superpowers/specs/2026-10-01-ux-d2-badges-design.md`.

## Goal

Give kids and teens a reason to come back mid-week that the daily streak and the long-term rank do not: one personal goal per week, sized to the kid, with a points bonus for reaching it. Independent of the virtual pet.

It must not be a third "do your chores this week" surface. Two weekly things already exist (`family_cup_service.py`): the **Family Cup** (points leaderboard between members, resets Monday) and the cooperative **boss battle** (family-wide HP = the week's chore points). The quest is personal, varied week to week, and has a twist beyond raw completion (on time, every chore of a day, extra work).

**Decisions (user, 2026-10-01):**
- Personal weekly quest, not a reworked boss battle and not parent-authored.
- Reward = bonus points into the existing points ledger. No cash, no new currency.
- One quest per kid per week, picked automatically. No choosing, no multiple quests.
- Parents get one family setting: the bonus amount (default 20; 0 switches quests off).
- A card on the kid home, celebrated in place (no modal); the parent hub shows each kid's quest.
- Created and paid on read, like D2 badges: no scheduled job, no hooks in other services.

**Not in D3:** kid-chosen or parent-authored quests, more than one quest per week, cash rewards, quest notifications or pushes (D4), a quest badge family, quest history, changes to the Family Cup or boss battle, pet effects.

## Rules

### Who and when

Kids and teens only (roles CHILD, TEEN — `KID_ROLES`). One quest per kid per **week**: Monday–Sunday in the family's timezone (`families.timezone`), the same week D1 and the Family Cup use.

### Quest types

| Key | Emoji | Goal text ES / EN | Progress = this week's count of | Offered when |
|---|---|---|---|---|
| `on_time` | ⏰ | "Termina {n} tareas a tiempo" / "Finish {n} chores on time" | non-bonus assignments with `week_of` = this week that are done on time and count (see below) | the kid has at least one open chore dated today or later this week |
| `perfect_days` | ✨ | "Logra {n} días perfectos" / "Have {n} perfect days" | days of this week that have ≥ 1 due chore and whose every due chore is done on time and counts | at least one day of this week can still become perfect (no failed chore, at least one chore still open or awaiting review) |
| `extra_mile` | 🚀 | "Haz {n} tareas extra" / "Do {n} bonus tasks" | bonus assignments (`is_bonus = true`) with `week_of` = this week that are completed and count | the kid has at least one bonus task this week that is still open (dated today or later) or awaiting review |
| `go_getter` | 💼 | "Logra {n} gigs aprobadas" / "Get {n} gigs approved" | `gig_claims` of the kid with `status = approved` and `approved_at` inside this week | the `gigs` module is on, the kid is not in star mode (star-mode kids have no gig board), and at least one active, approved offering is open to the kid's role, and that the kid does not already hold an approved claim on |

"n" uses the singular form at 1 ("1 tarea", "1 chore", "1 día perfecto", "1 perfect day", …). The `go_getter` text uses the family's own word for a gig (`families.gig_term`: "gig" or "chamba").

**Counts** (the strict rule D2 adopted at its final review): an assignment counts when `status = completed`, it is not graded `missed`, and `approval_status` is `none` or `approved`. Work awaiting a parent's review does not count until approved; rejected work never counts. The bonus is real points, so the quest must not pay on work a parent may still reject.

**On time** is D1's rule: `completed_at`, in the family timezone, falls on or before the assignment's `assigned_date`; a legacy completed row with no `completed_at` counts as on time. A **due chore** is a non-bonus, non-cancelled assignment.

### Which quest a kid gets

Rotation order: `on_time`, `extra_mile`, `perfect_days`, `go_getter`. The starting index for a kid in a week is `(week_number + kid_offset) mod 4`, where `week_number` is the Monday's ordinal ÷ 7 and `kid_offset` is derived from the kid's id, so siblings usually differ in the same week and each kid moves one step per week. From the starting index, the first type that is **offered** (table above) **and achievable** (below) is the kid's quest. If none qualifies, there is no quest at that moment; the next read tries again.

### Goal size

For the chosen type:

1. `stretch = max(default, ceil(1.1 × average of the kid's count for that type over the previous 4 full weeks))` — computed in integers as `ceil(11 × four-week total ÷ 40)`. Defaults (also the starting goal for a kid with no history): `on_time` 3, `perfect_days` 2, `extra_mile` 1, `go_getter` 1.
2. `ceiling` = what is still achievable this week = already done + still possible:
   - `on_time`: done so far + chores that can still count (open chores dated today or later, plus on-time work awaiting review);
   - `perfect_days`: perfect days so far + days that can still become perfect;
   - `extra_mile`: done so far + the kid's bonus tasks that can still count (open and dated today or later, or awaiting review);
   - `go_getter`: done so far + the gig offerings the kid can still get approved, capped at 7 in total.
3. `target = min(stretch, ceiling)`.
4. The quest is **achievable** only if `target ≥ done so far + 1`. A quest never starts finished: if the type's target would already be met, that type is skipped.

Decided at the final review: the first draft treated both as unbounded, which made the goal regularly unwinnable — bonus tasks are finite dated rows, and single-slot gigs close on their first approval.

The target and the type are fixed when the quest row is created and never change afterwards, even if chores are added, cancelled or corrected.

### Bonus

- The amount is the family's `quest_bonus_points` at the moment the quest is created, copied onto the quest row. Default 20.
- The bonus is paid **once**, the first time a read finds `progress ≥ target`, as a `point_transactions` row of type `bonus` (the same pattern as routine completion, `routine_service._award_completion`): it raises the kid's spendable points, and through D1's existing rule it counts toward XP and rank. It also counts toward that week's Family Cup standing; parents have no quests, so kids gain a small edge there.
- Late settlement: every read also settles **last week's** quest, so a goal reached on Sunday night, or reached by a parent approving late, is still paid when the kid next opens the app. Quests older than last week are never settled.
- Once paid, the bonus is never taken back, even if a later parent correction lowers the count.
- `quest_bonus_points = 0` switches quests off for the family: no quest is created, no bonus is paid (including for a quest already in flight), and no card or hub chip shows.

### The "done" moment

A paid quest starts **unseen**. The kid home's quest card shows it as done with a one-time confetti and marks it seen. This is not a modal, so it does not take part in the "one modal per load" rule and cannot deadlock with the welcome tour. If last week's quest was paid and is still unseen, the card shows that result first ("La misión de la semana pasada: ¡lograda! +20 puntos"), then this week's quest on the next load. For a child in star mode the prize reads "+20 ⭐", like every other points label on that kid's home.

## Backend

### Storage

One Alembic migration after `user_badges`:

- New table `weekly_quests` (model `app/models/weekly_quest.py`):

  | Column | Type | Notes |
  |---|---|---|
  | `id` | UUID PK | |
  | `family_id` | UUID, FK `families.id` ON DELETE CASCADE, NOT NULL, indexed | tenancy |
  | `user_id` | UUID, FK `users.id` ON DELETE CASCADE, NOT NULL, indexed | |
  | `week_start` | Date, NOT NULL | the Monday |
  | `quest` | String(32), NOT NULL | type key |
  | `target` | Integer, NOT NULL, CHECK ≥ 1 | |
  | `bonus_points` | Integer, NOT NULL, CHECK ≥ 0 | copied from the family setting |
  | `created_at` | timestamptz, NOT NULL | |
  | `rewarded_at` | timestamptz, NULL | set when the bonus is paid |
  | `seen_at` | timestamptz, NULL | set when the kid saw the done moment |

  `UNIQUE(family_id, user_id, week_start)`.
- New column `families.quest_bonus_points INTEGER NOT NULL DEFAULT 20`.
- `weekly_quests` is added to `EXPORTED_FAMILY_TABLES` in `family_export_service.py` with a ZIP member `progress/quests.json` (the registry test fails otherwise).

### `app/services/quest_service.py`

Same layout as `progress_service.py` and `badge_service.py`: pure rules on top, family-scoped queries below.

- pure: `QUESTS` (ordered: key → default goal), `rotation(week_start, user_id) -> list[str]` (the 4 keys starting at the kid's index), `size_target(default, avg, done, possible) -> int | None` (None = not achievable).
- queries (every one filters on `family_id` and the kid's user id):
  - `week_counts(db, family_id, user_id, week_start, tz, today) -> dict[str, int]` — this week's count for each type.
  - `history_avg(db, family_id, user_id, week_start, tz) -> dict[str, float]` — per-type average over the previous 4 full weeks.
  - `availability(db, family_id, user, week_start, today, visible_modules) -> dict[str, int | None]` — per type, how many more are still possible this week (`None` = not offered).
  - `sync(db, user) -> QuestResponse` — if the family's bonus is 0, returns `applies: false`. Otherwise: creates this week's row if missing and a type qualifies (`INSERT … ON CONFLICT (family_id, user_id, week_start) DO NOTHING`), settles this week's and last week's rows, and builds the response.
  - `_settle(db, quest, progress) -> bool` — pays once: `UPDATE weekly_quests SET rewarded_at = now() WHERE id = :id AND rewarded_at IS NULL RETURNING id`; only when that returns a row does it lock the user row, add the `bonus` point transaction and raise `users.points`, all in the same commit. A quest with `bonus_points = 0` is marked rewarded without a transaction.
  - `ack(db, user, quest_id) -> None` — sets `seen_at` on the caller's own rewarded row; anyone else's id is ignored silently.
  - `hub_rows(db, family_id, week_start) -> dict[UUID, WeeklyQuest]` — one query for the parent hub.

### API (in `app/api/routes/progress.py`, prefix `/api/progress`)

- `GET /api/progress/quest` → `QuestResponse`:
  ```
  { applies: bool, gig_term: str,
    quest: { id: UUID, quest: str, target: int, progress: int, bonus_points: int,
             week_start: date, days_left: int, completed: bool } | null,
    celebrate: { id: UUID, quest: str, target: int, bonus_points: int, last_week: bool } | null }
  ```
  `quest` is this week's quest (null when none qualifies). `progress` is capped at `target`. `days_left` counts today (Sunday = 1). `completed` = paid. `celebrate` is the oldest paid-and-unseen quest among last week's and this week's (last week's first). `gig_term` is the family's word for a gig. Non-kids, and families with the bonus at 0, get `{ applies: false }`.

  This GET writes (creates the quest, pays the bonus); both writes are idempotent.
- `POST /api/progress/quest/ack` `{ id: UUID }` → 204. Non-kids get 404.

### Parents

- `FamilyUpdate` / `FamilyResponse` (`schemas/family.py`) gain `quest_bonus_points` (`ge=0, le=500`); the existing parent-only family update route persists it.
- `KidSummary` (`schemas/oversight.py`) gains `quest_progress: int | None`, `quest_target: int | None`, `quest_done: bool` — from this week's stored row plus that kid's computed progress. The hub only reads: it never creates or pays a quest, so a kid who has not opened the app this week shows no quest. With the bonus at 0 the three fields stay empty.

## Frontend

- **`lib/quest.ts`** (pure, vitest): `QUEST_META` (emoji + ES/EN goal templates, singular/plural), and
  - `questView(resp, lang)` → `{ emoji, title, progressLabel, barPct, daysLeftLabel, bonusLabel, done, celebrate: { id, title, bonusLabel, lastWeek } | null } | null` (null when the response is missing, `applies` is false, or there is neither a quest nor a celebrate; unknown quest keys → null);
  - `questChip(kid, lang)` → `"🏁 3/5"`, `"🏁 ✓"` or null, for the parent hub (🏁, not 🎯: the hub row already uses 🎯 for the kid's reward goal).
- **`components/home/QuestCard.astro`**, rendered by `KidHome.astro` directly under the task deck:
  - in progress: emoji + goal title, a progress bar with `3/5`, "Quedan {n} días" / "{n} days left" ("Último día" / "Last day" at 1), and the prize "+20 puntos" / "+20 points";
  - done: "¡Misión lograda! +20 puntos" / "Quest done! +20 points" on a mint fill with ink text;
  - when `celebrate` is present the card shows that result, fires `fireConfetti()` once, and POSTs the ack (`keepalive: true`);
  - it refetches `/api/progress/quest` on `ftm:deck-completed` (every completed task) and `ftm:deck-empty` (the event that already refreshes D1's pills) and re-renders bar, label and done state from `questView`.
- **`pages/dashboard.astro`** fetches `/api/progress/quest` in the existing parallel `apiFetch` calls for kid roles and passes the view to `KidHome`.
- **Parent hub:** each kid row shows the quest chip next to the progress line.
- **Parent settings → Family:** a number field "Bono de la misión semanal" / "Weekly quest bonus" (points, 0–500) with the note "0 desactiva las misiones semanales" / "0 turns weekly quests off" and a hint that a change applies from the next quest ("El cambio aplica desde la siguiente misión." / "A change applies from the next quest."), saved through the existing family update.
- Visual system: existing tokens only, ink text on brand fills, no emoji in an `<h1>`; the strict guard stays green. No native dialogs.
- **Failure:** `apiFetch` returns null on error → no card; the rest of the kid home is unaffected.

## Testing

- **Pure (pytest):** `rotation` (order, per-kid offset, one step per week); `size_target` — no history → default, 10 % stretch rounds up, capped by what is possible, not achievable when already met or when nothing is left.
- **Service + API (pytest, test DB):** each type's count from real rows; pending-review and rejected work not counted, approved counted; late or missed chores not counted for `on_time` / `perfect_days`; the quest is created once per week and its target does not change when chores are added later; a type that is not offered is skipped and the next one is used; no quest when nothing qualifies; the bonus is paid exactly once across repeated reads and lands as a `bonus` transaction that raises `users.points`; last week's quest is paid on this week's read, the week before is not; setting at 0 → `applies: false`, nothing created or paid; a sibling's and another family's rows never count; `ack` only marks the caller's own row; parents get `applies: false` on GET and 404 on ack; `quest_bonus_points` validation (negative and > 500 rejected, parent-only); `KidSummary` quest fields; the family-export registry test passes.
- **Migration:** covered by CI's upgrade → step-back → upgrade round-trip.
- **Frontend (vitest):** `questView` null cases, titles in both languages with singular/plural, bar %, days-left labels, done and celebrate states, unknown key; `questChip`; structure tests for `QuestCard` (rendered only behind the view, ack once with keepalive, confetti only on celebrate) and for the settings field; strict visual guard, `astro check`, build.
- **After deploy (prod, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` only):** as `sofia.demo` and `diego.demo` at 390 px — the card shows a quest with a sensible goal; `mariana.demo` hub rows show the chip; the settings field saves and 0 hides the card (then restore 20).

## Docs

- `CLAUDE.md`: extend the Progress row with the weekly quest (types, on-read creation and payment, the strict counting rule, the family setting).
- `docs/USER_GUIDE_{EN,ES}.md`: a "Weekly quest" section (17.5.4) after Badges, including the parent setting.
