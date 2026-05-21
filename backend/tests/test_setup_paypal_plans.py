"""Tests for the setup-paypal-plans script."""
from unittest.mock import MagicMock

from scripts.setup_paypal_plans import (
    build_plan_definitions,
    create_product_if_missing,
    create_plan_if_missing,
)


def test_build_plan_definitions_returns_four():
    defs = build_plan_definitions(product_id="PROD-FAM")
    names = [d["name"] for d in defs]
    assert "Plus Monthly" in names
    assert "Plus Annual" in names
    assert "Pro Monthly" in names
    assert "Pro Annual" in names
    assert len(defs) == 4


def test_build_plan_definitions_has_trial_cycle():
    defs = build_plan_definitions(product_id="PROD-FAM")
    for d in defs:
        cycles = d["billing_cycles"]
        assert cycles[0]["tenure_type"] == "TRIAL"
        assert cycles[0]["frequency"]["interval_unit"] == "DAY"
        assert cycles[0]["frequency"]["interval_count"] == 7


def test_create_product_skips_if_exists():
    fake_api = MagicMock()
    fake_api.get.return_value = {
        "products": [{"id": "EXISTING", "name": "Family Task Manager"}]
    }
    pid = create_product_if_missing(fake_api, name="Family Task Manager")
    assert pid == "EXISTING"
    fake_api.post.assert_not_called()


def test_create_plan_skips_if_exists():
    fake_api = MagicMock()
    fake_api.get.return_value = {
        "plans": [{"id": "P-EXISTING", "name": "Plus Monthly"}]
    }
    pid = create_plan_if_missing(fake_api, plan_def={"name": "Plus Monthly"})
    assert pid == "P-EXISTING"
    fake_api.post.assert_not_called()
