import pytest
from app.models.gig import GigOffering, GigPayoutCadence


def test_payout_cadence_enum_values():
    assert {c.value for c in GigPayoutCadence} == {
        "immediate", "weekly", "biweekly", "monthly",
    }


def test_gig_offering_has_payout_cadence_column():
    assert "payout_cadence" in GigOffering.__table__.columns
