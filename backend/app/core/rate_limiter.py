"""Application rate limiting (slowapi).

Protects unauthenticated auth endpoints (brute force, credential stuffing, email
enumeration) and expensive AI endpoints from abuse. Keyed by client IP.

Storage: in-memory by default (works for single-instance + tests). For a
multi-worker / multi-instance deploy set RATE_LIMIT_STORAGE_URI to the Redis URL
so the window is shared across workers — otherwise each worker enforces the limit
independently (still bounded, just N x looser).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def get_client_ip(request: Request) -> str:
    """Rate-limit key: the real client IP, spoof-resistant behind Cloudflare.

    Prefer ``CF-Connecting-IP``: prod ingress is a Cloudflare Tunnel and the
    CF edge always sets/overwrites this header (a client-supplied value never
    survives the edge), so it is not forgeable through the tunnel. This is
    deliberately NOT ``X-Forwarded-For``: Cloudflare *appends* the real IP to
    the client-supplied XFF list instead of replacing it, so any XFF-derived
    key (including uvicorn's ``--proxy-headers`` rewrite of
    ``request.client.host`` when ``--forwarded-allow-ips`` trusts the chain)
    lets an attacker rotate the leftmost entry and bypass every limit.

    Falls back to ``request.client.host`` (direct access: local dev, tests,
    container-internal calls) via slowapi's own helper.
    """
    cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
    if cf_ip:
        return cf_ip
    return get_remote_address(request)

_storage_uri = getattr(settings, "RATE_LIMIT_STORAGE_URI", "") or "memory://"

# headers_enabled stays False: injecting X-RateLimit-* headers on a 200 requires
# every route to declare a `response: Response` param. The 429 response from the
# exceeded-handler still carries Retry-After, which is what clients actually need.
#
# enabled: rate limiting is a production security control. By default it follows
# DEBUG (off in local dev / E2E where it would only throttle the test runner —
# every test logs in from one IP, tripping AUTH_LIMIT and 429-ing the suite into
# flaky failures; on in prod, DEBUG=false per docker-compose.gcp.yml). Set
# RATE_LIMIT_ENABLED explicitly to decouple from DEBUG (e.g. a staging box that
# runs DEBUG=true but must still enforce limits → RATE_LIMIT_ENABLED=true).
# The pytest suite overrides `limiter.enabled` directly (conftest disables it;
# test_rate_limiting re-enables it), so this initial value is transparent to it.
_rate_limit_enabled = settings.RATE_LIMIT_ENABLED
if _rate_limit_enabled is None:
    _rate_limit_enabled = not settings.DEBUG

limiter = Limiter(
    key_func=get_client_ip,
    storage_uri=_storage_uri,
    enabled=_rate_limit_enabled,
)

# Per-route limits (tweak here). Strings use the `limits` syntax.
AUTH_LIMIT = "10/minute"      # login, register-family, check-methods, password reset
EMAIL_LIMIT = "5/minute"     # verification / resend (extra-cheap to abuse)
AI_LIMIT = "30/hour"         # receipt scan / document scan
