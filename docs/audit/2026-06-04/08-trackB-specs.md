# Track B — scoped specs (workflow wefc76sbx)

## B1: Rate Limiting on Auth & AI Endpoints

**Current:** No rate limiting exists on any endpoint. Auth endpoints (login, register-family, check-methods, forgot-password, reset-password, verify-email, resend-verification) at backend/app/api/routes/auth.py:40-352 and AI scan endpoints (scan-receipt at backend/app/api/routes/budget/transactions.py:513-597, scan-document at backend/app/api/routes/calendar.py:189-230, jarvis chat at backend/app/api/routes/jarvis.py:46-87) are all unauthenticated or require_parent_role but have no rate limiting. OAuth endpoints at backend/app/api/routes/oauth.py:28-77 are also unprotected. Middleware setup in backend/app/main.py:121-140 has CORS + SessionMiddleware but no rate limiting. Redis is already configured (backend/app/core/config.py:148) and used for webhook deduping and model settings.

**Fix:** Implement Redis-backed rate limiting via slowapi (FastAPI-native rate limiting library backed by Redis). Recommended approach: 
1. Install slowapi (pip dependency)
2. Create backend/app/core/rate_limiter.py with:
   - RedisLimiter instance using settings.REDIS_URL
   - Factory function to build limiter keys by IP + endpoint path
   - Configurable per-endpoint limits (e.g., 5 reqs/min for auth, 10 reqs/min for AI)
3. Wire limiter into backend/app/main.py:120 via app.state.limiter = limiter + register Limiter.get_response as error handler (429 status)
4. Apply @limiter.limit decorators to auth routes (login, register, register-family, check-methods, forgot-password, reset-password, verify-email, resend-verification), OAuth routes (google, google/verify), and AI scan routes (scan-receipt, scan-document, /jarvis/chat, /jarvis/chat-stream)
5. For per-user rate limiting on authenticated endpoints, override the key_func to use family_id from JWT instead of IP address

Alternative (if slowapi + Redis has issues): use starlette-rate-limit with aioredis directly for finer control.

Limits recommended:
- Public auth (login, register-family, check-methods, forgot-password, reset-password): 10 requests/5 minutes per IP
- Email verification (verify-email, resend-verification): 5 requests/5 minutes per IP
- OAuth (google, google/verify): 10 requests/5 minutes per IP
- AI endpoints (scan-receipt, scan-document): 30 requests/hour per family_id (authenticated)
- Jarvis chat endpoints (chat, chat-stream): 100 requests/day per family_id (per config JARVIS_DAILY_MESSAGE_CAP already exists; add per-minute throttle of 10 msgs/min to prevent rapid spam)

Handler: Return 429 Too Soon with JSON response {"detail": "Rate limit exceeded. Please try again in X seconds.", "retry_after": X}

**Files:** /Volumes/shared/AgentIA/family-task-manager/backend/requirements.txt, /Volumes/shared/AgentIA/family-task-manager/backend/app/main.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/core/config.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/core/rate_limiter.py (NEW), /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/auth.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/oauth.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/budget/transactions.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/calendar.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/jarvis.py, /Volumes/shared/AgentIA/family-task-manager/backend/tests/test_rate_limiting.py (NEW)

**New deps:** slowapi==0.1.9

**Test plan:** RED (fails without rate limiting):
1. test_auth_login_rate_limit: POST /api/auth/login 11x in 5 min; expect 1-10 to succeed (200), 11+ to fail (429)
2. test_register_family_rate_limit: POST /api/auth/register-family 11x in 5 min from same IP; expect 11th+ to fail (429)
3. test_scan_receipt_rate_limit: POST /api/budget/transactions/scan-receipt 31x in 1 hour under same family_id; expect 1-30 to succeed (201/200), 31+ to fail (429)
4. test_jarvis_chat_per_minute_limit: POST /api/jarvis/chat 11x in 1 minute; expect 11+ to fail (429)
5. test_jarvis_daily_cap: POST /api/jarvis/chat 101x over a day (interleaved with sleep); expect 1-100 to succeed, 101 to fail (429 or existing daily cap logic)

GREEN (passes with rate limiting):
1. Same tests verify 429 responses include retry_after header and detail JSON
2. test_rate_limit_key_by_ip: Two IPs calling login simultaneously should each get their own quota
3. test_rate_limit_key_by_family: Two families calling scan-receipt simultaneously should each get their own quota
4. test_rate_limit_window_reset: After 5 min window passes, login quota resets (can make 10 more reqs)

Hard to test: Redis unavailability fallback (would need to mock Redis failure). Recommended: log warning but allow request to proceed (fail open) to avoid outage.

**Risk:** SHARED FILES with other items:
- backend/app/main.py: also touched by B2 (CSRF), B3 (HSTS), B4 (HTTPS redirect). Middleware order matters: add rate limiter BEFORE CORS/session so all paths are protected. Risk: if rate limiter is added after session, it won't rate limit session-free requests (OAuth, public auth).
- backend/app/core/config.py: already has REDIS_URL setting, no conflict.

PRODUCTION RISKS:
1. Redis unavailability: if Redis is down, slowapi will error on key increment. Mitigation: wrap limiter in try-catch that logs and allows request (fail open). Document this trade-off.
2. Distributed deployments: if multiple API instances run, each will check Redis independently (correct behavior), but IP-based rate limiting may be inaccurate if behind a load balancer without X-Forwarded-For header. Mitigation: trust_proxy config or override key_func to extract real IP from X-Forwarded-For.
3. User enumeration on forgot-password: rate limiting per IP helps, but still allows basic enumeration across IPs. Current design already returns same response regardless of email existence (backend/app/api/routes/auth.py:321-329), so rate limiting just adds latency, not privacy.
4. JARVIS_DAILY_MESSAGE_CAP already exists in config: new per-minute rate limiter is additional layer, not conflicting.

DEPENDENCIES:
- slowapi package (PyPI: slowapi 0.1.9+) supports redis:// URLs directly. No incompatibilities with FastAPI 0.109.0 or SQLAlchemy 2.0.25.
- Redis must be accessible at settings.REDIS_URL (already required for other features). No extra infrastructure needed.

**Config/env:** No new env vars needed. Existing REDIS_URL in backend/app/core/config.py:148 is reused. Optional config additions to settings:
- RATE_LIMIT_ENABLED: bool = True (default) — kill switch for rate limiting
- RATE_LIMIT_AUTH_PER_MINUTE: int = 10 (for "10 per 5 min" convert to per-minute: ~2)
- RATE_LIMIT_AI_PER_HOUR: int = 30
- RATE_LIMIT_JARVIS_PER_MINUTE: int = 10

Alternatively, hardcode limits in backend/app/core/rate_limiter.py as module constants with comments for easy tweaking.

If Redis is unavailable (local dev without Redis), slowapi can fall back to in-memory storage (memory://) but this won't work across multiple processes. Recommend: in dev, set REDIS_URL="" to use memory storage; tests mock Redis via conftest.py.


---

## B2: APScheduler jobs + overdue-sweep run in EVERY uvicorn worker

**Current:** backend/app/main.py lines 81-96: AsyncIOScheduler initialized in lifespan startup, which runs in every uvicorn worker process. Four jobs scheduled: subscription_sweep (3:00 UTC daily), pet_decay_sweep (8:00 UTC daily), pup_snapshot_sweep (23:30 UTC daily), jarvis_sched_sweep (every 5 mins). Additionally, _overdue_sweep_loop() (lines 31-45) fires every 60 minutes via asyncio.create_task(). docker-compose.gcp.yml line 102 specifies --workers 2, so all 4 jobs + overdue_sweep execute 2x simultaneously. Subscription_sweep is a separate async function (backend/app/jobs/subscription_sweep.py) that downgrades expired subs, but Jarvis/pet/PUP snapshots are inline lambdas. No distributed locking present; Redis is available (config.py line 148 REDIS_URL) and used for FX caching (fx_service.py) but not leveraged for job coordination.

**Fix:** Implement single-runner gate using Redis SETNX-based distributed lock to ensure scheduler and overdue_sweep run only once per cluster. Create app/core/scheduler_lock.py with RedisLeaderLock class using redis.asyncio. Modify lifespan() in main.py to: (1) Acquire leader lock on startup with TTL=120s and periodic renewal; (2) Initialize scheduler/overdue_sweep only if lock acquired; (3) Release lock on shutdown. Lock key: "ftm:scheduler:leader" (settable via env). Non-leader workers log that they skipped job init. Add SCHEDULER_LOCK_ENABLED env var (default True) to allow opt-out. For overdue_sweep specifically, wrap the loop check in the same lock context. Alternative: split scheduler into dedicated sidecar process (set env flag SKIP_SCHEDULER=True for worker processes).

**Files:** backend/app/core/scheduler_lock.py, backend/app/main.py, backend/app/core/config.py, docker-compose.gcp.yml, .env.gcp.example

**New deps:** 

**Test plan:** RED (unit): Mock Redis client, verify SETNX succeeds only for one concurrent lock attempt; verify TTL set; verify non-leader path skips scheduler init. GREEN: Acquire lock, confirm scheduler/overdue_sweep started; release lock, confirm tasks cleaned up. Concurrency: Simulate 2+ uvicorn workers starting simultaneously—only one should acquire lock, others log skip. TTL renewal: Mock time passage, verify lock renewed before TTL expiry. Integration (manual): docker-compose up with --workers 3, inspect logs for "[LEADER]" vs "[FOLLOWER]" messages; verify cron jobs fire once per interval not 3x. Hard parts: timing the TTL renewal test without blocking; ensuring Redis connection reuse (use fx_service.py pattern).

**Risk:** CONFLICTS: B1 (startup routines) and B7 (Redis connection) both touch config.py + require working Redis. If Redis is down on startup, lock acquisition fails and scheduler doesn't run—need graceful fallback (log warning, continue without scheduler, or raise only if SCHEDULER_LOCK_ENABLED=True). APScheduler holds references to jobs in memory—if lock holder dies abruptly, jobs orphan until TTL expires (120s is reasonable). Existing code paths that call TaskAssignmentService.mark_overdue_all() directly (e.g. /api/task-assignments/check-overdue endpoint) are unaffected; distributed lock only gates the periodic background sweep. No other code besides main.py touches scheduler, so risk of unintended side-effects is low. Prod: confirm REDIS_URL + Redis health on startup; test lock failure scenarios (Redis down, network partition).

**Config/env:** SCHEDULER_LOCK_ENABLED=True (default) — set False to disable lock and run scheduler in every worker (unsafe but useful for single-worker dev). SCHEDULER_LOCK_KEY="ftm:scheduler:leader" — Redis key name. SCHEDULER_LOCK_TTL=120 — lock hold time in seconds; renewal happens every TTL/2. Falls back to no-lock behavior if Redis unavailable and SCHEDULER_LOCK_ENABLED=False.


---

## B3: Health check endpoints (/health + /ready) with actual DB/Redis pings

**Current:** backend/app/main.py:202-205 — the /health endpoint returns a static dict without touching any infrastructure:
```python
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "database": "connected", "version": "1.0.0"}
```

This hardcoded response violates liveness vs readiness semantics:
- Kubernetes expects /health (liveness probe) to fail only if the process should be restarted (DB unreachable is NOT a restart reason)
- Kubernetes expects /ready (readiness probe) to fail if the service cannot handle requests (DB unreachable = unready)
- Currently both return "healthy" regardless of actual DB/Redis connectivity

**Fix:** Create two endpoints in backend/app/main.py:

1. **GET /health** (liveness) — fast, returns 200 if process is running. Logs only startup/fatal errors. DB/Redis unavailable does NOT cause 503.
   ```python
   @app.get("/health")
   async def health_check():
       """Liveness probe: returns 200 if process is alive."""
       return {"status": "alive", "version": "1.0.0"}
   ```

2. **GET /ready** (readiness) — actually pings DB + Redis, returns 503 if either fails. This is the health check the app depends on for traffic/scheduling decisions.
   ```python
   @app.get("/ready")
   async def readiness_check():
       """Readiness probe: returns 200 only if all critical services are responding."""
       checks = {}
       status_code = 200
       
       # Ping database with SELECT 1
       try:
           async with AsyncSessionLocal() as session:
               await session.execute(text("SELECT 1"))
               checks["database"] = "connected"
       except Exception as e:
           checks["database"] = f"error: {type(e).__name__}"
           status_code = 503
       
       # Ping Redis (requires singleton in app.core.redis)
       try:
           redis = await get_redis_client()
           await redis.ping()
           checks["redis"] = "connected"
       except Exception as e:
           checks["redis"] = f"error: {type(e).__name__}"
           status_code = 503
       
       response_dict = {"status": "ready" if status_code == 200 else "degraded", "checks": checks, "version": "1.0.0"}
       
       if status_code != 200:
           raise HTTPException(status_code=status_code, detail=response_dict)
       return response_dict
   ```

Support code needed:
- **backend/app/core/redis.py** (new file): Redis client singleton + get_redis_client() factory matching fx_service.py pattern (handles event loop rebinding for tests)
- **backend/app/main.py imports**: Add `from sqlalchemy import text` and `from fastapi import HTTPException`
- Update existing /health if called by external monitoring (fallback to /ready-style logic with timeout=2s on DB ping)

**Files:** /Volumes/shared/AgentIA/family-task-manager/backend/app/main.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/core/redis.py

**New deps:** 

**Test plan:** **RED test** (test_health_endpoints.py):
1. `/health` always returns 200 + "alive" status
2. `/ready` returns 200 + "connected" when DB/Redis are up
3. `/ready` returns 503 when DB query fails (mock engine.execute to raise)
4. `/ready` returns 503 when Redis.ping() fails (mock redis client to raise)
5. `/ready` returns degraded checks dict with error messages
6. Response times: /health <10ms (no I/O), /ready <200ms (with DB ping)

**Implementation note**: Use `unittest.mock.AsyncMock` + `@pytest.mark.asyncio` + fixtures from conftest.py (client: AsyncClient). Mock SQLAlchemy's `execute()` at the service layer, not the connection pool.

**Hard to test**: Redis singleton's event-loop rebinding requires pytest's function-scoped loop — test in isolation (fx_service.py already has a parallel pattern to verify against).

**Integration test** (optional): Start Docker containers for postgres + redis, hit /ready, verify both connected; kill postgres, hit /ready, verify 503 + error msg.

**Risk:** **Production risk**: 
- If /ready endpoint is slow (DB timeout), load balancers may take 30s to mark unhealthy. Add configurable timeout (default 5s) via settings.HEALTH_CHECK_TIMEOUT.
- Redis optional per config comment (REDIS_URL may point nowhere in dev) — /ready should only require Redis if explicitly configured (or gracefully degrade if Redis is optional).
- Breaking change for external monitoring: if GCP/k8s health checks currently call /health, they must be updated to /ready. Recommend keeping /health as-is for backward compatibility, add /ready as new.

**Shared files conflict**: backend/app/main.py touched by B1 (root endpoint), B3 (health), and possibly B5 (metrics). Coordinate with other B-items using same file. frontend/app/main.py is NOT touched (this is backend only).

**Dependencies**: Requires `sqlalchemy.text` (already in engine module), `redis.asyncio` (already imported in fx_service, subscriptions_webhook). No new pip packages.

**Config/env:** Optional settings in backend/app/core/config.py:
```python
HEALTH_CHECK_DB_TIMEOUT: float = 5.0  # seconds for SELECT 1 query
HEALTH_CHECK_REDIS_TIMEOUT: float = 2.0  # seconds for PING
REDIS_OPTIONAL: bool = False  # if True, /ready doesn't fail on Redis error
```

Production .env should set HEALTH_CHECK_DB_TIMEOUT=5 (k8s probes timeout at 10s, needs margin for retry).


---

## B4: No startup validation of critical secrets — app boots with default/placeholder SECRET_KEY (forgeable JWTs)

**Current:** backend/app/core/config.py:28 defines SECRET_KEY with a placeholder default: `SECRET_KEY: str = "your-secret-key-change-this-in-production"`. No validators exist; the Settings object instantiates (line 200) without checking if SECRET_KEY is still the default or if critical env vars (DATABASE_URL, PAYPAL_CLIENT_ID, etc.) are empty/missing in production. The app starts normally and uses this forgeable key in JWT token signing (backend/app/core/security.py:41, line 49) and session middleware (backend/app/main.py:135). Currently, only DEBUG mode is defined (config.py:19, defaults to True); there is no ENVIRONMENT or PROD flag to trigger strict validation.

**Fix:** Add a model_validator to Settings (pydantic v2 pattern) that detects production mode (via a new ENV or ENVIRONMENT variable, or by checking DEBUG=False) and raises a clear validation error if SECRET_KEY is the placeholder, DATABASE_URL is default/missing, or other critical secrets (PAYPAL_CLIENT_ID, ANTHROPIC_API_KEY, LITELLM_API_KEY where applicable) are empty. The validator should run at model instantiation (before settings = Settings() on line 200 completes) so the app fails immediately on boot with a helpful message listing which secrets are misconfigured. Pattern: use @model_validator(mode='after') to inspect self.DEBUG or os.environ.get('ENVIRONMENT') == 'production' and raise ValueError with a detailed message.

**Files:** /Volumes/shared/AgentIA/family-task-manager/backend/app/core/config.py

**New deps:** 

**Test plan:** RED test: instantiate Settings with ENVIRONMENT=production and SECRET_KEY at its default, expect ValidationError with message naming 'SECRET_KEY'. Verify DATABASE_URL='' (empty) also triggers the error in prod. GREEN test: instantiate Settings with ENVIRONMENT=production, SECRET_KEY='custom-prod-key-...', DATABASE_URL='postgresql://...', expect success. Verify dev (ENVIRONMENT=development or DEBUG=True) does NOT validate (allows placeholder). This is unit-testable by creating settings with monkeypatched os.environ; reference backend/tests/test_vault_bootstrap.py (line 114-142) as a pattern for env mocking.

**Risk:** config.py is shared with B1 (rate limiting), B3 (health check), B5 (logging/Sentry), B6 (PayPal webhook), B7 (httpx async) — these items may add ENV/DEBUG/mode detection or validators. **Conflict mitigation:** (1) use a distinct ENVIRONMENT env var (not DEBUG, which may be touched by others) so validators don't interfere; (2) keep the validator focused on ONLY secret-checking (don't validate other settings like ALLOWED_ORIGINS/GOOGLE_CLIENT_IDS which have existing validators); (3) document the validator's purpose in a comment so sibling changes don't accidentally remove/weaken it. Startup will be slightly slower (~microseconds for one model_validator call) but only once at boot.

**Config/env:** Add ENVIRONMENT env var (default='development'). In production, set ENVIRONMENT=production. Alternatively, can infer from DEBUG=False, but using explicit ENVIRONMENT is clearer. No new .env entries needed — existing .env in dev has all defaults; prod will provide real SECRET_KEY, DATABASE_URL, etc. before boot.


---

## B5: No error tracking (Sentry) and no structured/JSON logging

**Current:** backend/app/main.py (lines 24-28): uses standard `logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")` — produces plain-text logs only. backend/app/core/config.py (line 174): declares `LOG_LEVEL: str = "INFO"` but main.py hardcodes `logging.INFO` with no reference to `settings.LOG_LEVEL`. backend/app/core/exception_handlers.py (lines 102-110): registers handlers for only 7 domain exceptions; no catch-all `@app.exception_handler(Exception)` exists, so unhandled errors return bare Starlette 500 with no context capture. backend/requirements.txt: no sentry-sdk, structlog, or python-json-logger. .env.gcp.example (line 12): sets LOG_LEVEL=INFO as a placeholder with no enforcement. No request-id / access-log middleware. No Sentry DSN configuration or initialization.

**Fix:** 1. **Add dependencies to backend/requirements.txt**: Add `sentry-sdk[fastapi]==2.22.0` and `python-json-logger==3.2.0` (or structlog==24.4.0 if structlog preferred; python-json-logger is simpler for drop-in replacement).

2. **Create backend/app/core/logging.py** — new logging configuration module:
   - Function `setup_logging(level: str, is_json: bool) -> None` that reconfigures Python's root logger
   - When `is_json=True`, attach a JSON formatter (`pythonjsonlogger.jsonlogger.JsonFormatter`) that emits `{"timestamp", "level", "logger", "message", "exc_info", ...}`
   - When `is_json=False`, use plain-text (default)
   - Respects `settings.LOG_LEVEL` (from env or config.py default)
   - Initialize root logger + FastAPI logger (name="uvicorn.*")

3. **Modify backend/app/main.py**:
   - Replace lines 24-28 logging.basicConfig with: `from app.core.logging import setup_logging; setup_logging(settings.LOG_LEVEL, is_json=settings.JSON_LOGGING_ENABLED)` (call after settings imported, before app creation)
   - Add Sentry initialization after logging setup (if `settings.SENTRY_DSN`):
     ```python
     import sentry_sdk
     from sentry_sdk.integrations.fastapi import FastApiIntegration
     from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
     
     if settings.SENTRY_DSN:
         sentry_sdk.init(
             dsn=settings.SENTRY_DSN,
             integrations=[
                 FastApiIntegration(),
                 SqlalchemyIntegration(),
             ],
             environment=settings.ENVIRONMENT,
             debug=settings.DEBUG,
             traces_sample_rate=0.1 if not settings.DEBUG else 1.0,
         )
         logger.info("Sentry initialized with DSN %s", settings.SENTRY_DSN[:20] + "...")
     ```
   - Add catch-all exception handler at end (before `if __name__ == "__main__"`):
     ```python
     @app.exception_handler(Exception)
     async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
         logger.exception("Unhandled exception in %s %s", request.method, request.url.path)
         return JSONResponse(
             status_code=500,
             content={"error": "internal_server_error", "message": "An unexpected error occurred"}
         )
     ```

4. **Add config.py settings** (backend/app/core/config.py):
   - `SENTRY_DSN: str = ""` (optional, no-op if empty)
   - `ENVIRONMENT: str = "development"` (for Sentry environment tag; also used in sentry_sdk.init)
   - `JSON_LOGGING_ENABLED: bool = False` (opt-in, default off for local dev; set via env `JSON_LOGGING_ENABLED=true` in prod)

5. **Update .env.gcp.example**:
   - Add lines after `LOG_LEVEL=INFO`:
     ```
     JSON_LOGGING_ENABLED=true
     SENTRY_DSN=https://your-sentry-key@sentry.io/your-project-id
     ENVIRONMENT=production
     ```
   - Update ENVIRONMENT placeholder to match current deploy env

6. **Light test**: backend/tests/test_logging.py or conftest.py addition:
   - Assert `settings.SENTRY_DSN` can be set/unset without crashing app startup
   - Assert logger is configured (check `logging.root.handlers` has a handler)
   - Assert JSON output when enabled: `JSON_LOGGING_ENABLED=true` → logger emits valid JSON lines
   - Optional: mock Sentry and assert `sentry_sdk.init` is called when DSN is set

**Files:** backend/app/main.py, backend/app/core/config.py, backend/app/core/logging.py, backend/requirements.txt, .env.gcp.example

**New deps:** 

**Test plan:** 
**RED tests (before implementation):**
1. `test_sentry_init_guarded_on_dsn`: Run app startup with and without SENTRY_DSN env set; verify no error either way
2. `test_json_logging_enabled`: Set JSON_LOGGING_ENABLED=true, capture logger output, assert it's valid JSON with keys: timestamp, level, message, logger
3. `test_plaintext_logging_default`: Run app with JSON_LOGGING_ENABLED unset (default false), capture logger output, assert it's plain-text format (not JSON)
4. `test_log_level_respected`: Set LOG_LEVEL=DEBUG via env, assert logger.getEffectiveLevel() == logging.DEBUG (not hardcoded INFO)
5. `test_unhandled_exception_caught`: Mock a route that raises uncaught Exception, assert (a) status_code=500, (b) response JSON has keys "error" and "message", (c) exception is logged with logger.exception()

**GREEN proofs (after implementation):**
- All 5 tests pass
- Manual: `SENTRY_DSN="" python -m pytest ...` → app boots, no errors
- Manual: `JSON_LOGGING_ENABLED=true python -m pytest ...` → logs contain `{"timestamp": "...", "level": "INFO", "message": ...}`
- Manual: Unhandled route error (e.g., `1/0`) returns 500 with `{"error": "internal_server_error", ...}` and is captured in sentry.log if DSN set
- Manual: config.py Settings() can be instantiated with `SENTRY_DSN=""` (no-op), `SENTRY_DSN="https://..."` (valid DSN), and any LOG_LEVEL (DEBUG, INFO, WARNING, ERROR)

**Testing difficulty**: Sentry mocking is straightforward (mock `sentry_sdk.init`). JSON logger validation requires capturing stderr/stdout or monkeypatching handlers. Logger level checking is simple (read logging.root.getEffectiveLevel()). Overall: Easy to medium.


**Risk:** 
**Prod risk**: LOW. Both Sentry and JSON logging are completely opt-in via environment variables (SENTRY_DSN empty by default, JSON_LOGGING_ENABLED=false by default). Local dev unaffected. No breaking changes to existing exception handlers (new catch-all is a supplement). JSON formatter is a pure logging-layer change, doesn't affect API contracts or database. Sentry library integrations (FastApiIntegration, SqlalchemyIntegration) are passive observers, zero side effects.

**File conflicts with sibling items**:
- **backend/app/main.py** (lines 1-30): Item B5 modifies logging setup. No other items in Track B touch main.py lines 1-30 per the audit. Item A1 (security fix) also touches main.py but at line 147 (StaticFiles mount) and context is separate.
- **backend/app/core/config.py**: Item B5 adds 3 new settings (SENTRY_DSN, ENVIRONMENT, JSON_LOGGING_ENABLED). Item B6 (hardcoded SECRET_KEY validation) also touches config.py. Item B7 (LOG_LEVEL env not used) also touches config.py. No overlaps if B6/B7 handle their own settings additions without duplicating these 3.
- **backend/requirements.txt**: Item B5 adds 2 packages (sentry-sdk[fastapi], python-json-logger). Item B1 (remove aioredis) also touches requirements. Item B2 (split requirements-dev.txt) also touches requirements. No conflicts if each item adds/removes its own lines without duplicating.

**Integration notes**: If B6 adds validation for SECRET_KEY, B5's ENVIRONMENT setting will coexist naturally (both simple string fields). If B7 fixes LOG_LEVEL usage, B5's `setup_logging(settings.LOG_LEVEL, ...)` call will work correctly. If B2 creates requirements-dev.txt, sentry-sdk + python-json-logger stay in prod requirements.txt (both are runtime deps, not dev-only).
</risk>
<parameter name="config_or_env">
**New environment variables** (add to .env.gcp.example and prod Vault):
- `SENTRY_DSN=""` (empty by default, opt-in via Vault / deploy .env)
- `ENVIRONMENT="development"` (local) or `"production"` (GCP). Sent as Sentry context tag. Replaces any hardcoded env strings.
- `JSON_LOGGING_ENABLED=false` (default) or `true` (GCP). When true, all logs emit as JSON lines for GCP Cloud Logging to parse and index.

**Config.py changes** (add to Settings class, lines ~173-176):
```python
SENTRY_DSN: str = ""  # optional; no-op if empty
ENVIRONMENT: str = "development"  # "production" in GCP
JSON_LOGGING_ENABLED: bool = False  # opt-in per env
```

**Impact on .env.gcp.example**:
- Add post-LOG_LEVEL block (after line 12):
  ```
  JSON_LOGGING_ENABLED=true
  SENTRY_DSN=https://your-sentry-key@sentry.io/your-project-id
  ENVIRONMENT=production
  ```
  - Deployer must fill in real SENTRY_DSN from Sentry.io project setup (or leave empty if not using Sentry yet)

**No changes to existing local .env** (logging defaults to plaintext + no Sentry, development mode). Backward-compatible.
</config_or_env>
<parameter name="new_deps">
["sentry-sdk[fastapi]==2.22.0", "python-json-logger==3.2.0"]


**Config/env:** 


---

## B6: PayPal webhook drops subscription state-change events permanently on transient DB failure

**Current:** backend/app/api/routes/subscriptions_webhook.py:receive_webhook() marks event as processed in Redis BEFORE the subscription state change commits to the database:

1. Line 102: `proceed = await _dedupe_event(event_id)` — Redis SET with NX flag succeeds, event marked processed
2. Lines 112-131: `apply_activated/cancelled/payment_failed(db, ...)` called
3. Each apply_* function in backend/app/services/subscription_state.py (lines 50, 67, 84) calls `await db.commit()` within their own session
4. If any exception occurs during apply_* (network timeout, DB constraint violation, connection pool exhaustion), the exception is caught at line 134-135
5. Handler returns 200 anyway (line 137), triggering get_db() finally block which executes rollback()
6. Result: Redis key exists (event marked processed), but subscription state change was rolled back — event lost forever because PayPal won't retry (thinks it's processed) and DB never committed the change

**Fix:** Reorder the dedupe and state-change commit to ensure atomicity and returnability:

CHANGE: Move dedupe check AFTER successful state change, and return 5xx on any apply_* failure so PayPal retries:

In backend/app/api/routes/subscriptions_webhook.py:receive_webhook():
  1. Keep signature verification (lines 84-98)
  2. REMOVE early _dedupe_event call (currently lines 101-105)
  3. Try apply_activated/cancelled/payment_failed (lines 112-131)
  4. On SUCCESS: THEN mark event in Redis (dedupe after commit)
  5. On FAILURE: Return 500 (not 200) so PayPal retries — do NOT catch exception or return 200

LOGIC:
  - Try apply_* function which internally calls db.commit()
  - If commit succeeds, ONLY THEN check/mark Redis dedupe
  - If anything fails (apply_*, or Redis dedupe after successful DB commit), return 5xx
  - PayPal's retry logic handles transient failures by re-sending
  - apply_* functions already implement idempotency (check state before mutating)

CODE STRUCTURE:
```python
# Verify signature (keep as-is, lines 84-98)

# REMOVE lines 101-105 (early dedupe check)

# Dispatch event handler
try:
    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        # ... extract period_end (lines 113-120)
        await apply_activated(...)
    elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
        await apply_cancelled(...)
    elif event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
        await apply_payment_failed(...)
    else:
        logger.info("Ignoring webhook event_type %s", event_type)
        return {"received": True}
    
    # State change committed. NOW mark event processed.
    if event_id:
        try:
            await _mark_event_processed(event_id)  # Mark AFTER state commit
        except Exception as e:
            logger.error("Failed to mark event processed (will retry): %s", e)
            # Still return 5xx so PayPal retries; idempotent apply_* already happened
            raise
    
    return {"received": True}
    
except Exception as e:
    logger.exception("Webhook dispatch failed for %s: %s", event_id, e)
    # Return 500 to trigger PayPal retry — event not marked processed
    raise HTTPException(status_code=500, detail="Event processing failed")
```

Introduce new helper:
```python
async def _mark_event_processed(event_id: str) -> None:
    """Mark event as processed in Redis. Raises on failure (caller decides 5xx response)."""
    import redis.asyncio as aioredis
    
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        result = await client.set(
            f"paypal:event:{event_id}",
            "1",
            ex=EVENT_TTL_SECONDS,
            nx=True,
        )
        if not result:
            # Duplicate event (already processed)
            logger.info("Event %s already processed", event_id)
    finally:
        await client.close()
```

Delete _dedupe_event helper entirely (no longer used).

**Files:** backend/app/api/routes/subscriptions_webhook.py

**New deps:** 

**Test plan:** TDD Red-Green approach:

RED TEST 1: Simulate DB failure during apply_* (e.g., connection pool exhaustion, constraint violation)
  - Mock apply_cancelled to raise IntegrityError mid-handler
  - POST webhook event
  - Assert: HTTP 500 returned (not 200)
  - Assert: Event NOT marked in Redis (dedupe check returns False on next attempt)
  - Assert: Subscription state unchanged in DB (rolled back)
  - Assertion: Event is retriable — next POST with same event_id will attempt again

RED TEST 2: Simulate Redis failure AFTER successful DB commit
  - Mock apply_activated to succeed
  - Mock _mark_event_processed to raise ConnectionError
  - POST webhook event
  - Assert: HTTP 500 returned
  - Assert: Subscription state IS changed in DB (commit happened before Redis call)
  - Assert: Event NOT in Redis (mark failed)
  - Assertion: On retry, apply_activated is called again but idempotent (sees status already "active", returns early)
  - Assertion: Redis mark succeeds on second retry

RED TEST 3: Normal success path
  - Mock apply_cancelled to succeed
  - POST webhook event  
  - Assert: HTTP 200 returned
  - Assert: Subscription state changed (cancel_at_period_end=True)
  - Assert: Event marked in Redis

RED TEST 4: Duplicate event (already processed)
  - POST webhook event and get 200 (event marked in Redis)
  - POST same webhook event again
  - Assert: apply_* is NOT called second time (early return after Redis check shows already processed)
  - Assert: HTTP 200 returned (idempotent client perspective)
  - Assert: Subscription state reflects only one application

Testing approach:
  - Use pytest with async fixtures
  - Mock Redis client with aioredis.from_url patch
  - Mock PayPalService.verify_webhook_signature = True
  - Mock apply_* functions or wrap them with side-effect injection
  - Use db_session.refresh(subscription) to check DB state
  - Check Redis state via mock or real Redis test instance

Hardest part: Simulating mid-transaction failures without actually breaking the transaction. Solution: Create wrapper apply_* that injects failure at specific points (after finding subscription, after updating state, before commit).

Unit test file: backend/tests/test_paypal_webhook.py (already exists, add new test cases)

**Risk:** CONFLICTS WITH TRACK B SIBLINGS:
  - B1 (Firebase Cloud Tasks integration): May modify webhook exception handling or routing — ensure exception handler change doesn't conflict with Task Queue retry semantics
  - B2 (Family config multi-tenant scoping): May add family_id lookup in subscription routes — ensure apply_* functions still work with correct scoping
  - B3 (Payment method tokenization): May modify subscription state transitions — ensure apply_* idempotency assumptions hold with new fields
  - B4-B5: Don't directly conflict but share webhook/subscription codebase

PROD RISK:
  - Returning 500 on transient DB failures will trigger PayPal retry for 24h — acceptable because apply_* functions are idempotent
  - Short window where Redis mark fails but DB committed: acceptable, next retry marks event
  - If Redis dedupe never succeeds (Redis down permanently), events reprocess: acceptable (idempotent), but watch logs for Redis failures
  - Event may be processed 2x if: (1) DB commits, (2) Redis mark fails, (3) get_db() rollback is somehow partial — very unlikely with async transactions
  
TESTING RISK:
  - Hard to simulate true transactional failure without actually breaking DB
  - Solution: Mock apply_* with side-effect injection or use pytest-mock to raise exception at specific call count
  - Redis tests may need real Redis instance or solid mock — use fakeredis or mock aioredis.from_url
  
DATA INTEGRITY:
  - Idempotency assumptions: Each apply_* (activated, cancelled, payment_failed) must be idempotent
    - apply_activated: checks `if sub.status == "active": return sub` (line 40) ✓
    - apply_cancelled: checks `if sub.cancel_at_period_end: return sub` (line 62) ✓
    - apply_payment_failed: checks `if sub.status == "payment_failed": return sub` (line 79) ✓
  - All three are safe to reapply — no risk of data corruption on duplicate

**Config/env:** 


---

## ITEM B7: PayPal API calls use blocking 'requests' inside async route handlers

**Current:** backend/app/services/paypal_service.py lines 52-97: _PayPalV2HTTP class uses synchronous requests.post() at line 52 for OAuth token, requests.get() at line 66 for subscription fetch, requests.post() at line 80 for API operations (all with 15s timeouts). Called from async routes: /api/subscriptions/checkout (subscriptions.py:158 calls create_subscription), /api/subscriptions/activate (subscriptions.py:253 calls execute_subscription), /api/subscriptions/cancel (subscriptions.py:315 calls cancel_subscription), /api/subscriptions/webhook (subscriptions_webhook.py:84 calls verify_webhook_signature). Event loop blocks during PayPal latency.

**Fix:** Convert _PayPalV2HTTP to async: (1) Replace 'import requests' with 'import httpx', (2) Create module-level AsyncClient instance with timeout=15s, (3) Convert _auth() to async _auth_async() using 'await client.post(...)' for OAuth token, (4) Convert get() to async get_async() using 'await client.get(...)', (5) Convert post() to async post_async() using 'await client.post(...)'. Update method signatures: create_subscription, execute_subscription, get_subscription, cancel_subscription, verify_webhook_signature all become async. Add 'await' at 4 caller sites: subscriptions.py lines 158, 253, 315 and subscriptions_webhook.py line 84.

**Files:** /Volumes/shared/AgentIA/family-task-manager/backend/app/services/paypal_service.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/subscriptions.py, /Volumes/shared/AgentIA/family-task-manager/backend/app/api/routes/subscriptions_webhook.py, /Volumes/shared/AgentIA/family-task-manager/backend/tests/test_paypal_service_extras.py, /Volumes/shared/AgentIA/family-task-manager/backend/tests/test_paypal_webhook.py

**New deps:** 

**Test plan:** RED test: Call /api/subscriptions/checkout endpoint and verify requests library is not on call stack (event loop not blocked). GREEN tests: (1) Mock httpx.AsyncClient using unittest.mock.AsyncMock, (2) Test _PayPalV2HTTP.get_async() with mocked response returns correct subscription data, (3) Test _PayPalV2HTTP.post_async() with mocked response returns correct result, (4) Test PayPalService.create_subscription() awaits and returns approval_url, (5) Test PayPalService.execute_subscription() awaits and returns status, (6) Test PayPalService.cancel_subscription() awaits and returns cancelled status, (7) Test PayPalService.verify_webhook_signature() awaits and returns True/False. (8) Test /checkout route completes without blocking, (9) Test /activate route completes without blocking, (10) Test /cancel route completes without blocking, (11) Test /webhook route deduplicates and processes events without blocking. Update existing mocks in test_paypal_service_extras.py:22-53 and test_paypal_webhook.py:30-40 from patch(return_value=...) to AsyncMock(return_value=...) pattern. Verify existing JSON fixtures still load.

**Risk:** Token caching race condition if AsyncClient is not properly managed - mitigate with single module-level instance or asyncio.Lock. httpx 0.26.0 already in requirements.txt, no new deps. No config/env changes needed. Conflicts with B4 (Redis async refactoring) minimal - B7 only touches PayPal service, no shared files. Test compatibility risk: existing mocks use unittest.mock.patch with return_value, must convert to AsyncMock (similar pattern as A3 receipt fix). Prod benefit: eliminates event loop blocking on 4 high-traffic routes, improves concurrent user handling during PayPal checkout/activation. Webhook verification stays consistent. Timeout values (15s) preserved.

**Config/env:** 


---
