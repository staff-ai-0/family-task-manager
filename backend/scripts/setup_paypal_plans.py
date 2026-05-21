"""
Idempotent PayPal Product + Plans setup.

Run once per environment (sandbox + later live). Reads PAYPAL_MODE,
PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET from env. Creates the "Family Task
Manager" Product and 4 Plans (Plus monthly/annual, Pro monthly/annual)
with 7-day trial. Outputs plan IDs as env-var lines for .env.

Usage:
    docker exec family_app_backend python -m scripts.setup_paypal_plans
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

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


def build_plan_definitions(product_id: str) -> list[dict[str, Any]]:
    """Define the 4 Plans (Plus/Pro × monthly/annual) with 7-day trial."""
    cycles = {
        "monthly": {"interval_unit": "MONTH", "interval_count": 1},
        "annual": {"interval_unit": "YEAR", "interval_count": 1},
    }
    prices = {
        ("plus", "monthly"): "5.00",
        ("plus", "annual"): "50.00",
        ("pro", "monthly"): "15.00",
        ("pro", "annual"): "150.00",
    }
    out = []
    for tier in ("plus", "pro"):
        for cycle in ("monthly", "annual"):
            out.append(
                {
                    "product_id": product_id,
                    "name": f"{tier.capitalize()} {cycle.capitalize()}",
                    "description": f"Family Task Manager — {tier} ({cycle})",
                    "status": "ACTIVE",
                    "billing_cycles": [
                        {
                            "tenure_type": "TRIAL",
                            "sequence": 1,
                            "total_cycles": 1,
                            "frequency": {
                                "interval_unit": "DAY",
                                "interval_count": 7,
                            },
                            "pricing_scheme": {
                                "fixed_price": {"value": "0", "currency_code": "USD"}
                            },
                        },
                        {
                            "tenure_type": "REGULAR",
                            "sequence": 2,
                            "total_cycles": 0,
                            "frequency": cycles[cycle],
                            "pricing_scheme": {
                                "fixed_price": {
                                    "value": prices[(tier, cycle)],
                                    "currency_code": "USD",
                                }
                            },
                        },
                    ],
                    "payment_preferences": {
                        "auto_bill_outstanding": True,
                        "setup_fee": {"value": "0", "currency_code": "USD"},
                        "setup_fee_failure_action": "CONTINUE",
                        "payment_failure_threshold": 3,
                    },
                }
            )
    return out


def create_product_if_missing(api: PayPalAPI, name: str) -> str:
    """Look up product by name; create if absent. Returns product_id."""
    page = api.get("/v1/catalogs/products?page_size=20")
    for p in page.get("products", []):
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


def create_plan_if_missing(api: PayPalAPI, plan_def: dict[str, Any]) -> str:
    """Look up plan by name; create if absent. Returns plan_id."""
    page = api.get("/v1/billing/plans?page_size=20")
    for p in page.get("plans", []):
        if p.get("name") == plan_def["name"]:
            return p["id"]
    created = api.post("/v1/billing/plans", plan_def)
    return created["id"]


def main() -> int:
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

    out_lines: list[str] = []
    for plan_def in build_plan_definitions(product_id):
        plan_id = create_plan_if_missing(api, plan_def)
        tier, cycle = plan_def["name"].lower().split(" ")
        env_key = f"PAYPAL_PLAN_ID_{tier.upper()}_{cycle.upper()}"
        out_lines.append(f"{env_key}={plan_id}")

    print("\n# Add these to your .env:")
    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
