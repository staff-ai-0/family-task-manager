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

from app.core.config import settings

_storage_uri = getattr(settings, "RATE_LIMIT_STORAGE_URI", "") or "memory://"

# headers_enabled stays False: injecting X-RateLimit-* headers on a 200 requires
# every route to declare a `response: Response` param. The 429 response from the
# exceeded-handler still carries Retry-After, which is what clients actually need.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
)

# Per-route limits (tweak here). Strings use the `limits` syntax.
AUTH_LIMIT = "10/minute"      # login, register-family, check-methods, password reset
EMAIL_LIMIT = "5/minute"     # verification / resend (extra-cheap to abuse)
AI_LIMIT = "30/hour"         # receipt scan / document scan
