# Track B — prod-ops: execution progress

Branch `fix/prod-ops` (stacked on `fix/security-criticals`). Commits e707841, d78e0d1.
TDD in the `family_app_backend` container against test_db.

## DONE ✓ (5 of 7)
- **B4 — startup secret validation.** Settings fails fast in prod (DEBUG=false) on an
  unset/placeholder SECRET_KEY. `config.py` model_validator. Tests: test_config_validation.py (4).
- **B3 — real readiness probe.** `/health` is now liveness-only (no false "database:connected");
  new `/ready` pings DB + Redis, returns 503 when degraded. Tests: test_health_readiness.py (3).
- **B2 — single scheduler leader.** Redis leader lock (`app/core/scheduler_lock.py`) gates
  APScheduler + overdue sweep to one worker (was firing once per uvicorn worker). TTL renewal,
  release on shutdown, fail-open without Redis. Tests: test_scheduler_lock.py (2).
- **B6 — PayPal webhook retriability.** Was marking events processed before the state change +
  swallowing failures into 200 → lost events. Now marks only after a successful apply, returns
  503 on failure so PayPal retries. Tests: test_paypal_webhook_resilience.py (2).
- **B1 — auth rate limiting.** slowapi 10/min per-IP on login / register-family / check-methods /
  forgot-password / reset-password. In-memory default (RATE_LIMIT_STORAGE_URI → Redis for
  multi-worker). Tests: test_rate_limiting.py (2). Autouse conftest fixture disables the limiter
  for other tests.

58 passed across combined Track A+B suites; no regressions.

## DEFERRED (specced in 08-trackB-specs.md) — lowest value / highest churn
- **B5 — observability (Sentry + JSON logging).** Opt-in via SENTRY_DSN env + a logging module;
  mostly config, low testability. New deps: sentry-sdk[fastapi], python-json-logger.
- **B7 — PayPal async (requests → httpx).** Blocking `requests` in async handlers; calls are
  infrequent (subscribe/cancel/webhook-verify). Refactor needs the existing paypal test mocks
  rewritten from requests to httpx. Pattern mirrors the A3 receipt fix (timeout + offload).

## Deploy notes
- New dep slowapi==0.1.9 added to requirements.txt (rebuild image).
- For multi-worker prod, set RATE_LIMIT_STORAGE_URI to the Redis URL so the limit window is
  shared across workers (else each worker enforces independently — still bounded).
- B2 leader lock uses REDIS_URL; if Redis is down, jobs fail-open (run everywhere) — acceptable
  for single-instance, revisit if scaling out without Redis.
