"""WS-EXH: catch-all exception handler + X-Request-ID correlation.

- Unhandled exceptions → opaque JSON 500 ({"detail", "request_id"}) that never
  leaks str(exc)/tracebacks to the client, logged with method+path+user_id.
- Every response carries an X-Request-ID header; an inbound X-Request-ID is
  echoed back (sanitized) so clients/proxies can correlate.
- The catch-all must not shadow domain handlers, and Starlette must still
  re-raise the exception upward (that re-raise is what lets the Sentry ASGI
  wrapper capture unhandled errors).
"""

import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

BOOM_PATH = "/api/_test/boom"
SECRET_MARKER = "s3cr3t-internal-detail"

# Register a deliberately-crashing route once (test-only; include_in_schema off).
if not any(getattr(r, "path", None) == BOOM_PATH for r in app.router.routes):

    @app.get(BOOM_PATH, include_in_schema=False)
    async def _boom():
        raise RuntimeError(f"database password is {SECRET_MARKER}")


@pytest_asyncio.fixture
async def no_raise_client():
    """Client that lets the app's 500 response through instead of re-raising."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCatchAllHandler:
    @pytest.mark.asyncio
    async def test_500_json_without_leaking_exception(self, no_raise_client):
        r = await no_raise_client.get(BOOM_PATH)
        assert r.status_code == 500
        body = r.json()
        assert body["detail"] == "Internal server error"
        assert isinstance(body["request_id"], str) and body["request_id"]
        assert set(body.keys()) == {"detail", "request_id"}
        # str(exc) / traceback must never reach the client.
        assert SECRET_MARKER not in r.text
        assert "RuntimeError" not in r.text
        assert "Traceback" not in r.text

    @pytest.mark.asyncio
    async def test_500_carries_request_id_header_matching_body(self, no_raise_client):
        r = await no_raise_client.get(BOOM_PATH)
        assert r.headers["X-Request-ID"] == r.json()["request_id"]

    @pytest.mark.asyncio
    async def test_inbound_request_id_echoed_on_500(self, no_raise_client):
        rid = "corr-id-abc.123"
        r = await no_raise_client.get(BOOM_PATH, headers={"X-Request-ID": rid})
        assert r.status_code == 500
        assert r.headers["X-Request-ID"] == rid
        assert r.json()["request_id"] == rid

    @pytest.mark.asyncio
    async def test_log_includes_method_path_and_request_id(self, no_raise_client, caplog):
        with caplog.at_level(logging.ERROR, logger="app.core.exception_handlers"):
            await no_raise_client.get(
                BOOM_PATH, headers={"X-Request-ID": "log-corr-42"}
            )
        messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "app.core.exception_handlers"
        ]
        assert any(
            f"GET {BOOM_PATH}" in m and "request_id=log-corr-42" in m for m in messages
        ), messages
        # Unauthenticated request → user_id logged as None, and the traceback
        # (exc_info) is attached to the record for operators.
        assert any("user_id=None" in m for m in messages)
        assert any(
            rec.exc_info and rec.exc_info[0] is RuntimeError
            for rec in caplog.records
            if rec.name == "app.core.exception_handlers"
        )

    @pytest.mark.asyncio
    async def test_log_resolves_user_id_from_bearer_token(
        self, no_raise_client, auth_headers, test_parent_user, caplog
    ):
        with caplog.at_level(logging.ERROR, logger="app.core.exception_handlers"):
            await no_raise_client.get(BOOM_PATH, headers=auth_headers)
        messages = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "app.core.exception_handlers"
        ]
        assert any(f"user_id={test_parent_user.id}" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_exception_still_propagates_for_sentry(self):
        """ServerErrorMiddleware must re-raise after responding — that re-raise
        is what the Sentry ASGI wrapper (outermost) captures. If this starts
        failing, the catch-all is swallowing exceptions and Sentry is blind."""
        transport = ASGITransport(app=app)  # raise_app_exceptions=True (default)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with pytest.raises(RuntimeError):
                await c.get(BOOM_PATH)

    @pytest.mark.asyncio
    async def test_domain_handlers_not_shadowed(self, client):
        """Specific handlers (e.g. 401 for missing credentials) still win —
        the catch-all only sees exceptions nothing else claimed."""
        r = await client.get("/api/auth/me")
        assert r.status_code == 401


class TestRequestIDMiddleware:
    @pytest.mark.asyncio
    async def test_generated_id_on_success_response(self, no_raise_client):
        r = await no_raise_client.get("/health")
        assert r.status_code == 200
        rid = r.headers.get("X-Request-ID")
        assert rid and len(rid) >= 8

    @pytest.mark.asyncio
    async def test_inbound_id_echoed_on_success_response(self, no_raise_client):
        r = await no_raise_client.get("/health", headers={"X-Request-ID": "my-rid-7"})
        assert r.headers["X-Request-ID"] == "my-rid-7"

    @pytest.mark.asyncio
    async def test_inbound_id_is_sanitized(self, no_raise_client):
        """Hostile ids are stripped to a safe charset before hitting logs/headers."""
        r = await no_raise_client.get(
            "/health", headers={"X-Request-ID": "evil id<script>!" + "x" * 200}
        )
        rid = r.headers["X-Request-ID"]
        assert "<" not in rid and " " not in rid and "!" not in rid
        assert len(rid) <= 64

    @pytest.mark.asyncio
    async def test_fresh_id_per_request(self, no_raise_client):
        r1 = await no_raise_client.get("/health")
        r2 = await no_raise_client.get("/health")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]
