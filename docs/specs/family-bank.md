# Family Bank — Design Spec (P1)

**Status**: DESIGN — approved for implementation (P1-W1 backend, P1-W2 UI)
**Date**: 2026-07-08
**Roadmap**: `docs/audit/2026-07-07/00-INDEX.md` → P1 "Family Bank: weekly payday job; Save/Share/Spend jars w/ % auto-split; parent-paid interest; parent match"
**Evidence**: `docs/audit/2026-07-07/02-competitor-intel.md` (cited inline as *intel*)
**Foundation**: `docs/superpowers/specs/2026-06-30-two-currency-economy-design.md` (two-currency economy)

---

## 1. Problem

Kids earn cash on the gig board (`cash_cents`, 1 pt = $1 MXN) and parents settle it with
`POST /api/cash/{user_id}/payout`. That is a working IOU ledger — but it teaches nothing.
There is no allowance ("domingo"), no payday ritual, no saving mechanic, no way for a
parent to incentivize saving. Every raved-about competitor in the category ships exactly
those four things on top of a ledger we already have.

The Family Bank is the P1 launch differentiator: **payday + Save/Share/Spend jars +
parent-paid interest + parent match**, all as pure ledger math on `cash_cents` /
`cash_transactions`. No banking rails, no cards, no regulation — the parent remains the
bank, the app is the authoritative ledger.

**Hard constraint (two-currency economy — review-fail if violated)**: the Family Bank
operates ONLY on the CASH ledger. Points remain a fully separate privileges currency.
Chores/bonus tasks never produce cash; jars/interest/match/allowance never touch
`User.points` or `point_transactions`.

---

## 2. Competitor evidence

All from `docs/audit/2026-07-07/02-competitor-intel.md`:

| Feature | Evidence (group / product) |
|---|---|
| Save/Share/Spend jars with % auto-split of every payout | BusyKid [HIGH] "the classic three-jars pedagogy, automated; consistently praised as the thing that actually teaches money habits"; Rooster Money [HIGH] Spend/Save/Give pots ("allowance auto-splits by percentage so saving/giving happens by default, not willpower"); iAllowance [HIGH] unlimited jars ("confirming jars are table stakes") |
| Weekly allowance independent of chores | iAllowance [HIGH] "set-and-forget weekly allowance credited automatically was its core praised loop… allowance-plus-chores is what these apps show parents expect"; Greenlight [HIGH] "set it once, pay on schedule" |
| Payday model (earnings accrue, paid like a paycheck on a set day) | BusyKid [HIGH] "parents love the real-job framing… kids learn income is periodic, not instant"; GoHenry gap-to-close: "kid-facing earnings-this-week / payday-countdown view" |
| Parent-paid interest on savings | Greenlight [HIGH] "the killer teaching tool… Greenlight's tier ladder (2–6%) is literally its main upsell axis"; FamZoo [HIGH] "rates absurdly high (e.g. 1%/week) so kids see the effect fast"; Rooster [HIGH] parent-funded 'boost' — and both Rooster & FamZoo *get complaints that the app doesn't automate it* |
| Parent match on kid savings | BusyKid [HIGH] "parents double-down on saving behavior like a 401(k) match"; GoHenry/Acorns [LOW→adapt] "the transferable idea is the MATCH mechanic: 'I match 50% of whatever my kid saves' — pure ledger math" |
| Parent-settled Share/charity jar | BusyKid [MEDIUM] "'Share' can be a parent-settled pledge (family picks the cause, parent executes, app tracks it)" — church/abuelos/local causes fit Mexico |
| Bundling all of the above as one "Family Bank" | chore-card-fintech INSIGHTS: "a bundled 'Family Bank' (payday + Save/Share/Spend jars + parent interest/match) is the highest-ROI build before launch"; allowance-trackers INSIGHTS: "the defensible middle for a Mexico launch is the FamZoo-style VIRTUAL FAMILY BANK… our gig cash_cents system is already 80% of it" |
| Premium gating: automation paid, ledger free | allowance-trackers INSIGHTS #4: "Free keeps chores+points+basic ledger unlimited and Plus (~MX$99/mo) gates jars, interest, allowance automation"; market-monetization: "freemium is table stakes; Greenlight's lack of a free tier is its most-cited weakness" |

Also relevant: the incumbents' weak flank is the *banking layer* (billing-after-cancel,
lost transfers, fraud disputes). Our parent-settled ledger sidesteps all of it
(chore-card-fintech INSIGHTS #1).

---

## 3. Design decisions

### D1 — Jars: materialized per-kid balances + `jar` attribution column on the ledger

Three fixed jars in v1: `spend`, `save`, `share` (ES: **Gastar / Ahorrar / Compartir**).

Schema choice (options considered):

- ~~Computed balances from a `jar` column alone~~ — rejected: every balance read scans the
  ledger; `balance_before/after` per jar can't be stamped; diverges from the existing
  materialized pattern (`User.cash_cents` + ledger rows).
- ~~Separate `kid_jar` table (one row per jar)~~ — rejected for v1: 3 fixed jars don't need
  normalization; per-mutation locking would span 1–3 rows instead of one.
- **Chosen**: one row per kid in a new `kid_bank_accounts` table carrying the three jar
  balances *and* the parent config (allowance, splits, interest, match), **plus** a
  `jar` attribution column on `cash_transactions`. Single-row `FOR UPDATE` mirrors the
  proven `_get_user_locked` pattern in `backend/app/services/cash_service.py:19`.

**Invariants** (enforced in service code, asserted in tests):

1. `spend_cents + save_cents + share_cents == users.cash_cents` at all times.
2. Every `cash_transactions` row stamps `balance_before/after` against the **total**
   `cash_cents` (unchanged semantics — existing rows stay valid).
3. Jar transfers are **paired rows** (−X from jar A, +X to jar B, both type
   `JAR_TRANSFER`) so `SUM(amount_cents)` still reconciles with the balance and each
   jar's history is auditable via the `jar` column.
4. Lock order is always: `users` row first (via `_get_user_locked`, which already uses
   `populate_existing=True`), then `kid_bank_accounts` row. Never the reverse (deadlock).

Legacy rows: `jar` defaults to `'spend'` — historically all cash was spendable, so the
backfill is a no-op `server_default`.

`kid_bank_accounts` rows are **lazily created with no-op defaults** (splits 100/0/0,
allowance 0, interest 0, match 0) the first time a kid's cash is touched or the parent
opens settings. A family that never configures the bank sees zero behavior change.

### D2 — % auto-split applied on every cash credit

`CashService.award_gig_cash` (called from `gig_claim_service.py:114,409`) becomes
split-aware: a positive credit is divided by the kid's `split_*_pct` into up to three
ledger rows (same `gig_claim_id`/`assignment_id`, same type, one per non-zero jar
share). Rounding: floor each non-spend share; the remainder goes to `spend`.
Allowance credits (D3) go through the same splitter.

Negative amounts debit jars in cascade order `spend → save → share` until covered —
never leaves a negative jar. The cascade is ONE shared `CashService` debit helper and
applies to **every** signed debit against the total, not just claw-backs: the
`GIG_EARNED` claw-back path AND negative `ADJUSTMENT` (`CashService.adjust`,
`cash_service.py:113-142`). Today `adjust` allows a debit up to the TOTAL balance
(floors at 0), which can exceed the spend jar alone — e.g. spend=$0, save=$200,
adjust −$100 **must** cascade into `save`; pinning ADJUSTMENT to jar='spend' would
either break invariant #1 or trip the `spend_cents >= 0` CHECK and turn a working
`POST /api/cash/{user_id}/adjust` call into a 500. The existing floor-at-zero-total
contract of that endpoint is preserved unchanged.

**Entitlement at credit time**: the splitter consults the family plan
(`get_family_plan_by_id`) before splitting — families not entitled to
`family_bank_automation` fall back to 100/0/0 regardless of stored config (§10
downgrade behavior). This matters because splits fire at gig-approval time
(`gig_claim_service.py:114,409`), a path the payday sweep never touches.

Default split is 100/0/0, so **free-tier families and unconfigured kids keep today's
exact behavior** (single row, jar='spend').

### D3 — Weekly allowance ("domingo"), independent of chores

Per-kid config: `allowance_cents` + `payday_weekday` (0=Mon..6=Sun; **default 6 —
Sunday, the literal "domingo"**). Credited by the payday sweep as a new
`ALLOWANCE` transaction type, then split per D2. v1 allowance is **unconditional**
(iAllowance/Rooster model); Greenlight-style "no chore = no pay" withholding is an
explicit open question for P2 (§12).

### D4 — Payday sweep (scheduler-leader job)

One new job in the existing APScheduler leader block (`backend/app/main.py:145-158`),
following the `send_morning_reminders` timezone pattern
(`task_assignment_service.py:1977` — inline `ZoneInfo(tz_name or "UTC")` with a
try/except UTC fallback): group families by `Family.timezone`, evaluate each
kid against **family-local** time.

Runs **hourly**; a kid is paid when: local weekday == `payday_weekday` AND local hour ≥ 8
AND `last_payday_at` < family-local midnight (idempotency guard — safe across restarts
and duplicate ticks, same rationale as the TASK_DUE guard). Hourly beats a single daily
UTC tick because non-CDMX timezones would otherwise miss their local weekday window.

Per-kid payday, in order (one DB transaction per kid, per-kid try/except so one failure
never blocks the family — same isolation as the morning-reminder loop):

1. **Match** — `match_pct` × (kid-initiated Save deposits since `last_payday_at`),
   capped at `match_cap_cents` → credit `save`, type `MATCH`.
2. **Interest** — `interest_rate_bps` × `save_cents` **after step 1's match, before
   this payday's allowance** → credit `save`, type `INTEREST`, floor rounding.
3. **Allowance** — credit `allowance_cents`, split per D2, type `ALLOWANCE`.
4. Stamp `last_payday_at = now()`; send ONE celebratory bilingual notification via
   `NotificationService.create_localized` (new `payday` copy key, §8).

Ordering rationale: allowance is new money and starts earning next week; the match
lands in `save` first (step 1) and **deliberately earns interest the same payday** —
step 2 computes interest on the post-match Save balance, exactly as the pseudocode in
§6 does — so a kid who saved sees the match compound immediately (saving is visibly
rewarded twice). Deterministic and explainable to a kid.

The sweep resolves the family plan via `get_family_plan_by_id` and **skips automation
for non-entitled families** (downgraded families stop accruing; balances remain).

### D5 — Parent match

Config: `match_pct` (0–200, e.g. 50 = 50%) + `match_cap_cents` (0 = uncapped) per kid.
Matched base = sum of `JAR_TRANSFER` credits into `save` where `created_by == kid`
(kid-initiated only — parent-forced transfers and auto-splits don't game the match)
with `created_at > last_payday_at`. On a kid's **first** payday `last_payday_at` is
NULL — the sweep's WHERE clause deliberately admits those kids, so the window must be
defined: **NULL means all-time**, i.e. every prior kid-initiated Save deposit counts.
That's safe (JAR_TRANSFER rows only exist after this feature ships, match only pays
once the parent configured it, and `match_cap_cents` bounds the payout either way)
and avoids silently paying $0 on the very payday the feature debuts. Applied at
payday (D4 step 1), not instantly —
teaches delayed gratification and makes the cap trivially enforceable.

### D6 — Kid actions

| Action | Rule |
|---|---|
| Spend → Save, Spend → Share | Kid self-serve, anytime (saving is always frictionless) |
| Save → Spend | Parent-approved by default (`save_withdrawal_requires_approval`, default `true`). Kid taps "ask to withdraw" → parent notification (deep link) → **parent executes** the transfer. Toggle off = kid self-serve. No new request table in v1 — the request is a localized notification, mirroring how gig review requests work today |
| Share → anything | Parent-only. Share is settled by the parent (hands cash to the church/abuelos/cause) via the existing payout flow with `jar='share'` |
| Request payout of Spend | Kid taps "request payout" → parent notification; parent uses the existing `POST /api/cash/{user_id}/payout` (extended with a `jar` param, default `'spend'`, validated against the jar balance) |

Parents can move money between any jars of any kid in their family, anytime.

### D7 — Config surface

New parent settings page `/parent/settings/family-bank` (§9). Per-kid: allowance amount
+ payday weekday, split percentages (must sum to 100), interest %/week, match % + cap,
Save-withdrawal-approval toggle. All automation fields are Plus-gated (§10).

### D8 — Relationship to the budget module (explicitly NOT coupled)

`BudgetAccount` could host kid envelopes someday (YNAB-benchmark intel: "no one gives
kids their own envelopes fed by chores/gigs"), and a kid's Save jar could later mirror
into an `offbudget` savings account for parent reporting. **v1 does neither** — no FK,
no service call, no import from `app.models.budget` anywhere in the bank code. The only
bridge ever contemplated is a read-only projection, designed post-launch (§12).

---

## 4. Schema — DDL sketch

ONE new table + one column + four enum values. (Alembic migration, §7.)

```sql
-- Per-kid Family Bank account: jar balances (materialized) + parent config.
-- INVARIANT: spend_cents + save_cents + share_cents == users.cash_cents.
CREATE TABLE kid_bank_accounts (
    id                  UUID PRIMARY KEY,
    family_id           UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,

    -- jar balances, centavos
    spend_cents         INTEGER NOT NULL DEFAULT 0,
    save_cents          INTEGER NOT NULL DEFAULT 0,
    share_cents         INTEGER NOT NULL DEFAULT 0,

    -- weekly allowance ("domingo")
    allowance_cents     INTEGER NOT NULL DEFAULT 0,          -- 0 = no allowance
    payday_weekday      SMALLINT NOT NULL DEFAULT 6,         -- 0=Mon .. 6=Sun

    -- % auto-split of every cash credit (gig payouts + allowance)
    split_spend_pct     SMALLINT NOT NULL DEFAULT 100,
    split_save_pct      SMALLINT NOT NULL DEFAULT 0,
    split_share_pct     SMALLINT NOT NULL DEFAULT 0,

    -- parent-paid weekly interest on the Save jar, basis points (100 = 1%/wk)
    interest_rate_bps   INTEGER NOT NULL DEFAULT 0,

    -- parent match on kid-initiated Save deposits, applied at payday
    match_pct           SMALLINT NOT NULL DEFAULT 0,         -- 50 = 50% match
    match_cap_cents     INTEGER NOT NULL DEFAULT 0,          -- 0 = uncapped

    save_withdrawal_requires_approval BOOLEAN NOT NULL DEFAULT TRUE,

    last_payday_at      TIMESTAMPTZ,                         -- idempotency + match window
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_kid_bank_split_sum
        CHECK (split_spend_pct + split_save_pct + split_share_pct = 100),
    CONSTRAINT ck_kid_bank_ranges CHECK (
        spend_cents >= 0 AND save_cents >= 0 AND share_cents >= 0
        AND allowance_cents >= 0
        AND payday_weekday BETWEEN 0 AND 6
        AND split_spend_pct BETWEEN 0 AND 100
        AND split_save_pct  BETWEEN 0 AND 100
        AND split_share_pct BETWEEN 0 AND 100
        AND interest_rate_bps BETWEEN 0 AND 10000             -- max 100%/week (FamZoo-style)
        AND match_pct BETWEEN 0 AND 200
        AND match_cap_cents >= 0
    )
);
CREATE INDEX ix_kid_bank_accounts_family_id ON kid_bank_accounts (family_id);

-- Jar attribution on the existing ledger. Plain string on purpose (matches the
-- users.approval_status precedent) — values 'spend' | 'save' | 'share'.
ALTER TABLE cash_transactions
    ADD COLUMN jar VARCHAR(8) NOT NULL DEFAULT 'spend';

-- New ledger types. ⚠️ cash_transaction.py declares SQLEnum WITHOUT
-- values_callable, so the PG enum stores the UPPERCASE MEMBER NAMES
-- (verified live: GIG_EARNED, PAYOUT, ADJUSTMENT). Add names, not values:
ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS 'ALLOWANCE';
ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS 'INTEREST';
ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS 'MATCH';
ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS 'JAR_TRANSFER';
```

Model changes:

- `backend/app/models/kid_bank.py` — new `KidBankAccount` model (import in
  `models/__init__.py` so `create_all` in tests picks it up).
- `backend/app/models/cash_transaction.py` — add `ALLOWANCE`, `INTEREST`, `MATCH`,
  `JAR_TRANSFER` to `CashTransactionType`; add `jar = Column(String(8), nullable=False, server_default="spend")`.
- **No change to `User`** — `cash_cents` remains the authoritative total.

Ledger semantics per type:

| Type | Sign | Jar | Notes |
|---|---|---|---|
| `GIG_EARNED` | + (− claw-back) | split per config | unchanged call sites |
| `ALLOWANCE` | + | split per config | payday sweep only |
| `INTEREST` | + | `save` | payday sweep only |
| `MATCH` | + | `save` | payday sweep only |
| `JAR_TRANSFER` | ± paired, net 0 | source/dest | always two rows in one txn |
| `PAYOUT` | − | param (default `spend`; `share` = settling the Share pledge) | existing type, jar-validated |
| `ADJUSTMENT` | ± | + → `spend` (v1); − → cascade `spend→save→share` | existing manual adjust; a negative adjustment uses the same jar cascade as claw-back (D2) so invariant #1 holds and `ck_kid_bank_ranges` can't trip |

---

## 5. API sketch

New router `backend/app/api/routes/bank.py` (`/api/bank`, registered in `main.py`),
new service `backend/app/services/bank_service.py`. `CashService` stays the low-level
ledger primitive (gains split logic + jar param); `BankService` owns jar config, jar
transfers, requests, and the payday sweep.

| Method & path | Role | Gating | Purpose |
|---|---|---|---|
| `GET /api/bank/me` | kid (TEEN/CHILD) | free | Own jars, split config, next payday date + countdown, pending-match preview ("$X saved since last payday → papá pondrá $Y"), interest rate |
| `GET /api/bank/family` | parent | free | All kids: jar balances + settings summary (kiosk/settings data source) |
| `PUT /api/bank/settings/{user_id}` | parent | `require_feature("family_bank_automation")` **only when the payload enables automation** (allowance>0, split≠100/0/0, interest>0, or match>0); resetting to defaults is always allowed | Upsert per-kid config; validates splits sum to 100 + CHECK ranges |
| `POST /api/bank/transfer` | kid self / parent any-kid | free | `{user_id, from_jar, to_jar, amount_cents}`. Kid: `spend→save/share` always; `save→spend` 403 `code="approval_required"` when the flag is on (UI then offers "ask"). Parent: any direction |
| `POST /api/bank/requests/save-withdrawal` | kid | free | `{amount_cents, reason?}` → localized notification to all parents (deep link to the kid's bank card). Stateless in v1 |
| `POST /api/bank/requests/payout` | kid | free | `{amount_cents?}` → localized notification to all parents. Stateless in v1 |
| `POST /api/cash/{user_id}/payout` | parent | free (existing) | **Extended**: optional `jar` field (default `"spend"`); validates against that jar's balance, debits jar + total |
| `GET /api/cash/history` | any (existing) | free | **Extended**: response schema gains `jar` per row |

All queries filter `family_id` from the JWT user (multi-tenant hard rule). Kid
endpoints operate strictly on `current_user`; parent endpoints verify the target kid's
`family_id == current_user.family_id`.

Jarvis/MCP: read-only bank tools (`get_kid_bank`, list balances) can ride the existing
family-scoped MCP CRUD pattern later — not in v1 scope.

---

## 6. Payday job — pseudocode

`BankService.run_payday_sweep(db)`, wired in the `main.py` leader block:

```python
# main.py (scheduler-leader block, after _morning_reminder_sweep)
async def _family_bank_payday_sweep():
    async with AsyncSessionLocal() as session:   # app.core.database.AsyncSessionLocal
        try:
            n = await BankService.run_payday_sweep(session)
            if n:
                logger.info("Family Bank payday sweep paid %d kid(s)", n)
        except Exception:
            logger.exception("Family Bank payday sweep failed")

scheduler.add_job(_family_bank_payday_sweep, "cron", minute=10, id="family_bank_payday")  # hourly
```

```python
async def run_payday_sweep(db) -> int:
    families = (await db.execute(select(Family.id, Family.timezone))).all()
    paid = 0
    for fid, tz_name in families:
        tz = safe_zoneinfo(tz_name)                      # fallback UTC, like morning sweep
        local_now = datetime.now(tz)
        if local_now.hour < 8:                           # pay after 08:00 local, not at midnight
            continue
        local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=tz)

        # Plus-gated automation: skip non-entitled families entirely.
        plan = await get_family_plan_by_id(db, fid)
        if not plan.limits.get("family_bank_automation", False):
            continue

        accounts = await db.scalars(
            select(KidBankAccount)
            .join(User, User.id == KidBankAccount.user_id)
            .where(KidBankAccount.family_id == fid,
                   KidBankAccount.payday_weekday == local_now.weekday(),
                   or_(KidBankAccount.last_payday_at.is_(None),
                       KidBankAccount.last_payday_at < local_midnight),   # idempotent per local day
                   User.is_active.is_(True),
                   User.approval_status == APPROVAL_APPROVED)
        )
        for acct in accounts:
            try:
                user = await _get_user_locked(db, acct.user_id)          # lock order: user, then acct
                acct = await _lock_account(db, acct.user_id)

                # 1) MATCH on kid-initiated Save deposits since last payday
                #    (since=None on the FIRST payday → all-time window, see §D5)
                base = await sum_kid_save_deposits(db, acct.user_id, since=acct.last_payday_at)
                match = min(base * acct.match_pct // 100,
                            acct.match_cap_cents or 10**12) if acct.match_pct else 0
                if match: credit_jar(db, user, acct, "save", match, CashTransactionType.MATCH)

                # 2) INTEREST on the post-match, pre-allowance Save balance (D4)
                interest = acct.save_cents * acct.interest_rate_bps // 10_000
                if interest: credit_jar(db, user, acct, "save", interest, CashTransactionType.INTEREST)

                # 3) ALLOWANCE, auto-split across jars (floor; remainder → spend)
                if acct.allowance_cents:
                    credit_split(db, user, acct, acct.allowance_cents, CashTransactionType.ALLOWANCE)

                acct.last_payday_at = datetime.now(timezone.utc)
                await db.commit()

                if match or interest or acct.allowance_cents:
                    await NotificationService.create_localized(
                        db, family_id=fid, user_id=acct.user_id, key="payday",
                        params={"total": fmt_mxn(match + interest + allowance),
                                "allowance": ..., "interest": ..., "match": ...},
                        link="/bank")
                    paid += 1
            except Exception:
                await db.rollback()
                logger.exception("payday failed for kid %s", acct.user_id)
    return paid
```

Notes:
- Per-kid commit + try/except: one bad row never blocks the family or the sweep
  (pattern proven in `send_morning_reminders`).
- Idempotency = `last_payday_at < family-local midnight`, not a "did I run today"
  flag — restart-safe, duplicate-tick-safe, DST-safe enough for v1.
- A kid with allowance 0 but interest/match configured still gets a payday event on
  their `payday_weekday`.
- `sum_kid_save_deposits`: `SELECT COALESCE(SUM(amount_cents),0) FROM cash_transactions
  WHERE user_id=:kid AND type='JAR_TRANSFER' AND jar='save' AND amount_cents>0
  AND created_by=:kid AND (CAST(:since AS timestamptz) IS NULL OR created_at > :since)`
  (kid-initiated only, §D5). `:since = last_payday_at`, which is **NULL before a kid's
  first payday** — the NULL branch matches all-time deposits so the first payday's
  match is not silently $0 (a bare `created_at > :since` would match zero rows on
  NULL, even though the sweep's WHERE deliberately admits `last_payday_at IS NULL`).

---

## 7. Migration plan — ONE migration

File: `backend/migrations/versions/2026_07_XX_family_bank.py`

- **`down_revision`: run `podman exec family_app_backend alembic heads` at
  implementation time and chain to the actual single head.** As of this spec (2026-07-08)
  it is `mxn_plan_currency_w6` — the sibling P1 workstreams already landed
  `task_mechanics_w4` → `mxn_plan_currency_w6` on top of `ai_processing_consent`. More
  siblings may land before implementation — chain, don't fork.
- Contents (all in one revision):
  1. `op.create_table("kid_bank_accounts", ...)` + family_id index + CHECK constraints.
  2. `op.add_column("cash_transactions", sa.Column("jar", sa.String(8), nullable=False, server_default="spend"))` — instant on PG15 (non-volatile default), no backfill needed.
  3. Four `op.execute("ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS '<NAME>'")`
     — **uppercase member names** (`ALLOWANCE`, `INTEREST`, `MATCH`, `JAR_TRANSFER`),
     because the column was created without `values_callable` (verified against the live
     DB: labels are `GIG_EARNED`, `PAYOUT`, `ADJUSTMENT`). PG15 allows ADD VALUE inside
     the migration transaction as long as the same transaction doesn't *use* the new
     values — this migration doesn't.
  4. Downgrade: drop table + column; **leave the enum values in place** (PG cannot drop
     enum values; document in the migration docstring).
- After merge: `podman exec family_app_backend alembic upgrade head` locally;
  `deploy-onprem.sh` runs it against prod as part of the normal deploy.
- Test DB: `conftest.py` uses `create_all`, so importing `KidBankAccount` in
  `models/__init__.py` is what makes tests see the table — don't forget it.

---

## 8. Notifications (bilingual, existing i18n pattern)

Add to `NotificationType` (`backend/app/models/notification.py`): `PAYDAY = "payday"`,
`BANK_REQUEST = "bank_request"`.

Add `_COPY` keys in `notification_service.py` (per-language dicts, resolved against the
recipient's `preferred_lang`, Mexico-first default `es` — existing `create_localized`
machinery, zero new i18n code):

| Key | Type | ES (sketch) | EN (sketch) |
|---|---|---|---|
| `payday` | PAYDAY | 🎉 "¡Día de pago! +{total}" / "Tu domingo: {allowance} · interés: {interest} · aportación de papás: {match}" | 🎉 "Payday! +{total}" / "Allowance: {allowance} · interest: {interest} · parent match: {match}" |
| `payday_interest_only` | PAYDAY | 💰 "¡Tu ahorro creció!" / "Ganaste {interest} de interés esta semana." | 💰 "Your savings grew!" / "You earned {interest} in interest this week." |
| `bank_save_withdrawal_request` | BANK_REQUEST (→ parents) | 🏦 "{child} quiere retirar {amount} de su ahorro" | 🏦 "{child} wants to withdraw {amount} from savings" |
| `bank_payout_request` | BANK_REQUEST (→ parents) | 💵 "{child} pide su pago de {amount}" | 💵 "{child} is asking to be paid {amount}" |

`create_localized` already fans out to push (`push_service`) — payday lands as a push
notification for free.

---

## 9. Config / UI notes (UI workstream)

Two surfaces, both bilingual ES/EN (lang cookie default `es`), following each page's
existing style. **Interactive buttons must follow the `astro:page-load` one-shot
dispatch wiring used by existing pages** (project memory: hoisted-module handlers race
otherwise and buttons go silently dead) — copy the handler pattern from a recent page,
e.g. the gigs or settings pages.

### Parent: `/parent/settings/family-bank` (new Astro page)

- Listed from `/parent/settings/index.astro` alongside family/subscription entries.
- One card per kid (TEEN/CHILD members): 
  - "Domingo semanal" — MXN amount input + weekday select (default Domingo).
  - Split editor — three linked percent inputs (Gastar/Ahorrar/Compartir) with a
    sum-to-100 validator and a visual bar.
  - "Interés semanal" — percent input (0–100%/week) with a plain-language explainer
    ("tú pagas este interés — el banco eres tú").
  - "Aportación de papás (match)" — percent + cap (MXN) inputs.
  - Toggle: "Retiros de Ahorro requieren aprobación".
- Non-Plus families see the page with automation controls locked behind the existing
  upsell affordance (same pattern as budget reports upsell) — jar balances remain
  visible/manageable.
- Also on this page: per-kid "Liquidar Compartir" (settle Share) and free-form jar
  transfer actions (parent side of D6).

### Kid: "Mi Banco" — new page `/bank` (kid-facing, kiosk-friendly)

- Three big jar cards (Gastar/Ahorrar/Compartir) with balances; total = header.
- Payday countdown ("Tu domingo cae el domingo — faltan 3 días") — the GoHenry
  earnings-this-week/countdown gap called out in intel.
- Match preview: "Has ahorrado $40 desde el último pago → tus papás pondrán $20 💪".
- Actions: "Mover a Ahorro/Compartir" (self-serve), "Retirar de Ahorro" (self-serve or
  "Pedir permiso" depending on the flag), "Pedir mi pago" (Spend payout request).
- Link/entry from the existing cash balance UI on the gigs pages so kids discover it.
- Parents visiting `/bank` get redirected to `/parent/settings/family-bank` (or shown
  the family overview) — parents have no jars.

Ledger UI: the existing cash history view gains a jar chip per row (ES: Gastar/Ahorrar/
Compartir) and friendly type labels for ALLOWANCE/INTEREST/MATCH/JAR_TRANSFER.

---

## 10. Premium gating

New **boolean** feature `family_bank_automation` wired through the existing machinery
in `backend/app/core/premium.py` (`FEATURE_LIMIT_MAP` + `FEATURE_MIN_PLAN["family_bank_automation"] = "plus"`,
`DEFAULT_FREE_LIMITS["family_bank_automation"] = False`; add the key to the Plus/Pro
plan `limits` JSON in the plan seed/setup — coordinate with the P1 MXN-pricing
workstream which owns plan rows).

| Capability | Free | Plus | Pro | Enforcement point |
|---|---|---|---|---|
| Jar balances, kid bank page, jar chips in history | ✓ | ✓ | ✓ | — (basic ledger stays free — intel: gate automation, not the ledger) |
| Manual jar transfers (kid + parent) | ✓ | ✓ | ✓ | — |
| Payout by jar / settle Share | ✓ | ✓ | ✓ | — |
| Kid requests (payout / save withdrawal) | ✓ | ✓ | ✓ | — |
| Weekly allowance automation | – | ✓ | ✓ | `PUT /api/bank/settings` via `require_feature`; sweep re-checks plan |
| % auto-split of credits | – | ✓ | ✓ | `PUT /api/bank/settings` via `require_feature`; **plus a credit-time check**: the `CashService` splitter consults `get_family_plan_by_id` and falls back to 100/0/0 when not entitled — splits fire at gig approval (`gig_claim_service.py:114,409`), a path the sweep never touches, so a sweep-side check alone cannot enforce this |
| Parent-paid interest | – | ✓ | ✓ | `PUT /api/bank/settings` via `require_feature`; sweep re-checks plan |
| Parent match | – | ✓ | ✓ | same |

Downgrade behavior: **all** automation stops — the sweep skips non-entitled families
(no allowance/interest/match accrual, no notification), and the credit-time splitter
falls back to 100/0/0 (single row, jar='spend') for non-entitled families, so a family
that configured 50/30/20 on Plus does NOT keep auto-split after downgrading. Config
values are retained (not reset) so re-upgrading resumes automation with the same
settings — the alternative (resetting stored splits to 100/0/0 on downgrade) was
rejected because it destroys config and contradicts "re-upgrading resumes". Settings
PUT that merely *disables* automation is never gated.

Rationale (intel): interest/tier ladder is literally Greenlight's upsell axis;
allowance-trackers INSIGHTS #4 prescribes exactly this free/Plus cut; a genuinely free
basic ledger is the acquisition funnel (Rooster's free virtual tracker).

---

## 11. Test plan

`backend/tests/test_family_bank.py` (+ small additions to existing cash tests). Run via
`podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_family_bank.py -v --no-cov`.

1. **Settings CRUD**: parent upserts config; splits must sum to 100 (422 otherwise);
   range validation (interest ≤ 100%/wk, weekday 0–6); TEEN/CHILD get 403; cross-family
   target kid → 404/403 (tenant isolation).
2. **Lazy account creation**: first touch creates the default row; defaults are no-op
   (single-row credit, jar='spend').
3. **Split application**: `award_gig_cash` with 50/30/20 emits 3 rows summing exactly to
   the credit, floor + remainder-to-spend rounding verified (e.g. 101¢ split);
   `balance_before/after` chain is contiguous; jar balances + `cash_cents` invariant holds.
4. **Negative debits (shared cascade)**: GIG_EARNED claw-back debits in
   spend→save→share order, never negative jars; **negative ADJUSTMENT against a
   jar-split balance** (spend=0, save=200_00, adjust −100_00) cascades into `save` —
   succeeds, invariant #1 holds, no `ck_kid_bank_ranges` violation, no 500; adjust
   exceeding the total still floors at 0 (existing `/api/cash/{user_id}/adjust`
   contract preserved).
5. **Jar transfers**: paired net-zero rows; kid spend→save OK; kid save→spend blocked
   with `approval_required` when flag on, allowed when off; parent always allowed;
   insufficient jar balance → 422.
6. **Payout by jar**: payout validates against jar balance (not just total);
   `jar='share'` settles Share; legacy payout (no jar) debits spend.
7. **Payday — allowance**: kid on matching local weekday gets credited + split; wrong
   weekday untouched; `last_payday_at` stamped.
8. **Payday — interest**: floor(save × bps / 10000); computed on the **post-match**
   Save balance (step 1's MATCH earns interest the same payday, per D4) and before
   this payday's allowance lands; zero-rate → no row.
9. **Payday — match**: only kid-initiated save deposits since `last_payday_at` count
   (parent transfers and auto-split credits excluded); cap enforced; cap=0 = uncapped;
   **first payday** (`last_payday_at IS NULL`) matches all-time kid-initiated Save
   deposits — a kid with prior deposits gets a non-zero match, not silently $0.
10. **Payday — idempotency**: running the sweep twice in the same family-local day pays
    once; restart mid-family doesn't double-pay committed kids.
11. **Payday — timezone bucketing**: two families in different timezones evaluated
    against their own local weekday/hour (mirror the morning-reminder tests).
12. **Gating**: free-plan family skipped by the sweep entirely; Plus family processed;
    inactive/pending-approval kids skipped; **credit-time split gating**: a free-plan
    family with a stored 50/30/20 split gets a single-row jar='spend' credit at gig
    approval (splitter falls back to 100/0/0 when not entitled).
13. **Notifications**: payday notification created once, localized (es default / en via
    `preferred_lang`), amounts formatted; request endpoints notify all parents.
14. **Two-currency guard**: entire flow never touches `User.points` /
    `point_transactions` (assert points unchanged end-to-end).
15. **Premium unit**: `require_feature("family_bank_automation")` raises for free,
    passes for plus (extend `test_subscription.py` patterns).

Existing suites that must stay green: `tests` covering cash service/routes and gig
approval (call-site behavior unchanged for unconfigured kids).

---

## 12. Non-goals (v1) and open questions

### Explicit NON-goals

- **No points involvement** — jars/interest/match/allowance are cash-only. Points remain
  the separate privileges currency (two-currency constraint).
- **No pet integration** — intel suggests pet-payday celebrations, but the pet feature
  is under a go/no-go question (memory: `feedback_virtual_pet_uncertain`). Do not add
  pet hooks or dependencies.
- **No real banking** — no cards, no CLABE/SPEI, no charity rails, no custody of funds.
  The parent settles in the physical world; the app is the ledger.
- **No budget-module coupling** — no FK to `BudgetAccount`, no imports from
  `app.models.budget` (§D8). A read-only mirror is a post-launch design.
- No loans/payroll deductions (FamZoo P2 ideas), no round-ups, no chore-conditional
  allowance withholding, no custom named jars, no simulated investing.

### Open questions (decide before or during implementation — none block the schema)

1. **Chore-conditional allowance** (Greenlight's "no chore = no pay" [HIGH]): v2 flag
   `allowance_requires_chores` computing payout from completed assignments? The schema
   accommodates it later without migration churn (behavioral flag + sweep query).
2. **Custom/extra jars** (iAllowance "unlimited banks"): would force the normalized
   `kid_jar` table. Deliberately deferred; revisit only on user demand.
3. **Save-jar ↔ savings-goal linkage**: the P1 "Kid money: goal jar" workstream earmarks
   points toward rewards; a *cash* goal ("save $500 for the bike") over the Save jar is
   the natural v2 bridge. Coordinate naming so kids don't see two unrelated "goals".
4. **Share jar cause label**: add `share_cause VARCHAR` per family/kid so the UI says
   "Compartir — para los abuelos"? Cheap, could ride the same migration if the UI
   workstream wants it.
5. **Payday hour**: fixed ≥ 08:00 local — should it be configurable per family? Default
   opinionated; revisit on feedback.
6. **Teens defaults**: seed different default splits by role (e.g. TEEN 80/20/0)? v1
   ships one default (100/0/0) to keep free-tier behavior identical.
7. **Kiosk panel**: jar balances on the kiosk dashboard — coordinate with the P1 kiosk
   workstream once both land.

---

## 13. Workstream split (implementable as specced)

**Backend (P1-W1)** — one PR: migration (§7), `KidBankAccount` model, `CashService`
split/jar/claw-back changes, `BankService` (config, transfers, requests, payday sweep),
`/api/bank` router + `main.py` registration + scheduler job, notification types/copy,
premium feature key, `tests/test_family_bank.py`.

**UI (P1-W2)** — one PR, after backend merges: `/parent/settings/family-bank`,
kid `/bank` page, jar chips + type labels in cash history, request buttons, upsell
lock-states, ES/EN copy.

Dependencies on other P1 workstreams: MXN pricing workstream must add
`family_bank_automation: true` to Plus/Pro plan limits (coordinate the plan-seed
change); kiosk workstream consumes `GET /api/bank/family` later.
