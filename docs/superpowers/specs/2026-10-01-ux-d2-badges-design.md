# UX-D2 — Badges — Design

**Date:** 2026-10-01
**Status:** design approved in conversation 2026-10-01; awaiting written-spec review
**Program:** UX/GUI program, sub-project **D2** of D (progression & engagement loop). D1 streak + rank shipped (PRs #287, #289). D3 = weekly challenge, D4 = mystery reward + app-icon badge + smart pushes.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row D; competitor scan: layered progression — daily streak → weekly challenge → rank → badges — outlasts pet/points novelty; PointUp 90+ badges, Nimbi badges).
**Builds on:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`.

## Goal

Rank is one long ladder. Badges add many small, varied wins beside it, so a kid who is not grinding rank still has something close to chase: a kid or teen can see what they have earned, what is next and how close it is, and gets a moment when a badge unlocks. Independent of the virtual pet.

**Decisions (user, 2026-10-01):**
- Small tiered catalog: 8 families × 3 tiers = 24 badges, each with visible progress.
- Families: Chores, Streak, Perfect week, Extra mile, Gigs, Saver, Rewards, Family Cup.
- Shelf split by job: "Next badges" strip in the ProgressSheet (home) + full shelf on the profile page.
- One batched celebration per visit, launch-day history included; gated like D1; rank-up goes first.
- Badges are permanent once earned: counts computed from history, earned tiers stored.
- Parents: a badge count on each kid's hub row. No notifications, no parent shelf.

**Not in D2:** secret or one-off badges, parent badges, badge notifications or pushes (D4 owns pushes), a parent view of a kid's shelf, custom family badges, any reward (points or cash) for a badge, live update of the strip without a page load.

## Rules

### Who

Kids and teens only (roles CHILD, TEEN — D1's `KID_ROLES`). One name set for both.

### Catalog

Thresholds live only in the backend; names and emoji live only in the frontend (`lib/badges.ts`), the same split as D1's ranks.

| Key | Emoji | Name ES / EN | Bronze / Silver / Gold | Count |
|---|---|---|---|---|
| `chores` | 🧹 | Manos a la obra / Hard Worker | 10 / 50 / 200 | non-bonus assignments that are done (see "done" below) |
| `streak` | 🔥 | Racha imparable / Unstoppable | 7 / 30 / 100 | best streak reached in D1's walk (the peak, not the current value) |
| `perfect_week` | 📅 | Semana perfecta / Perfect Week | 1 / 4 / 12 | perfect weeks (see below) |
| `extra_mile` | 🚀 | Milla extra / Extra Mile | 1 / 10 / 50 | bonus assignments (`is_bonus = true`) that are done |
| `gigs` | 💼 | Espíritu emprendedor / Go-Getter | 1 / 10 / 50 | `gig_claims` with `claimed_by = kid`, `status = approved` |
| `saver` | 🐷 | Buen ahorro / Smart Saver | 1 / 3 / 10 | `kid_savings_goals` with `user_id = kid`, `reached_at IS NOT NULL` (any status) |
| `rewards` | 🎁 | Bien merecido / Well Earned | 1 / 5 / 20 | `point_transactions` of type `reward_redeemed` with `reward_id IS NOT NULL` and `points < 0` |
| `cup` | 🏆 | Copa familiar / Cup Champion | 1 / 3 / 10 | `family_cup_seasons` with `winner_user_id = kid` |

Tier names: Bronce / Plata / Oro — Bronze / Silver / Gold. Tiers are numbered 1–3; tier 0 means none earned.

**Done** (chores, extra mile) reuses D1's rule minus the on-time part: `status = completed`, `completion_grade` is not `missed`, `approval_status` is not `rejected`, status is not `cancelled`. It counts at submit time; approval is not required. All-time, no lookback.

**Rewards** deliberately requires `reward_id`: pet-shop purchases also write `reward_redeemed` rows, without a `reward_id`, and must not count. A parent-gated redemption writes its ledger row only when approved (`RewardService` deducts at approval; a rejection writes nothing), so there are no reversal rows to exclude. Known limit: if a reward is deleted, its past redemption rows lose their `reward_id` (`ON DELETE SET NULL`) and stop counting toward progress; tiers already earned are unaffected.

**Best streak** = the highest value D1's running streak counter reaches anywhere in its 365-day forward walk.

**Perfect week** = a Monday–Sunday week (family timezone) that
- ended before the current week (the current week never counts),
- lies fully inside the 365-day lookback (its Monday is on or after the walk's start),
- has at least one `done` day, and
- has no `missed` and no `shield` day (using a forgiven miss disqualifies the week).

All gold tiers (100-day streak, 12 perfect weeks) fit inside the 365-day window.

### Earning and permanence

A tier is **earned** the first time the kid's count for that family is ≥ the tier's threshold when their badges are read. Earned tiers are stored and never removed: a later parent correction (reopened chore, re-grade, re-split gig) or the streak window moving on lowers the displayed count but not the earned tier. Tiers stack — a kid with 60 chores holds bronze and silver.

The shelf shows, per family, the highest earned tier and progress toward the next (`60/200`); a gold family shows "Max".

`earned_at` is when the app recorded the tier, not when the underlying event happened. Launch-day tiers therefore all carry the kid's first post-launch visit date.

### Module gating

Families `gigs` and `saver` belong to the `gigs` module (gig board + Family Bank). When a family has that module off (`effective_modules(families.enabled_modules)`), those two badge families are **not evaluated and not returned** — absent from the shelf, the strip, the celebration and the hub count. Stored rows are kept; they reappear when the module is switched back on.

### Celebration

Every earned tier starts unseen. On the kid home (dashboard), if the kid has unseen tiers in visible families, one modal shows them all:

- One tile per family, at the highest unseen tier of that family (unseen bronze + silver of `chores` is one silver tile).
- Headline: one tile → "¡Nueva insignia!" / "New badge!"; several → "¡Ganaste {n} insignias!" / "You earned {n} badges!". Up to 6 tiles, then "+{n} más" / "+{n} more".
- Confetti; a "¡Genial!" / "Awesome!" button.
- Closing it acks **every** unseen tier id it was rendered with (including the lower tiers folded into a tile).

It opens only when
1. the welcome tour is complete (`completed_welcome_tour !== false`, D1's rule — driver.js plus a modal deadlocks touch input), **and**
2. no rank-up celebration is rendered on this load.

Otherwise the tiers stay unseen and the modal shows on a later visit. There is never more than one celebration modal per page load. Launch day uses this same path: a kid with history sees one modal for everything already earned.

## Backend

### Storage

New table `user_badges` (model `app/models/user_badge.py`, one Alembic migration after `user_last_seen_rank`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `family_id` | UUID, FK `families.id` ON DELETE CASCADE, NOT NULL, indexed | tenancy |
| `user_id` | UUID, FK `users.id` ON DELETE CASCADE, NOT NULL, indexed | |
| `badge` | String(32), NOT NULL | catalog key |
| `tier` | Integer, NOT NULL, CHECK 1–3 | |
| `earned_at` | timestamptz, NOT NULL | |
| `seen_at` | timestamptz, NULL | NULL = not celebrated yet |

`UNIQUE(user_id, badge, tier)`. Nothing else is stored; counts are derived on every read.

### `app/services/badge_service.py`

Same layout as `progress_service.py`: pure rules on top, family-scoped queries below.

- pure: `BADGES` (ordered catalog: key → thresholds tuple, required module or None), `tiers_for(count, thresholds) -> int` (0–3), `next_target(count_tier, thresholds) -> int | None`.
- `progress_service.compute_streak` gains two fields on `StreakResult`: `best: int` and `perfect_weeks: int`. Existing fields and behavior are unchanged.
- queries (all filter on `family_id` and `user_id`):
  - `counts_for(db, user, today, tz, visible) -> dict[str, int]` — chores + extra mile in one conditional-aggregate query; gigs, saver, rewards, cup one count each; streak + perfect week from `ProgressService.day_states` + `compute_streak`. Skips families not in `visible`. All values `int(...)`.
  - `sync(db, user) -> BadgesResponse` — computes counts, inserts every earned-but-missing tier with `INSERT … ON CONFLICT (user_id, badge, tier) DO NOTHING`, commits, and builds the response from the stored rows.
  - `ack(db, user, ids) -> None` — one `UPDATE user_badges SET seen_at = now() WHERE id IN (:ids) AND user_id = :me AND family_id = :mine AND seen_at IS NULL`. Ids that are not the caller's are ignored silently.
  - `earned_counts(db, family_id, visible) -> dict[UUID, int]` — one grouped query for the parent hub.

### API (in `app/api/routes/progress.py`, prefix `/api/progress`)

- `GET /api/progress/badges` → `BadgesResponse`:
  ```
  { applies: bool,
    badges: [ { badge: str, count: int, tier: int, next_target: int | null, earned_at: datetime | null } ],
    unseen: [ { id: UUID, badge: str, tier: int } ],
    earned_total: int }
  ```
  `badges` is in catalog order and holds visible families only; `earned_at` is that of the highest earned tier; `earned_total` counts earned tiers in visible families (max 24). Non-kids get `{ applies: false }` with empty lists (the same convention as `GET /api/progress/me`), so pages can fetch it without knowing the role first.

  This GET writes: it records newly earned tiers. The write is an idempotent insert-if-missing, and it keeps awarding in one place instead of hooks in every service that can move a count.
- `POST /api/progress/badges/ack` `{ ids: [UUID] }` (1–24 ids, else 422) → 204. Non-kids get 404.

### Parent hub

`KidSummary` (`schemas/oversight.py`) gains `badge_count: int`, filled by `earned_counts` (stored rows in visible families). It reflects what the kid has unlocked in the app, so it updates when that kid next opens the app; it does not evaluate badges on the parent's request.

## Frontend

- **`lib/badges.ts`** (pure, vitest): `BADGE_META` (emoji, ES/EN name per key), `TIER_NAMES`, and
  - `badgesView(resp, lang)` → `{ tiles: [{ key, emoji, name, tier, stars, progressLabel, barPct, maxed }], next: Tile[] (≤ 3), unseenTiles: [{ key, emoji, name, tier, tierName }], unseenIds: string[], earnedTotal } | null` (null when the response is missing or `applies` is false). Unknown keys from the API are dropped.
  - `next` = non-maxed families sorted by `count / next_target` descending, ties in catalog order, first 3.
  - `shouldCelebrateBadges(view, rankCelebrating, completedWelcomeTour)` — true only with unseen tiles, no rank-up modal on this load, and the tour complete.
- **Tier look:** the family emoji with three stars under it (★★☆ = silver), stars in `text-brand-sun-text`. A family at tier 0 shows the emoji greyed (`grayscale opacity-50`). No new color tokens.
- **`components/home/ProgressSheet.astro`:** new "Próximas insignias" / "Next badges" block — the `next` tiles, each with a progress bar and `37/50`, and a "Ver todas" / "See all" link to `/profile#badges`. When every family is maxed, one line: "¡Tienes todas las insignias!" / "You have every badge!". No badges response → no block. The sheet's panel becomes scrollable (`max-h-[90dvh] overflow-y-auto`) so the extra block never pushes the Close button off a small phone.
- **`pages/profile.astro`:** for kid roles, a "Insignias" / "Badges" section (`id="badges"`): a grid of the tiles (2 columns on a phone) with emoji, name, stars, progress bar and label (`60/200`, or "Máx" / "Max").
- **`components/home/BadgeCelebration.astro`:** follows `RankUpCelebration.astro` — native `<dialog>` with `m-auto`, `showModal()`, focus on the button, `cancel` handled, `fireConfetti(dialog)`, once-guard, then `POST /api/progress/badges/ack` with `unseenIds`. No native `alert`/`confirm`.
- **`pages/dashboard.astro`:** for kid roles, fetches `/api/progress/badges` in the existing parallel `apiFetch` calls and renders `BadgeCelebration` only when `shouldCelebrateBadges(...)`.
- **Parent hub:** `progressLine` (`lib/progress.ts`) appends ` · 🏅 {n}` when `badge_count > 0`.
- **Proxy:** `pages/api/progress/[...path].ts` already forwards the new routes.
- **Failure:** `apiFetch` returns null on error → no strip, no shelf section, no modal; the dashboard and D1 pills are unaffected.

## Testing

- **Pure (pytest):** `tiers_for` boundaries for every family (below, at, between, above gold); `next_target`; `compute_streak.best` (peak survives a later reset); `perfect_weeks` — shield week excluded, missed week excluded, current week excluded, week with nothing due excluded, week partly before the lookback start excluded; D1's existing streak tests still pass.
- **Service + API (pytest, test DB):** each family's count from real rows (pet purchase not counted as a reward; rejected/missed chore not counted; bonus vs non-bonus split); earned tier survives a count dropping below the threshold; two syncs award once (unique constraint); gigs module off hides `gigs` + `saver` and keeps stored rows; another family's rows never count; `ack` only marks the caller's own ids and ignores foreign ids; `applies: false` for parents on GET and 404 on ack; 422 on empty/oversized ack; `KidSummary.badge_count` is an int and respects module gating.
- **Migration:** covered by CI's upgrade → downgrade → upgrade round-trip.
- **Frontend (vitest):** `badgesView` null cases, stars and labels per tier, maxed tile, `next` ordering and tie-break, unseen folding (bronze + silver → one silver tile, both ids kept), unknown key dropped; `shouldCelebrateBadges` — tour pending, rank-up pending, nothing unseen; structure tests for `BadgeCelebration` mirroring `rank-up-celebration.test.ts`; `progressLine` with and without badges; strict visual guard, `astro check`, build.
- **After deploy (prod, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` only):** as `sofia.demo` (child) and `diego.demo` (teen) at 390 px — batched celebration once and not again, strip in the sheet, shelf on the profile; `mariana.demo` hub row shows the count.

## Docs

- `CLAUDE.md`: extend the Progress row in "Additional domains" with badges (catalog source, `user_badges`, write-on-GET, celebration gate).
- `docs/USER_GUIDE_{EN,ES}.md`: a short section on streak, rank and badges (D1 added none).
