# UX-D1 — Streak + Rank — Design

**Date:** 2026-09-30
**Status:** approved 2026-09-30; implemented on feat/ux-d1-streak-rank
**Program:** UX/GUI program, sub-project **D1** of D (progression & engagement loop). D was split into D1 streak + rank (this spec, the backbone), D2 badges, D3 weekly challenge, D4 mystery reward + app-icon badge + smart pushes.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row D; competitor scan: layered progression — daily streak → weekly challenge → rank → badges — outlasts pet/points novelty, which fades in 4–8 weeks; PointUp 15 ranks, Nimbi 10 levels).

## Goal

Kids and teens keep coming back after the points/pet novelty fades: every day of chores extends a visible streak, and all approved work grows a personal rank. Independent of the virtual pet (it keeps its own XP; a family with the pet module off still gets D1).

**Decisions (user, 2026-09-30):** XP = points + gig pesos · streak = all chores + weekly pass · 10 ranks, two name sets (kids / teens) · kids and teens only · computed from history (no stored counters) · shown in the kid header.

**Not in D1:** badges (D2), weekly challenge (D3), mystery reward / app-icon badge / smart pushes (D4), parent XP, best-streak record, leaderboards (Family Cup already exists), any change to pet XP.

## Rules

### XP

`xp(user) = max(0, Σ point_transactions.points WHERE user = kid AND type IN (task_completed, bonus, gig_approved))`
`        + max(0, Σ cash_transactions.amount_cents WHERE user = kid AND type = gig_earned) // 100`

Each part sums ALL rows of its type — positive and negative — then clamps at
0; the per-row floor was replaced by floor-after-sum (1 XP per $1 earned), so
a $5 gig split 350/100/50 cents across jars (`CashService.credit_split_rows`)
gives 5 XP, not `3 + 1 + 0 = 4`.

Excluded: `reward_redeemed`, `penalty`, `parent_adjustment`, `transfer` (points); `payout`, `adjustment`, `allowance` (chore points converted to cash — would double-count), `interest`, `match`, `jar_transfer` (cash). Spending never lowers XP; parent corrections (reopening a chore, re-splitting a shared gig) do, and XP never goes below 0. Family-scoped: every query filters by the kid's `family_id`.

### Ranks

| # | Cumulative XP | Kids ES / EN | Teens ES / EN |
|---|---|---|---|
| 1 | 0 | Novato / Rookie | Novato / Rookie |
| 2 | 100 | Ayudante / Helper | Colaborador / Contributor |
| 3 | 300 | Explorador / Explorer | Confiable / Reliable |
| 4 | 600 | Estrella / Star | Pro / Pro |
| 5 | 1 000 | Súper Ayudante / Super Helper | Experto / Expert |
| 6 | 1 600 | Campeón / Champion | Especialista / Specialist |
| 7 | 2 500 | Héroe / Hero | Capitán / Captain |
| 8 | 3 800 | Maestro / Master | Élite / Elite |
| 9 | 5 500 | Gran Maestro / Grand Master | Maestro / Master |
| 10 | 8 000 | Leyenda / Legend | Leyenda / Legend |

`rank_for_xp(xp)` = highest rank whose threshold ≤ xp. Thresholds live only in the backend; names live only in the frontend (`lib/progress.ts`). Kids = role CHILD, teens = role TEEN (name set follows the role, same as the kid-home skin).

### Streak

All dates are family-timezone dates (`families.timezone`). A kid's **due chores** for day D = their task assignments with `assigned_date = D`, template `is_bonus = false`, status ≠ `cancelled`.

A day's **state**:
- **none** — no due chores → skipped; never breaks or extends the streak.
- **done** — every due chore has `completed_at` on or before the end of D (family tz), is not graded `missed` (`completion_grade`) and not `rejected` (`approval_status`). It counts at submit time; approval is not required.
- **missed** — any due chore fails the above.
- **today** — D is today and not yet done (neither counts nor breaks).
- **future** — after today.

**Streak count**, walking back from yesterday (and including today if it is already `done`): each `done` day adds 1; `none` days are skipped; the **first `missed` day of each Monday–Sunday week is forgiven** (shown as a shield 🛡️, adds 0, doesn't break); any further `missed` day in the same week ends the walk. Lookback 365 days.

Legacy rows (added at planning): an assignment with `status = completed` but `completed_at` NULL (written before completion timestamps existed) counts as done on time.

Consequences: retroactive "mark done for kid" after the day doesn't restore that day (completed too late); a later `missed`/`rejected` grade can lower a streak already shown.

### Celebration

`users.last_seen_rank` (nullable int). When `rank > (last_seen_rank or 1)`, the kid home shows a one-time full-screen "¡Ahora eres {nombre}!" / "You're now {name}!" with the existing confetti (`lib/celebrate.ts`); dismissing it acks the rank. On launch, existing kids therefore see one celebration for the rank they already hold (if ≥ 2). Ack only moves up.

## Backend

- **`app/services/progress_service.py`** (`ProgressService`):
  - pure: `RANK_THRESHOLDS: tuple[int, ...]`, `rank_for_xp(xp) -> int`, `rank_floor(rank) -> int`, `next_rank_xp(rank) -> int | None`, `DayState` enum (`none`, `done`, `missed`, `shield`, `today`, `future`), `compute_streak(states: dict[date, DayState], today: date) -> StreakResult(days: int, week: list[tuple[date, DayState]], shield_used: bool)` — `week` is Monday–Sunday of today's week with forgiven misses reported as `shield`.
  - queries: `xp_for(db, family_id, user_id) -> int`, `day_states(db, family_id, user_id, tz, today) -> dict[date, DayState]` (one query over the last 365 days of the kid's non-bonus assignments), `progress_for(db, user) -> ProgressResponse`.
- **`app/api/routes/progress.py`**, registered under `/api/progress`:
  - `GET /api/progress/me` → `ProgressResponse { applies: bool, xp: int, rank: int, rank_floor_xp: int, next_rank_xp: int | null, streak_days: int, week: [{date, state}], shield_used: bool, celebrate_rank: int | null }`; parents get `{ applies: false }` (other fields null/0).
  - `POST /api/progress/me/ack-rank` `{ rank: int }` → sets `last_seen_rank = max(last_seen_rank or 1, min(rank, rank_for_xp(xp_for(kid))))` — it can only move up and never past the rank the kid actually holds; 204. Rejects rank < 1 or > 10 with 422; parents get 404.
- **Migration**: add `users.last_seen_rank INTEGER NULL`.
- **`KidSummary`** (`schemas/oversight.py`, built in `oversight_service`): + `streak_days: int`, `rank: int` (ints, never Decimal — strict mobile clients).
- All values are plain `int` in responses.

## Frontend

- **`lib/progress.ts`**: `RANK_NAMES` (kids/teens × es/en, the table above), `rankName(rank, skin, lang)`, `progressView(resp, skin, lang)` → `{ streakLabel, rankLabel, barPct, toNextLabel, ladder: [{rank, name, xp, state: 'done'|'current'|'next'}], week: [{label, state}] } | null` (null when `applies` is false or the response is missing). vitest.
- **`components/home/KidHeader.astro`**: under the name, a row of two pill buttons — `🔥 {n} días/days` and `{rankName} · {rank}/10` — and a thin XP bar (`barPct`). Pills use ink text on the header (sky tone for kids, white text on the teen dark skin); the visual guard applies. Both open the progress sheet. No response → no row.
- **`components/home/ProgressSheet.astro`**: bottom sheet (native `<dialog>`, same pattern as `AppDialog`): header rank name + XP to next; ladder of 10 rows (done ✓, current highlighted, locked); this week's 7-day strip (done / missed / 🛡️ / none / today / future); one-line rule ("Termina todas tus tareas del día. Tienes 1 día de perdón por semana." / "Finish all your chores each day. You get 1 free miss per week.").
- **Rank-up celebration** (kid home): if `celebrate_rank`, a full-screen overlay (z-[60], above BottomNav) with the rank name, `fireConfetti()`, and a "¡Genial!" / "Awesome!" button that POSTs the ack and closes. Shown once per rank.
- **`pages/dashboard.astro`** fetches `/api/progress/me` with the existing parallel `apiFetch` calls (never throws; null → no pills).
- **Parent hub `KidRow`**: `🔥 {streak} · {rankName}` under the kid's name.

## Testing

- Pure (pytest): rank boundaries (0, 99, 100, 7999, 8000, huge); streak — all done, a `none` day in between, today pending vs done, one miss forgiven (shield) + second miss in the same week resets, misses in two different weeks each forgiven, `missed` grade and `rejected` count as missed, completion after the day counts as missed, 365-day cap.
- Integration (pytest, test DB): XP sums include/exclude each ledger type; another family's rows never count; `day_states` from real assignments + family timezone; `GET /me` for child, teen, parent; ack monotonic + 422 bounds; `KidSummary` carries `streak_days`/`rank` as ints.
- Frontend (vitest): `rankName` both sets/langs, `progressView` null cases, bar %, ladder states, week labels; strict visual guard; `astro check`; build.
- After deploy: demo family (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`) as `sofia.demo` (child) and `diego.demo` (teen) at 390 px — pills, sheet, celebration once; parent hub row as `mariana.demo`.
