"""
Idempotent PayPal Product + Plans setup.

Run once per environment (sandbox + later live). Reads PAYPAL_MODE,
PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET from env. Creates the "Family Task
Manager" Product and 8 Plans (Plus/Pro x monthly/annual x USD/MXN) with a
7-day trial. Outputs plan IDs as env-var lines plus the SQL UPDATEs that
wire them into the subscription_plans rows AND activate them (the MXN rows
are migration-seeded inactive until wired — see _sql_update).

MXN plans are the Mexico-first defaults. Prices come from
app/core/plan_pricing.py (CANONICAL_PRICES) — the single source of truth.
Do NOT add a price constant to this file.

NOTE: verify the PayPal business account supports MXN pricing before the
live run (Mexico-registered accounts do; plan creation 400s otherwise).

Usage:
    docker exec family_app_backend python -m scripts.setup_paypal_plans
    docker exec family_app_backend python -m scripts.setup_paypal_plans --dry-run

--dry-run prints what would be created (no PayPal API calls, no credentials
needed) so the operator can review names/prices/currencies first.
"""
from __future__ import annotations

import os
import sys
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import requests


PAYPAL_API_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


class PayPalAPI:
    def __init__(self, mode: str, client_id: str, client_secret: str):
        self.base = PAYPAL_API_BASE[mode]
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_exp: float = 0.0

    def _auth(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        r = requests.post(
            f"{self.base}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + data.get("expires_in", 3600)
        return self._token

    def get(self, path: str) -> dict[str, Any]:
        r = requests.get(
            f"{self.base}{path}",
            headers={"Authorization": f"Bearer {self._auth()}"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(
            f"{self.base}{path}",
            headers={
                "Authorization": f"Bearer {self._auth()}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Prices come from the canonical table — do NOT add a copy here.
# ---------------------------------------------------------------------------
from app.core.plan_pricing import price_decimal_str  # noqa: E402

TRIAL_DAYS = 7


def _plan_name(tier: str, cycle: str, currency: str) -> str:
    """PayPal plan display name; the idempotency key at PayPal's side.

    USD keeps the legacy 2-word names ("Plus Monthly") so already-provisioned
    environments are matched, not duplicated. Other currencies get an
    explicit suffix ("Plus Monthly MXN").
    """
    base = f"{tier.capitalize()} {cycle.capitalize()}"
    return base if currency == "USD" else f"{base} {currency}"


def plan_meta(plan_def: dict[str, Any]) -> tuple[str, str, str]:
    """Recover (tier, cycle, currency) from a plan definition."""
    parts = plan_def["name"].split(" ")
    tier, cycle = parts[0].lower(), parts[1].lower()
    currency = parts[2].upper() if len(parts) > 2 else "USD"
    return tier, cycle, currency


def build_plan_definitions(
    product_id: str, currencies: tuple[str, ...] = ("USD", "MXN")
) -> list[dict[str, Any]]:
    """Define the Plans (Plus/Pro × monthly/annual × currency) with trial."""
    cycles = {
        "monthly": {"interval_unit": "MONTH", "interval_count": 1},
        "annual": {"interval_unit": "YEAR", "interval_count": 1},
    }
    out = []
    for currency in currencies:
        for tier in ("plus", "pro"):
            for cycle in ("monthly", "annual"):
                out.append(
                    {
                        "product_id": product_id,
                        "name": _plan_name(tier, cycle, currency),
                        "description": (
                            f"Family Task Manager — {tier} ({cycle}, {currency})"
                        ),
                        "status": "ACTIVE",
                        "billing_cycles": [
                            {
                                "tenure_type": "TRIAL",
                                "sequence": 1,
                                "total_cycles": 1,
                                "frequency": {
                                    "interval_unit": "DAY",
                                    "interval_count": TRIAL_DAYS,
                                },
                                "pricing_scheme": {
                                    "fixed_price": {
                                        "value": "0",
                                        "currency_code": currency,
                                    }
                                },
                            },
                            {
                                "tenure_type": "REGULAR",
                                "sequence": 2,
                                "total_cycles": 0,
                                "frequency": cycles[cycle],
                                "pricing_scheme": {
                                    "fixed_price": {
                                        "value": price_decimal_str(
                                            tier, cycle, currency
                                        ),
                                        "currency_code": currency,
                                    }
                                },
                            },
                        ],
                        "payment_preferences": {
                            "auto_bill_outstanding": True,
                            "setup_fee": {"value": "0", "currency_code": currency},
                            "setup_fee_failure_action": "CONTINUE",
                            "payment_failure_threshold": 3,
                        },
                    }
                )
    return out


def iter_all_pages(api: PayPalAPI, path: str, items_key: str):
    """Yield every item across ALL pages of a PayPal list endpoint.

    Follows the HATEOAS ``links`` rel=next chain until exhausted. The
    first-page-only lookup this replaces silently missed pre-existing
    plans/products beyond page 1 (easily hit once legacy/sandbox plans
    accumulate — this repo alone defines 8 plans), which made the
    "if missing" checks create ACTIVE duplicates on re-run.
    """
    while path:
        page = api.get(path)
        yield from page.get(items_key, [])
        next_href = next(
            (
                link.get("href")
                for link in page.get("links", [])
                if link.get("rel") == "next"
            ),
            None,
        )
        if not next_href:
            return
        # PayPal returns absolute hrefs; PayPalAPI.get expects a base-relative
        # path, so strip scheme+host and keep path?query.
        split = urlsplit(next_href)
        path = f"{split.path}?{split.query}" if split.query else split.path


def create_product_if_missing(api: PayPalAPI, name: str) -> str:
    """Look up product by name (across all pages); create if absent."""
    for p in iter_all_pages(api, "/v1/catalogs/products?page_size=20", "products"):
        if p.get("name") == name:
            return p["id"]
    created = api.post(
        "/v1/catalogs/products",
        {
            "name": name,
            "description": "Gamified family chore and task manager",
            "type": "SERVICE",
            "category": "SOFTWARE",
        },
    )
    return created["id"]


class PlanPriceMismatch(RuntimeError):
    """A PayPal plan matched by name charges a stale (non-canonical) price.

    Raised by create_plan_if_missing instead of silently reusing the match:
    a name collision is NOT proof the plan is safe to reuse (see that
    function's docstring).
    """


class PlanPriceUnavailable(RuntimeError):
    """A PayPal plan matched by name has no comparable REGULAR price even
    after fetching its full Show-Plan-Details representation.

    This is NOT evidence of a stale price — it means the price data itself
    is missing or malformed, which is a different (and rarer) problem.
    Raised separately from PlanPriceMismatch so the operator isn't told
    "charges None" for something that was never comparable in the first
    place.
    """


def _regular_fixed_price(plan: dict[str, Any]) -> dict[str, Any] | None:
    """The REGULAR billing cycle's fixed_price from a PayPal plan object, or
    None if absent.

    Callers must pass the Show Plan Details response (GET
    /v1/billing/plans/{id}), NOT a List Plans item. Per billing_subscriptions_v1's
    published OpenAPI spec, GET /v1/billing/plans declares a `Prefer` header
    whose default is `return=minimal` — a minimal response carries only
    `id`, `status`, and HATEOAS `links`, no `billing_cycles` — while
    PayPalAPI.get sends no Prefer override at all, so list items never carry
    a price. Show Plan Details takes no `Prefer` parameter and returns the
    full representation (including `billing_cycles`) by default, so it is
    the one PayPal response this function can trust.
    """
    for cycle in plan.get("billing_cycles") or []:
        if cycle.get("tenure_type") == "REGULAR":
            return (cycle.get("pricing_scheme") or {}).get("fixed_price")
    return None


def _same_price(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Numeric equality on ``value`` + exact match on ``currency_code``.

    PayPal does not guarantee decimal formatting on the wire: the live API
    returned ``'5.0'`` on 2026-07-31 for a plan provisioned as ``'5.00'``,
    and raw dict equality aborted the entire provisioning run over that
    formatting difference. Decimal("5.0") == Decimal("5.00"), so numeric
    comparison is the correct semantics; currency_code stays an exact
    string match (USD 99 and MXN 99 are different prices).

    Raises decimal.InvalidOperation (or TypeError on a non-string/number)
    when a value cannot be parsed — the caller maps that to
    PlanPriceUnavailable, because unparseable price data is missing data,
    not evidence of a stale price.
    """
    if (actual.get("currency_code") or "") != (expected.get("currency_code") or ""):
        return False
    return Decimal(str(actual["value"])) == Decimal(str(expected["value"]))


def create_plan_if_missing(api: PayPalAPI, plan_def: dict[str, Any]) -> str:
    """Look up plan by name (across all pages); create if absent.

    A name match alone is NOT enough to safely reuse a plan: PayPal's plan
    id is the only thing that actually fixes what a subscriber is charged,
    and idempotency-by-name means the next operator run relies on exactly
    this reuse path (if the 2026-07-16 provisioning really happened, this
    reuses those plans rather than duplicating them). If a reused plan
    carries a stale price — e.g. a pre-usd_price_alignment "Plus Monthly"
    still at $4.99 — the DB gets force-set to canonical (by migration or
    scripts/restore_plan_prices.py) while PayPal keeps charging the old
    amount, and a customer is billed something they were never shown. So
    before reusing a name match, this verifies its REGULAR billing cycle's
    fixed_price (value AND currency_code) against what plan_def says it
    should charge.

    The List Plans item used for the name match is NOT trustworthy for this
    check — see _regular_fixed_price's docstring: PayPal's `Prefer:
    return=minimal` default strips `billing_cycles` from list items
    entirely, which is indistinguishable from "no billing_cycles" and would
    make every reused plan look like a price mismatch (`charges None`) on
    the very first name match against the real API. So on a name match this
    fetches the plan's full representation via Show Plan Details (GET
    /v1/billing/plans/{id}, no Prefer needed, cost is fine — this only
    happens once per name match) and compares THAT instead. A genuine
    mismatch raises PlanPriceMismatch — naming the plan id, its actual
    price, and the expected price — rather than proceeding silently, so the
    operator sees it BEFORE any wiring SQL is applied. If the detail fetch
    still has no comparable REGULAR price (missing/malformed data, not a
    stale price), that raises the distinct PlanPriceUnavailable instead —
    absent price data must mean "go fetch it", never "mismatch".
    """
    expected_price = [
        c for c in plan_def["billing_cycles"] if c["tenure_type"] == "REGULAR"
    ][0]["pricing_scheme"]["fixed_price"]

    for p in iter_all_pages(api, "/v1/billing/plans?page_size=20", "plans"):
        if p.get("name") == plan_def["name"]:
            plan_id = p["id"]
            detail = api.get(f"/v1/billing/plans/{plan_id}")
            actual_price = _regular_fixed_price(detail)
            if actual_price is None:
                raise PlanPriceUnavailable(
                    f"PayPal plan {plan_id!r} named {plan_def['name']!r} has "
                    "no REGULAR billing-cycle price in its Show Plan Details "
                    "response, so its price cannot be verified. This is NOT "
                    "a stale-price mismatch — the price data itself is "
                    "missing or malformed. Inspect the plan directly at "
                    "PayPal before re-running provisioning."
                )
            try:
                prices_match = _same_price(actual_price, expected_price)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise PlanPriceUnavailable(
                    f"PayPal plan {plan_id!r} named {plan_def['name']!r} has "
                    f"an unparseable REGULAR price {actual_price!r} in its "
                    "Show Plan Details response, so its price cannot be "
                    "verified. This is NOT a stale-price mismatch — the "
                    "price data itself is malformed. Inspect the plan "
                    "directly at PayPal before re-running provisioning."
                ) from exc
            if not prices_match:
                raise PlanPriceMismatch(
                    f"PayPal plan {plan_id!r} named {plan_def['name']!r} "
                    f"charges {actual_price!r} but the canonical price is "
                    f"{expected_price!r}. Refusing to reuse it — retire the "
                    "stale plan at PayPal (or correct its price there) "
                    "before re-running provisioning."
                )
            return plan_id
    created = api.post("/v1/billing/plans", plan_def)
    return created["id"]


def _env_key(tier: str, cycle: str, currency: str) -> str:
    """Env-var key for a plan id. USD keeps the legacy 2-part keys."""
    key = f"PAYPAL_PLAN_ID_{tier.upper()}_{cycle.upper()}"
    return key if currency == "USD" else f"{key}_{currency.upper()}"


def _sql_update(tier: str, cycle: str, currency: str, plan_id: str) -> str:
    """SQL that wires the provisioned PayPal plan id into subscription_plans.

    Also flips is_active = true: the mxn_plan_currency_w6 migration seeds the
    MXN rows INACTIVE (they cannot be checked out while their PayPal ids are
    NULL), and this wiring step is what activates them. Idempotent for rows
    that are already active (USD).
    """
    column = f"paypal_plan_id_{cycle}"
    return (
        f"UPDATE subscription_plans SET {column} = '{plan_id}', is_active = true "
        f"WHERE name = '{tier}' AND currency = '{currency}';"
    )


def print_dry_run() -> None:
    """Print what a real run would ensure — no API calls, no credentials."""
    print("DRY RUN — no PayPal API calls made.\n")
    print('Would ensure product: "Family Task Manager" (SERVICE / SOFTWARE)')
    print(f"Would ensure {len(build_plan_definitions('<product-id>'))} plans "
          f"({TRIAL_DAYS}-day trial, then:)")
    for plan_def in build_plan_definitions("<product-id>"):
        tier, cycle, currency = plan_meta(plan_def)
        price = price_decimal_str(tier, cycle, currency)
        interval = "month" if cycle == "monthly" else "year"
        print(f"  - {plan_def['name']:<20} {currency} {price:>8} / {interval}")
    print(
        "\nA real run prints the provisioned plan ids as .env lines and as "
        "SQL UPDATEs for subscription_plans."
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--dry-run" in args:
        print_dry_run()
        return 0

    mode = os.environ.get("PAYPAL_MODE", "sandbox")
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.stderr.write(
            "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET env vars required\n"
        )
        return 1
    if mode not in PAYPAL_API_BASE:
        sys.stderr.write(f"Invalid PAYPAL_MODE: {mode}\n")
        return 1

    api = PayPalAPI(mode, client_id, client_secret)
    product_id = create_product_if_missing(api, "Family Task Manager")

    env_lines: list[str] = []
    sql_lines: list[str] = []
    for plan_def in build_plan_definitions(product_id):
        plan_id = create_plan_if_missing(api, plan_def)
        tier, cycle, currency = plan_meta(plan_def)
        env_lines.append(f"{_env_key(tier, cycle, currency)}={plan_id}")
        sql_lines.append(_sql_update(tier, cycle, currency, plan_id))

    print("\n# Add these to your .env:")
    for line in env_lines:
        print(line)
    print(
        "\n-- Run these against the app DB to wire the plan ids "
        "(psql -U familyapp familyapp):"
    )
    for line in sql_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
