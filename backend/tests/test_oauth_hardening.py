"""POST /api/oauth/google is public, creates families, and must be defended.

Three gaps this pins:

1. No rate limit. Every sibling auth route is decorated; this one was not, so an
   endpoint that creates users and whole families had no throttle at any layer
   (the Limiter carries no default/application limits either).
2. Blocking I/O on the event loop. `id_token.verify_oauth2_token` is synchronous
   and fetches Google's certs BEFORE validating the signature — so even a garbage
   token triggers an outbound HTTPS GET, with a 120s library default timeout.
3. Uncached certs, re-fetched on every single call.
"""
import asyncio
from unittest.mock import patch

import pytest

from app.core.rate_limiter import AUTH_LIMIT
from app.services import google_oauth_service as svc
from app.services.google_oauth_service import GoogleOAuthService


def _idinfo(aud: str) -> dict:
    return {
        "iss": "https://accounts.google.com",
        "aud": aud,
        "sub": "google-sub-1",
        "email": "user@example.com",
        "name": "Test User",
        "email_verified": True,
    }


class TestOAuthRateLimiting:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "app.api.routes.oauth.google_oauth_login",
            "app.api.routes.oauth.verify_google_token",
        ],
    )
    def test_both_oauth_routes_carry_the_auth_limit(self, endpoint):
        """slowapi registers decorated endpoints in the limiter's route table."""
        from app.api.routes import oauth  # noqa: F401  (import registers routes)
        from app.core.rate_limiter import limiter

        registered = limiter._route_limits
        assert endpoint in registered, (
            f"{endpoint} has no slowapi limit — an unauthenticated, "
            "family-creating endpoint must be throttled"
        )
        applied = [str(item.limit) for item in registered[endpoint]]
        assert applied, f"{endpoint} is registered but carries no limit"

    def test_oauth_routes_accept_the_request_object_slowapi_needs(self):
        """slowapi resolves the client key from a `request: Request` parameter."""
        import inspect

        from starlette.requests import Request

        from app.api.routes import oauth

        for endpoint in (oauth.google_oauth_login, oauth.verify_google_token):
            sig = inspect.signature(endpoint)
            assert "request" in sig.parameters, (
                f"{endpoint.__name__} must take `request` for slowapi keying"
            )
            assert sig.parameters["request"].annotation is Request, (
                f"{endpoint.__name__}'s `request` must be a starlette Request, "
                "not the Pydantic body model"
            )

    def test_auth_limit_is_a_real_bound(self):
        assert AUTH_LIMIT, "AUTH_LIMIT must be a non-empty slowapi limit string"


class TestCertCaching:
    def setup_method(self):
        svc._cert_cache.clear()

    def test_certs_fetched_once_then_served_from_cache(self):
        calls = []

        class _Resp:
            status = 200
            data = b'{"keys": []}'
            headers = {"Cache-Control": "public, max-age=1800"}

        def _inner(url, method="GET", body=None, headers=None, timeout=None, **kw):
            calls.append((url, timeout))
            return _Resp()

        transport = svc._CachingCertsTransport()
        transport._inner = _inner

        first = transport("https://www.googleapis.com/oauth2/v3/certs")
        second = transport("https://www.googleapis.com/oauth2/v3/certs")

        assert len(calls) == 1, "cert bundle must be cached across verify calls"
        assert first.data == second.data == b'{"keys": []}'

    def test_fetch_timeout_is_bounded(self):
        """The library default is 120s; a hung googleapis must not hold a slot."""
        seen = {}

        class _Resp:
            status = 200
            data = b"{}"
            headers = {}

        def _inner(url, method="GET", body=None, headers=None, timeout=None, **kw):
            seen["timeout"] = timeout
            return _Resp()

        transport = svc._CachingCertsTransport()
        transport._inner = _inner
        transport("https://www.googleapis.com/oauth2/v3/certs")

        assert seen["timeout"] == svc._CERT_FETCH_TIMEOUT
        assert svc._CERT_FETCH_TIMEOUT <= 30

    def test_non_200_is_not_cached(self):
        calls = []

        class _Resp:
            status = 500
            data = b"boom"
            headers = {}

        def _inner(url, **kw):
            calls.append(url)
            return _Resp()

        transport = svc._CachingCertsTransport()
        transport._inner = _inner
        transport("https://certs")
        transport("https://certs")

        assert len(calls) == 2, "a failed cert fetch must not poison the cache"

    @pytest.mark.parametrize(
        "header,expected",
        [
            ({"Cache-Control": "public, max-age=900, must-revalidate"}, 900.0),
            ({"cache-control": "max-age=60"}, 60.0),
            ({"Cache-Control": "no-store"}, None),
            ({}, None),
            (None, None),
        ],
    )
    def test_max_age_parsing(self, header, expected):
        assert svc._parse_max_age(header) == expected

    @pytest.mark.parametrize(
        "header,expected",
        [
            # Explicit no-cache directives must NOT fall back to the default TTL:
            # pinning a rotated-away cert bundle for an hour would reject every
            # real token until it expired, with no way to self-heal.
            ({"Cache-Control": "no-store"}, None),
            ({"Cache-Control": "no-cache"}, None),
            ({"Cache-Control": "max-age=0"}, None),
            ({"Cache-Control": "max-age=600"}, 600.0),
            # Only a MISSING directive falls back.
            ({}, svc._CERT_TTL_FALLBACK),
            (None, svc._CERT_TTL_FALLBACK),
        ],
    )
    def test_cache_ttl_honours_no_store(self, header, expected):
        assert svc._cache_ttl(header) == expected

    def test_no_store_response_is_refetched(self):
        calls = []

        class _Resp:
            status = 200
            data = b'{"keys": []}'
            headers = {"Cache-Control": "no-store"}

        def _inner(url, **kw):
            calls.append(url)
            return _Resp()

        transport = svc._CachingCertsTransport()
        transport._inner = _inner
        transport("https://certs")
        transport("https://certs")

        assert len(calls) == 2, "a no-store cert response must not be cached"


class TestVerificationOffEventLoop:
    @pytest.mark.asyncio
    async def test_verify_does_not_block_the_event_loop(self):
        """The sync Google call must run in a worker thread, not inline."""
        verifying_thread = {}

        def _slow_verify(token, request, audience=None, **kw):
            import threading

            verifying_thread["name"] = threading.current_thread().name
            return _idinfo("client-1.apps.googleusercontent.com")

        with patch.object(
            svc.settings,
            "GOOGLE_CLIENT_ID",
            "client-1.apps.googleusercontent.com",
        ), patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token",
            side_effect=_slow_verify,
        ):
            # A concurrent tick proves the loop stayed responsive.
            ticks = 0

            async def _tick():
                nonlocal ticks
                for _ in range(3):
                    await asyncio.sleep(0)
                    ticks += 1

            result, _ = await asyncio.gather(
                GoogleOAuthService.verify_google_token("tok"), _tick()
            )

        assert result["email"] == "user@example.com"
        assert ticks == 3
        import threading

        assert verifying_thread["name"] != threading.current_thread().name, (
            "verify_oauth2_token ran on the event-loop thread"
        )
