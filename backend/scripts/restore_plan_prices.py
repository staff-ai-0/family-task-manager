#!/usr/bin/env python3
"""Re-assert canonical subscription plan prices — the remedy that actually
works on a REPEAT re-zeroing.

Why this exists
----------------
The deploy script and the operator console both used to point at
``alembic upgrade head`` as the fix for a broken billing check. That only
works ONCE: alembic refuses to re-run an already-applied revision, so once
``2026_07_31_restore_plan_prices`` has run on a host, a future out-of-band
re-zeroing (the exact recurrence this branch exists to catch — see
app/core/plan_pricing.py's module docstring) makes ``alembic upgrade head``
report "already at head" and change nothing. The operator follows the
printed instruction, sees no effect, and is stranded at the moment the
alarm fires.

This script re-asserts ``app.core.plan_pricing.CANONICAL_PRICES`` on the
four paid ``(name, currency)`` rows every time it is run, regardless of
migration state. It is the one documented remedy that always works.

It deliberately does NOT touch ``is_active`` or ``paypal_plan_id_*`` — those
are provisioning state owned by scripts/setup_paypal_plans.py. A script
fighting the operator over them is how prod's MXN rows ended up
active-but-unwired (see that script's module docstring).

Usage:
    docker exec family_app_backend python -m scripts.restore_plan_prices
    docker exec family_app_backend python -m scripts.restore_plan_prices --dry-run

--dry-run reports what would change (name/currency, old -> new) without
writing anything.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_pricing import CANONICAL_PRICES
from app.models.subscription import SubscriptionPlan


async def restore_plan_prices(db: AsyncSession, *, dry_run: bool = False) -> list[dict]:
    """Re-assert CANONICAL_PRICES on the rows that exist and differ.

    Returns one entry per row that was changed (or would be, under
    ``dry_run``); rows that already match canonical, and (name, currency)
    pairs with no row in the table, are not included. Callers are
    responsible for committing ``db`` when ``dry_run`` is False.
    """
    changes: list[dict] = []
    for (name, currency), (monthly, annual) in CANONICAL_PRICES.items():
        row = (
            await db.execute(
                select(SubscriptionPlan).where(
                    SubscriptionPlan.name == name,
                    SubscriptionPlan.currency == currency,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            continue
        if row.price_monthly_cents == monthly and row.price_annual_cents == annual:
            continue
        changes.append(
            {
                "name": name,
                "currency": currency,
                "old": (row.price_monthly_cents, row.price_annual_cents),
                "new": (monthly, annual),
            }
        )
        if not dry_run:
            row.price_monthly_cents = monthly
            row.price_annual_cents = annual
    return changes


def _report(changes: list[dict], *, dry_run: bool) -> None:
    verb = "would change" if dry_run else "changed"
    if not changes:
        print("Nothing to do — every present row already matches CANONICAL_PRICES.")
        return
    print(f"{len(changes)} row(s) {verb}:")
    for c in changes:
        old_m, old_a = c["old"]
        new_m, new_a = c["new"]
        print(
            f"  {c['name']}/{c['currency']}: "
            f"monthly {old_m} -> {new_m}, annual {old_a} -> {new_a}"
        )


async def _main_async(dry_run: bool) -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        changes = await restore_plan_prices(session, dry_run=dry_run)
        if not dry_run:
            await session.commit()
    _report(changes, dry_run=dry_run)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        print("DRY RUN — no writes will be made.\n")
    return asyncio.run(_main_async(dry_run))


if __name__ == "__main__":
    sys.exit(main())
