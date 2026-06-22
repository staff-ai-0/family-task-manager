"""L4: a cached PayPal OAuth token that gets rejected (401) must be
invalidated and the request retried once with a fresh token — otherwise the
stale token wedges every call until its natural expiry."""
import time
from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError

from app.services.paypal_service import _PayPalV2HTTP


def _resp(status, body=None, text=None):
    import json
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    # post() returns {} when r.text is empty, so a body implies non-empty text.
    m.text = text if text is not None else (json.dumps(body) if body else "")

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


def _seed_token():
    _PayPalV2HTTP._token = "t"
    _PayPalV2HTTP._token_exp = time.time() + 3600


def test_get_backs_off_and_retries_on_503_then_succeeds():
    _seed_token()
    orig = _PayPalV2HTTP._BACKOFF_BASE
    _PayPalV2HTTP._BACKOFF_BASE = 0  # no real sleep in tests
    try:
        fake = MagicMock()
        fake.get.side_effect = [_resp(503), _resp(503), _resp(200, {"ok": True})]
        with patch("app.services.paypal_service.requests", fake):
            out = _PayPalV2HTTP.get("/x")
        assert out == {"ok": True}
        assert fake.get.call_count == 3, "must retry transient 5xx with backoff"
    finally:
        _PayPalV2HTTP._BACKOFF_BASE = orig
        _PayPalV2HTTP._token = None
        _PayPalV2HTTP._token_exp = 0.0


def test_post_retries_on_429_then_succeeds():
    _seed_token()
    orig = _PayPalV2HTTP._BACKOFF_BASE
    _PayPalV2HTTP._BACKOFF_BASE = 0
    try:
        fake = MagicMock()
        fake.post.side_effect = [_resp(429), _resp(200, {"ok": True})]
        with patch("app.services.paypal_service.requests", fake):
            out = _PayPalV2HTTP.post("/x", {"a": 1})
        assert out == {"ok": True}
        assert fake.post.call_count == 2
    finally:
        _PayPalV2HTTP._BACKOFF_BASE = orig
        _PayPalV2HTTP._token = None
        _PayPalV2HTTP._token_exp = 0.0


def test_get_gives_up_after_max_attempts_on_persistent_5xx():
    _seed_token()
    orig = _PayPalV2HTTP._BACKOFF_BASE
    _PayPalV2HTTP._BACKOFF_BASE = 0
    try:
        fake = MagicMock()
        fake.get.side_effect = [_resp(503), _resp(503), _resp(503), _resp(503)]
        with patch("app.services.paypal_service.requests", fake):
            with pytest.raises(HTTPError):
                _PayPalV2HTTP.get("/x")
        assert fake.get.call_count == _PayPalV2HTTP._RETRY_ATTEMPTS
    finally:
        _PayPalV2HTTP._BACKOFF_BASE = orig
        _PayPalV2HTTP._token = None
        _PayPalV2HTTP._token_exp = 0.0
