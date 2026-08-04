"""Application rate limiting (slowapi).

Protects unauthenticated auth endpoints (brute force, credential stuffing, email
enumeration) and expensive AI endpoints from abuse. Keyed by client IP.

Storage: in-memory by default (works for single-instance + tests). For a
multi-worker / multi-instance deploy set RATE_LIMIT_STORAGE_URI to the Redis URL
so the window is shared across workers — otherwise each worker enforces the limit
independently (still bounded, just N x looser).
"""
from typing import Any, Optional

from limits import parse as parse_rate_limit
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.wrappers import Limit
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
COUPON_LIMIT = "10/hour"     # coupon redemption attempts

# ---------------------------------------------------------------------------
# Coupon attempts: ONE budget, charged manually at every entry point.
#
# A @limiter.limit decorator scopes its bucket to the decorated endpoint, so
# two routes that both redeem codes get two independent budgets. That was the
# hole: POST /subscriptions/coupons/redeem carried COUPON_LIMIT (10/hour)
# while POST /auth/register-family reached the same CouponService.redeem
# under AUTH_LIMIT alone (10/minute = 600/hour), and answered with
# `coupon_applied` — a 60x-cheaper hit/miss oracle against codes that
# coupon_service's docstring calls "human-chosen and guessable by design".
# A hit is a real Plus/Pro floor (metered LLM spend on the operator's key)
# and permanently burns a max_redemptions seat, since revoke does not return
# it.
#
# Charged from the route body rather than by decorator because only the body
# knows whether a coupon is in play at all: register-family must stay exactly
# as permissive as it is today for the couponless signups that are ~all of
# them, and slowapi's decorator cannot see the parsed request body.
_COUPON_SCOPE = "coupon-attempt"
_COUPON_ATTEMPT_LIMIT = Limit(
    limit=parse_rate_limit(COUPON_LIMIT),
    key_func=get_client_ip,
    scope=_COUPON_SCOPE,
    per_method=False,
    methods=None,
    error_message=None,
    exempt_when=None,
    cost=1,
    override_defaults=True,
)


def charge_coupon_attempt(
    request: Request, *, family_id: Optional[Any] = None
) -> None:
    """Spend one unit of the shared coupon-attempt budget, or raise 429.

    Call this BEFORE doing any coupon work, at every route that can reach
    ``CouponService.redeem`` — including the ones where a coupon is optional,
    in which case call it only on the branch that actually carries a code.

    Charges up to two dimensions of the same limit:

    * the client IP, always. The only key available at signup, where the
      family does not exist yet (a brand-new family_id per attempt would be
      a free bucket every time).
    * ``family_id`` when the caller is authenticated. IP is rotatable — open
      proxies, a phone toggling airplane mode — while the family in the JWT
      is not, so an authenticated attacker cannot refresh the budget by
      moving hosts. Charged as a second bucket rather than as a compound
      ``ip+family`` key, which would have exactly the rotation hole.

    Both buckets are charged before either is judged, so an attempt that
    trips the family limit still counts against the IP.

    No-op when the limiter is disabled (local dev, and the pytest suite via
    conftest) — mirroring the decorator, which skips the whole check on
    ``if self.enabled``.
    """
    if not limiter.enabled:
        return
    keys = [f"ip:{get_client_ip(request)}"]
    if family_id is not None:
        keys.append(f"family:{family_id}")

    exceeded = False
    for key in keys:
        args = [key, _COUPON_SCOPE]
        # The 429 handler reads this to build Retry-After; slowapi's decorator
        # sets it the same way from __evaluate_limits.
        request.state.view_rate_limit = (_COUPON_ATTEMPT_LIMIT.limit, args)
        if not limiter.limiter.hit(_COUPON_ATTEMPT_LIMIT.limit, *args):
            exceeded = True
    if exceeded:
        raise RateLimitExceeded(_COUPON_ATTEMPT_LIMIT)
