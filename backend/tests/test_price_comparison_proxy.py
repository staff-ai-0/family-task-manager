"""Tests for the price-comparison proxy: backend signs server-side,
forwards to the price-checker, secret never reaches the browser."""

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch target: the httpx.AsyncClient used inside the route module
_PATCH_TARGET = "app.api.routes.budget.price_comparison.httpx.AsyncClient"


def _make_mock_client(status_code: int, body: dict, captured: dict | None = None):
    """Return a mock AsyncClient context manager that records outbound calls."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json = MagicMock(return_value=body)
    mock_resp.text = ""

    async def fake_get(url, headers=None, **kw):
        if captured is not None:
            captured["url"] = url
            captured["headers"] = dict(headers or {})
        return mock_resp

    mock_client_instance = MagicMock()
    mock_client_instance.get = fake_get
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cls = MagicMock(return_value=mock_client_instance)
    return mock_cls


@pytest.mark.asyncio
async def test_proxy_signs_with_family_secret_and_forwards(
    client, auth_headers, db_session, test_family,
):
    """Backend should sign the transaction_id with the family's webhook
    secret and forward to the price-checker, then return the upstream body."""
    from app.models.a2a import FamilyA2AWebhook

    db_session.add(FamilyA2AWebhook(
        family_id=test_family.id, url="https://x", secret="topsecret", enabled=True,
    ))
    await db_session.commit()

    tx_id = "11111111-1111-1111-1111-111111111111"
    upstream_body = {"transaction_id": tx_id, "city": "Monterrey", "items": []}

    captured = {}
    mock_cls = _make_mock_client(200, upstream_body, captured)

    with patch(_PATCH_TARGET, new=mock_cls):
        r = await client.get(
            f"/api/budget/price-comparison/{tx_id}",
            headers=auth_headers,
        )

    assert r.status_code == 200, f"status={r.status_code} body={r.text}"
    assert r.json() == upstream_body
    assert tx_id in captured.get("url", ""), f"captured={captured}"
    expected_sig = "sha256=" + hmac.new(
        b"topsecret", tx_id.encode(), hashlib.sha256
    ).hexdigest()
    got_headers = captured.get("headers", {})
    assert got_headers.get("X-A2A-Signature") == expected_sig, f"headers={got_headers}"
    assert got_headers.get("X-A2A-Family") == str(test_family.id)


@pytest.mark.asyncio
async def test_proxy_404_when_no_webhook(
    client, auth_headers, db_session, test_family,
):
    tx_id = "11111111-1111-1111-1111-111111111111"
    r = await client.get(
        f"/api/budget/price-comparison/{tx_id}",
        headers=auth_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_proxy_passes_through_upstream_404(
    client, auth_headers, db_session, test_family,
):
    from app.models.a2a import FamilyA2AWebhook
    db_session.add(FamilyA2AWebhook(
        family_id=test_family.id, url="https://x", secret="s", enabled=True,
    ))
    await db_session.commit()

    mock_cls = _make_mock_client(404, {"detail": "no comparisons yet"})

    with patch(_PATCH_TARGET, new=mock_cls):
        r = await client.get(
            f"/api/budget/price-comparison/11111111-1111-1111-1111-111111111111",
            headers=auth_headers,
        )
    assert r.status_code == 404
