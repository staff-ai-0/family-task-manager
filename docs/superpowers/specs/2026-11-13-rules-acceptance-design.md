# Rules announcement + acceptance record (chore rules project 2 of 3)

Status: IMPLEMENTED on branch feat/rules-acceptance (pending merge)

## Intent
Every family member is told the chore rules (cutoff, grab window, weekly ladder, early deadline, alarms, streak prize) and each one records "I understand and accept these rules; no future claims about results computed with them". The user wants **a record that they accepted** — nothing more (no hard lock-out, no dispute workflow).

## Non-goals / anti-goals
- No blocking of core flows (chores, rewards) for someone who hasn't accepted: the sheet reappears on the next visit; the record is the goal. A kid must never be locked out of the app by an unticked box.
- Not a legal waiver (a minor can't bind themselves): copy and docs frame it as a family agreement. No parent proxy: each person accepts for themself.
- Project 3 (show-and-tell / AI baseline photos) is separate.

## Design (my calls, approved as a whole)
- **Record**: new table `rules_acceptances(id, family_id→families CASCADE, user_id→users CASCADE, rules_version int, snapshot JSONB, accepted_at timestamptz)`, `UNIQUE(user_id, rules_version)`; history kept (a new version adds a row). `snapshot` = the exact values shown (deadline, cutoff, grab end, alarms, streak cents, per-chore bonus %, ladder thresholds) so the record proves WHAT was accepted. Must join the family-export registry (`EXPORTED_FAMILY_TABLES` in `family_export_service.py`).
- **Who/when**: all active, approved members (PARENT, TEEN, CHILD) of a family with Early Bird enabled. `required` = EB on AND no row for `(user, families.rules_version)`. A `rules_version` bump (existing mechanism) re-requires everyone.
- **API** (`/api/rules`, family-scoped, any authenticated member unless noted): `GET /status` → `{required, version, accepted_at|null, rules:{…snapshot…}}`; `POST /accept {version}` → 409 `stale_version` if it isn't the current version, idempotent if already accepted; `GET /acceptances` (PARENT) → per member `{user_id,name,role,accepted_at|null}` for the current version; `POST /announce` (PARENT, max once per hour per family) → creates a `RULES_UPDATE` notification (+push) for every active member and returns the count.
- **Announcement**: notification type `RULES_UPDATE` (ES/EN copy, link `/dashboard?rules=1`). Sent by the parent's Announce button AND automatically when the settings save bumps `rules_version` / enables Early Bird (best-effort, never fails the save).
- **UI**: a bottom sheet `RulesSheet` mounted once in `Layout.astro` (z-[60], backdrop z-[55], safe-area padding per repo rule): shows the rules from `/status` with the family's own values, a checkbox ("Entiendo las reglas y las acepto; no haré reclamos futuros sobre resultados calculados con ellas." / EN) that enables the Accept button, and a "Más tarde" that hides it for the session. Not shown during the welcome tour, on kiosk pages, or when `required` is false. Parent hub `RulesStatusCard`: "N of M accepted", names of those pending, an Announce button. Copy only in `frontend/src/lib/rulesNotice.ts` (ES+EN).

## Constraints
Family-scoped everywhere; integer cents; no native dialogs; `hidden` attribute not class on kit buttons; browser reaches the API through an Astro proxy route file `pages/api/rules/[...path].ts` (`createApiProxy({name:"rules"})`); vitest guards (visual-consistency, contrast, no-native-dialogs) stay green; Alembic single head (current head `marked_done_by_parent`).

## Left to the builder
Where the ladder percentages/early bonus % live as constants (expose them from `early_bird_rules.py` and reuse in `week_ladder` rather than copying literals, if cheap); how the Layout detects "welcome tour running" (reuse the existing suppression check used by ModuleTour).

## As built — deviations
- `accept` uses INSERT … ON CONFLICT DO NOTHING (constraint `uq_rules_acceptances_family_user_version`) and re-reads the row, so a double tap never errors or duplicates. If the re-read finds nothing the route answers 409 `accept_not_recorded`, never a 500.
- **R3 — the key includes the family**: `UNIQUE(family_id, user_id, rules_version)` (the Record bullet above said `UNIQUE(user_id, rules_version)`). An invitation can move an existing account to another family; with the old key, accepting v1 there hit the old family's row, inserted nothing and 500'd. The migration was edited in place (the table was never released).
- The parent acceptances list filters to active, approved members, and is EMPTY while Early Bird is off, so the parent card (hidden on an empty list) never offers an Announce that can only fail.
- `stale_version`, `early_bird_off`, `announce_too_soon` and `accept_not_recorded` carry a top-level `code` on the error response.
- The family export gained `progress/rules_acceptances.json`.
- The settings hook never calls announce while Early Bird is off: only a `rules_version` bump while on, or switching Early Bird on, announces (after the commit; a failure — including a failing rollback in the cleanup — is logged and never fails the save). A save that does both sends ONE notice per pending member.
- **R1 — the per-chore bonus % bumps `rules_version`**: the sheet shows and snapshots `early_bird_bonus_pct`, so it joined the bump list (cutoff, grab end, alarms, deadline, streak amount, per-chore bonus %).
- **R2 — announce notifies only members still pending** (amends "for every active member" in the API bullet): active, approved members with no acceptance for the current version in this family. `sent` is how many were notified; 0 is a valid answer ("Everyone has already accepted the rules."), writes nothing and starts no hourly cap. A version bump leaves everyone pending, so it still reaches everyone. The card button reads "Send rules to those pending".
- **R4 — teens-only labels**: the per-chore bonus and streak prize lines say "(teens)" / "(adolescentes)", because the backend pays them to teens only; each line is omitted when its value is 0.
- `/dashboard?rules=1` keeps `rules=1` when it redirects a parent to `/parent` (`parentHomeUrl`), and the sheet removes `rules` from the URL once read (`stripRulesParam`), so a later reload honours "Later". `/admin` is a skip path.
- `rules_update` is in `SUPERSEDING_TYPES` in `notification_service.py`.
- The sheet's welcome-tour suppression relies on `window.__ftmTourStarted` plus a 600 ms delay.
- Known limits: no focus trap in the sheet; two parents racing Announce can double-send; an auto-announce (forced) uses up the manual hourly allowance.
