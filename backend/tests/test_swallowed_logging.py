"""M5: non-fatal notification/analytics failures must be logged, not silently
swallowed with a bare ``except: pass``."""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.gig_claim_service import GigClaimService


@pytest.mark.asyncio
async def test_notify_parents_failure_is_logged_not_silent(
    db_session, test_family, test_parent_user, caplog
):
    claim = SimpleNamespace(family_id=test_family.id)
    offering = SimpleNamespace(title="Wash dishes")
    claimer = SimpleNamespace(name="Emma")

    with patch(
        "app.services.notification_service.NotificationService.create",
        side_effect=RuntimeError("boom"),
    ):
        with caplog.at_level(logging.WARNING):
            # Must not raise — notification is best-effort.
            await GigClaimService._notify_parents_pending(
                db_session, claim, offering, claimer
            )

    assert any(
        "notify parents of pending gig failed" in r.getMessage()
        for r in caplog.records
    ), "swallowed notification failure must be logged"
