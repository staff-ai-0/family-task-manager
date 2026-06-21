"""L4: a cached PayPal OAuth token that gets rejected (401) must be
invalidated and the request retried once with a fresh token — otherwise the
stale token wedges every call until its natural expiry."""
import time
from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError

from app.services.paypal_service import _PayPalV2HTTP


def _resp(status, body=None, text=""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    m.text = text

    def _raise():
        if status >= 400:
            raise HTTPError(str(status))

    m.raise_for_status.side_effect = _raise
    return m


def test_get_invalidates_token_and_retries_once_on_401():
    _PayPalV2HTTP._token = "stale"
    _PayPalV2HTTP._token_exp = time.time() + 3600
    try:
        fake = MagicMock()
        fake.post.return_value = _resp(200, {"access_token": "fresh", "expires_in": 3600})
        fake.get.side_effect = [_resp(401, text="invalid token"), _resp(200, {"ok": True})]

        with patch("app.services.paypal_service.requests", fake):
            out = _PayPalV2HTTP.get("/v1/billing/subscriptions/I-X")

        assert out == {"ok": True}
        assert fake.get.call_count == 2, "must retry the GET once after a 401"
        assert _PayPalV2HTTP._token == "fresh", "stale token must be refreshed"
    finally:
        _PayPalV2HTTP._token = None
        _PayPalV2HTTP._token_exp = 0.0
