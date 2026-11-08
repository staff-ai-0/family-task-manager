# Early Bird — 11:00 chore deadline, up-for-grabs, early bonuses

Date: 2026-11-07 · Status: approved by "go" (user skipped questions; every
call below not quoted from the request is marked **[call]**)

## Why

Parent's words: the teens have "just enough energy to make it to get the
money" and "are not too collaborative". The request, verbatim rules:

1. Chores must be finished each day **before 11 am**. Two push reminders,
   **10:00** and **10:30**. At **11:00 anyone can take the chore, claim it
   in their name and get the bonus**.
2. A chore done **before any reminder** earns **extra points**; a full week
   of that earns **+5 %**; **3 weeks in a row** earns an extra **$500 pesos**.

Success = teens finish their chores in the morning without being chased, and
siblings have a reason to pick up each other's slack.

## Goals

- A per-family **deadline** (default 11:00, family-local) with two automatic
  reminders at deadline −60 and −30 min.
- At the deadline, a teen's still-open chores for that day become **up for
  grabs**: another kid/teen can take one; it becomes theirs and they earn
  it. The owner loses it.
- Three early-bird tiers: per-chore points, per-week +5 % on the chore
  paycheck, every 3rd consecutive early week a $500 MXN cash bonus.

## Non-goals

- No change for families that do not switch it on (default **off**).
- No LLM call anywhere (no `ai_features` gating needed).
- No change to flat-allowance payday, gigs board, collaboration gigs.
- No "give it back" after taking a chore.
- Chores from previous days are not grabbable (only the same day).

## Anti-goals (would be failure even if it "works")

- A kid could end up with a perfect streak/early day/paycheck **without
  doing the chore** (e.g. the taken chore silently vanishing from their day).
- The same chore paid twice (owner completes after it was taken; two
  siblings take it at once).
- Reminders that lie (a "1 hour left" read at 4 pm; a reminder for a chore
  already done).
- Money moved twice by a restart or a duplicate cron tick.

## Definitions (all times family-local, `families.timezone`)

- **Deadline D** = `families.early_bird_deadline` (default 11:00).
  **R1** = D − 60 min, **R2** = D − 30 min. **Early cutoff** = R1 ("before
  any reminder"). Deadline validation: 07:00–22:00, minutes multiple of 5
  **[call]**.
- **Active day**: weekday in `families.early_bird_days` (NULL = all 7)
  **[call — school days vary; parent picks]** and the day's R1 is after
  `early_bird_enabled_at`.
- **Covered chore**: a `task_assignments` row with
  - template `is_bonus = false` and `early_bird_exempt = false` **[call —
    evening chores like "dinner dishes" can't be done by 11; parent ticks
    them exempt on the template]**,
  - `assigned_to` a member with role **TEEN** **[call — the request is
    about teens; kids can still *take* chores]**,
  - `assigned_date` an active day, `status != cancelled`,
  - `taken_from_id IS NULL` (a chore someone took has no deadline for them).
- **Early chore**: covered, `status = completed`, `completed_at < R1` of its
  `assigned_date`, not rejected, `completion_grade` not `missed` and not
  `partial` **[call — money tiers reward done *right* and early; a partial
  grade breaks the early day]**.
- **Early day** (per teen): ≥ 1 covered chore that day and all are early.
  A day with a covered chore awaiting parent review is *pending*. A day with
  no covered chores is *neutral*.
- **Early week** (Mon–Sun): the week started after enablement
  (`early_bird_enabled_at` < Monday's R1) **[call — the week you switch it on
  doesn't count for the weekly tiers; daily points work at once]**, ≥ 1
  covered day, every covered day early. Any covered day missed ⇒ *missed*
  week. No covered day ⇒ *neutral* week (does not break or extend a run).

## Behaviour

### 1. Reminders (sweep every 5 min, leader-only)

New cron job `early_bird_sweep` (`minute="*/5"`). For each family with
`early_bird_enabled`, not soft-deleted, today an active day:

| Window | Who | Copy (ES/EN keys in `_COPY`) | Send record |
|---|---|---|---|
| [R1, R2) | teens with ≥ 1 open covered chore today | "⏰ 1 hora: termina tus N tareas antes de las 11:00" | no `deadline_soon` row since R1 |
| [R2, D) | same | "⚠️ 30 min: …o quedan libres para tus hermanos" | no `deadline_soon` row since R2 |
| [D, D+60 min) | owners of open covered chores today | "⏰ Se acabó el tiempo — N tareas quedaron libres" | no `up_for_grabs` row since D |
| [D, D+60 min) | other active kids/teens who could take ≥ 1 | "🙌 N tareas libres — tómalas y gana sus puntos" | same |

- Only the latest applicable reminder is sent (a sweep that first runs at
  10:40 sends R2, not R1).
- New `NotificationType`s `deadline_soon`, `up_for_grabs`, `chore_taken`,
  `early_bird_payout`. `deadline_soon` and `up_for_grabs` join
  `SUPERSEDING_TYPES`. Reminder rows expire at D; up-for-grabs rows at local
  midnight. Rows are created for every eligible member (push is sent only
  if subscribed — `create_localized` already handles that).
- "Open" = `pending` or `overdue`. A teen who finishes everything gets no
  further reminder (re-checked every tick).
- One family failing must not stop the others (ping_service pattern).

### 2. Up for grabs + take

- **Grabbable** = covered chore, `assigned_date = today`, now ≥ D, status
  open. Derived on read — the sweep mutates nothing.
- Until someone takes it, the owner can still complete it (late: normal
  points, no early bonus).
- `POST /api/early-bird/grabs/{assignment_id}/take` (CHILD or TEEN):
  - family enabled; same family (404 otherwise); grabbable; caller ≠ owner;
    caller is a participating member; caller's role allowed by
    `template.allowed_roles` (NULL = any); caller has no open mandatory
    chores today/overdue (`has_open_mandatory_through`) — "finish yours
    first" **[call — keeps grabbing a reward for doing your own part]**.
  - Row-locks the owner's row. Owner row → `status = taken`,
    `taken_by = caller`, `taken_at = now`. New row for the caller: same
    template/family/`assigned_date`/`week_of`, `status = pending`,
    `taken_from_id = owner row id`.
  - Second taker (race) gets **409 `already_taken`**.
  - Owner gets a `chore_taken` notification ("🙋 {taker} tomó tu tarea
    '{title}'").
- The taker completes it through the ordinary complete endpoint: ordinary
  points (`effective_points`), proof/review rules unchanged. "Get the bonus"
  = **the chore's own points, and in `points_rate` mode its paycheck value**
  **[call — no extra multiplier on top]**. Taker's row counts in their
  streak/paycheck like any chore; it is excluded from their early-day
  evaluation (it can never be early).

### 3. New status `taken`

`AssignmentStatus.TAKEN = "taken"` (PG enum `assignmentstatus` gains
`'taken'`). Why not reuse: `cancelled` is filtered out of streak, paycheck,
badges and quests (the miss would vanish — anti-goal 1), and
`completed`+rejected is counted as *done* by kiosk/oversight/analytics.
`taken` is a non-open, non-completed, non-cancelled terminal state, so every
existing `status != cancelled` / `status == completed` consumer already
treats it as "assigned, not done". Explicit touches:

- `BankService._chore_units` / `_chore_week_tasks`: taken ⇒ `lost_units`
  full; bucket `"taken"`.
- `can_complete` already excludes it (owner can't complete after a take).
- Shuffle only deletes `pending` rows — taken rows survive a re-shuffle.
- Frontend status labels: "Tomada por {name}" / "Taken by {name}".

### 4. Early bonus points (tier 1)

- `families.early_bird_bonus_pct` (default **20**, 0–100, 0 = off)
  **[call — "extra points" unquantified; 20 % of the chore]**.
- Award = `grade_credit_points(round_half_up(effective_points × pct / 100),
  credit_pct)`, min 1 when pct > 0 — as a `bonus` point transaction linked
  to the assignment; stored on `task_assignments.early_bonus_points`
  (idempotency marker, guarded write).
- When: non-proof chore — in `complete_assignment` if covered and
  `completed_at < R1`. Proof chore — at approval (`approve_gig` mandatory
  branch) if completed before R1 and grade `full` (partial ⇒ no bonus,
  consistent with the early-chore rule). Rejected ⇒ none.

### 5. Weekly +5 % (tier 2)

- `families.early_bird_week_pct` (default **5**, 0–50).
- Applies to the chore paycheck (`chore_proportional`, `chore_gated`,
  `points_rate`) of an **early week**: `bonus = base × pct // 100`, added to
  the computed amount in ONE place used by both the projection
  (`_paycheck_projection`) and `release_chore_paycheck`, so preview,
  outstanding weeks, release and the payout-receipt confirm
  (`adjustment = receipt − computed base`) all agree.
- Only for a finished, decided week (current week / pending-review week ⇒
  no bonus yet, shown as "pending"). `flat` allowance gets no 5 %
  **[call — not chore-based]**.
- Exposed as `early_bird_bonus_cents` on preview / outstanding / history so
  the teen meter and parent payouts can show "incl. +5 % madrugador".

### 6. 3-week $500 (tier 3)

- `families.early_bird_streak_cents` (default **50 000** = $500 MXN,
  0–1 000 000, 0 = off). Run length fixed at 3.
- New table `early_bird_weeks` — one settled row per (teen, week):
  `id, family_id FK CASCADE, user_id FK CASCADE, week_of DATE,
  result ('early'|'missed'|'neutral'), run_weeks INT, bonus_cents INT
  default 0, paid_at TIMESTAMPTZ NULL, created_at`, `UNIQUE(user_id,
  week_of)`, CHECK on result. Joins the family-export registry.
- Settlement (same sweep, after the week ends): weeks settle oldest-first,
  up to 3 weeks back; a week with a covered chore pending parent review
  waits — up to 7 days after the week ends, then a pending chore completed
  before R1 counts as early **[call — kids don't lose for a slow parent]**.
  `run_weeks`: early ⇒ prev + 1, missed ⇒ 0, neutral ⇒ prev (prev = row for
  week − 7 d, missing ⇒ 0).
- `result = early` and `run_weeks % 3 == 0` ⇒ pay `streak_cents` once
  (guarded `UPDATE … WHERE paid_at IS NULL`) as a new
  `CashTransactionType.BONUS` credit (jar split like other income), notify
  the teen and the parents (`early_bird_payout`). Weeks 3, 6, 9… pay.
- Paid money is never clawed back by later grading.

### 7. Settings

- Family columns: `early_bird_enabled BOOL NOT NULL DEFAULT false`,
  `early_bird_enabled_at TIMESTAMPTZ NULL` (stamped on every off→on),
  `early_bird_deadline TIME NOT NULL DEFAULT '11:00'`,
  `early_bird_days JSONB NULL`, `early_bird_bonus_pct`,
  `early_bird_week_pct`, `early_bird_streak_cents` (above).
- Template column: `early_bird_exempt BOOL NOT NULL DEFAULT false`.
- Assignment columns: `taken_by UUID FK users SET NULL`,
  `taken_at TIMESTAMPTZ`, `taken_from_id UUID FK task_assignments SET NULL`,
  `early_bonus_points INT NULL`.
- Edited through the existing `PATCH` family endpoint (`FamilyUpdate`) and
  template create/update schemas. Parent UI: an "Madrugador / Early bird"
  section in `/parent/settings/family` (toggle, deadline, day chips, three
  amounts) + an "Evening chore — no 11:00 deadline" checkbox on the
  template form.

### 8. Kid/teen surfaces

- `GET /api/early-bird/me` (kid/teen): settings snapshot, today's state
  (`early` / `on_track` (before R1, open) / `late` / `none`), cutoff and
  deadline instants, the week's day states, `run_weeks` and next payout
  week, this week's 5 % status, and the grabbable list (title, points,
  owner name) with `can_take` + reason.
- `EarlyBirdCard.astro` on the teen home: countdown to the cutoff (then to
  the deadline), Mon–Sun dots, "Racha: 1/3 semanas → $500", "+5 % si
  terminas temprano toda la semana".
- `UpForGrabs` section on kid + teen home after D: list + "Tomar" button →
  POST → the chore lands in their deck.
- Copy only in `frontend/src/lib/earlyBird.ts`; Astro proxy route files
  under `frontend/src/pages/api/early-bird/`.
- Parent: `GET /api/early-bird/family` — per-teen today/week/run for the
  settings section.

### 9. Docs

- `docs/USER_GUIDE_{EN,ES}.md` section; CLAUDE.md domain row.

## Constraints

- Multi-tenant: every query filters `family_id`; take endpoint 404s across
  families.
- Alembic only; single head (`payout_receipts` → new). Downgrade must work
  (CI round-trips): enum values removed by recreating the types after
  mapping `taken` → `cancelled` and `BONUS` rows → `ADJUSTMENT`.
- `cash_transactions.type` is a name-valued PG enum (`SQLEnum` without
  `values_callable`) — the new member is added by name.
- Never native dialogs; section-colored headers; visual/contrast guards.
- Integer money math only.

## Left to the builder

- Exact copy wording, card layout, icons (within the visual system).
- Module layout of the service (`early_bird_service.py` expected: pure rules
  first, then queries — ping_service style).
- Whether the 5 % helper lives in `bank_service` or `early_bird_service`
  (one place, both callers).
