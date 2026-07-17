import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.core.exception_handlers import register_exception_handlers
from app.core.request_context import RequestIDLogFilter, RequestIDMiddleware
from app.api.routes import auth, users, rewards, consequences, families, task_templates, task_assignments, oauth, cash, invitations, subscriptions, push, shopping, calendar, notifications, kiosk, pet, analytics, jarvis, meals, family_chat, jarvis_schedules, dm, bank, family_cup, referrals, routines
from app.api.routes.budget import router as budget_router
from app.api.routes.gigs import router as gigs_router
from app.api.routes import oversight, onboarding
from app.jobs.subscription_sweep import run_sweep
from app.services.task_assignment_service import TaskAssignmentService
from app.services.consequence_service import ConsequenceService
from app.services.pet_service import PetService
from app.services.analytics_service import AnalyticsService
from app.services.jarvis_schedule_service import JarvisScheduleService

# Configure logging — level driven by LOG_LEVEL env var (default "INFO").
# %(request_id)s is injected by RequestIDLogFilter (contextvar-backed), so
# every record — app or library — correlates to a request ("-" outside one).
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - [rid=%(request_id)s] %(message)s",
)
for _root_handler in logging.getLogger().handlers:
    _root_handler.addFilter(RequestIDLogFilter())
logger = logging.getLogger(__name__)

# Error monitoring — activates only when SENTRY_DSN is set in .env
if settings.SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        environment="production" if not settings.DEBUG else "development",
    )


async def _overdue_sweep_loop() -> None:
    """Background loop: every 60 minutes, mark stale PENDING assignments OVERDUE."""
    # Run once on startup so a fresh boot catches anything missed during downtime.
    await asyncio.sleep(30)
    while True:
        try:
            async with AsyncSessionLocal() as session:
                flipped = await TaskAssignmentService.mark_overdue_all(session)
                if flipped:
                    logger.info("Overdue sweep flipped %d assignment(s)", flipped)
                # Interval recurrence (W4.2): spawn 'every N days since last
                # completion' assignments that are now due.
                spawned = await TaskAssignmentService.spawn_interval_assignments(session)
                if spawned:
                    logger.info("Interval sweep spawned %d assignment(s)", spawned)
                resolved = await ConsequenceService.check_expired_all(session)
                if resolved:
                    logger.info("Consequence sweep auto-resolved %d", resolved)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Overdue sweep failed")
        await asyncio.sleep(60 * 60)  # 1 hour


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    from app.core.scheduler_lock import (
        try_acquire_scheduler_leadership,
        renew_scheduler_leadership,
        release_scheduler_leadership,
    )

    # Startup
    logger.info("Starting Family Task Manager API...")
    logger.info(
        f"Database URL: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'Not configured'}"
    )

    # Elect a single scheduler leader so cron jobs + the overdue sweep run on
    # exactly one worker (prod runs multiple uvicorn workers).
    is_leader, leader_client, leader_token = await try_acquire_scheduler_leadership(settings.REDIS_URL)

    overdue_task = None
    scheduler = None
    renew_task = None

    if not is_leader:
        logger.info("Not the scheduler leader — skipping cron + overdue sweep in this worker.")
    else:
        logger.info("Scheduler leader — starting cron jobs + overdue sweep.")
        overdue_task = asyncio.create_task(_overdue_sweep_loop())

        async def _pet_decay_sweep():
            async with AsyncSessionLocal() as session:
                try:
                    n = await PetService.sweep_decay_all(session)
                    if n:
                        logger.info("Pet decay sweep notified %d owner(s)", n)
                except Exception:
                    logger.exception("Pet decay sweep failed")

        async def _pup_snapshot_sweep():
            async with AsyncSessionLocal() as session:
                try:
                    n = await AnalyticsService.write_all_snapshots(session)
                    if n:
                        logger.info("PUP snapshot wrote %d family rows", n)
                except Exception:
                    logger.exception("PUP snapshot sweep failed")

        async def _jarvis_schedule_sweep():
            async with AsyncSessionLocal() as session:
                try:
                    n = await JarvisScheduleService.sweep_due(session)
                    if n:
                        logger.info("Jarvis schedule sweep fired %d", n)
                except Exception:
                    logger.exception("Jarvis schedule sweep failed")

        async def _family_bank_payday_sweep():
            # Family Bank payday (match → interest → allowance) across families,
            # evaluated in family-local time. Idempotent per family-local week
            # via last_payday_at, so a restart or duplicate tick never
            # double-pays. Runs hourly; the service filters to the local payday
            # weekday + hour>=8 window (spec §D4).
            async with AsyncSessionLocal() as session:
                try:
                    from app.services.bank_service import BankService
                    n = await BankService.run_payday_sweep(session)
                    if n:
                        logger.info("Family Bank payday sweep paid %d kid(s)", n)
                except Exception:
                    logger.exception("Family Bank payday sweep failed")

        async def _family_purge_sweep():
            # Hard-delete families soft-deleted longer than the grace window
            # (FamilyDeletionService.PURGE_RETENTION_DAYS). Self-serve family
            # deletion only stamps deleted_at + cancels PayPal synchronously;
            # this sweep does the actual cascade delete + uploads/GCS cleanup.
            # Leader-only (this whole block runs on the elected leader). Each
            # family is purged in isolation so one failure never blocks the rest.
            async with AsyncSessionLocal() as session:
                try:
                    from app.services.family_deletion_service import (
                        FamilyDeletionService,
                    )
                    n = await FamilyDeletionService.purge_expired(session)
                    if n:
                        logger.info(
                            "Family purge sweep hard-deleted %d family(ies)", n
                        )
                except Exception:
                    logger.exception("Family purge sweep failed")

        async def _morning_reminder_sweep():
            # 'Tienes N tareas hoy' per member with pending chores due today.
            # Idempotent per local day (DB guard inside the service), so a
            # restart or duplicate tick never double-sends.
            async with AsyncSessionLocal() as session:
                try:
                    n = await TaskAssignmentService.send_morning_reminders(session)
                    if n:
                        logger.info("Morning reminder sweep sent %d reminder(s)", n)
                except Exception:
                    logger.exception("Morning reminder sweep failed")

        async def _auto_shuffle_sweep():
            # Weekly auto-shuffle: families that already use the shuffle get
            # the new week generated without a parent having to remember the
            # button. Idempotent per week (service-level guards); hourly so a
            # Monday spent down self-heals.
            async with AsyncSessionLocal() as session:
                try:
                    n = await TaskAssignmentService.auto_shuffle_all(session)
                    if n:
                        logger.info("Auto-shuffle sweep created %d assignment(s)", n)
                except Exception:
                    logger.exception("Auto-shuffle sweep failed")

        async def _recurring_post_sweep():
            # Auto-post due recurring BUDGET transactions (Actual-Budget
            # schedule parity) — idempotent: posting advances next_due_date.
            async with AsyncSessionLocal() as session:
                try:
                    from app.services.budget.recurring_transaction_service import (
                        RecurringTransactionService,
                    )
                    n = await RecurringTransactionService.post_all_due_all_families(session)
                    if n:
                        logger.info("Recurring post sweep created %d transaction(s)", n)
                except Exception:
                    logger.exception("Recurring post sweep failed")

        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_sweep, "cron", hour=3, minute=0, id="subscription_sweep")
        scheduler.add_job(_pet_decay_sweep, "cron", hour=8, minute=0, id="pet_decay_sweep")
        scheduler.add_job(_pup_snapshot_sweep, "cron", hour=23, minute=30, id="pup_snapshot_sweep")
        scheduler.add_job(_jarvis_schedule_sweep, "cron", minute="*/5", id="jarvis_sched_sweep")
        scheduler.add_job(_family_bank_payday_sweep, "cron", minute=10, id="family_bank_payday")  # hourly
        scheduler.add_job(_family_purge_sweep, "cron", hour=4, minute=0, id="family_purge_sweep")  # daily
        scheduler.add_job(_auto_shuffle_sweep, "cron", minute=25, id="auto_shuffle_sweep")  # hourly
        scheduler.add_job(_recurring_post_sweep, "cron", minute=40, id="recurring_post_sweep")  # hourly
        scheduler.add_job(
            _morning_reminder_sweep,
            "cron",
            hour=7,
            minute=30,
            timezone="America/Mexico_City",
            id="morning_reminder_sweep",
        )
        scheduler.start()

        if leader_client is not None:
            async def _renew_leadership_loop():
                while True:
                    await asyncio.sleep(60)
                    await renew_scheduler_leadership(leader_client, leader_token)

            renew_task = asyncio.create_task(_renew_leadership_loop())

    yield

    # Shutdown
    logger.info("Shutting down API...")
    if scheduler is not None:
        scheduler.shutdown(wait=True)
    for _task in (overdue_task, renew_task):
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
    await release_scheduler_leadership(leader_client, leader_token)
    await engine.dispose()


# Create FastAPI application
app = FastAPI(
    title="Family Task Manager API",
    description="RESTful API for gamified family task organization with rewards and consequences",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS Middleware - Allow frontend to connect
allowed_origins = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session Middleware (required for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY or settings.SECRET_KEY,
    max_age=1800,  # 30 minutes
)


class SecurityHeadersMiddleware:
    """Set baseline security headers on every API response.

    Pure ASGI (not BaseHTTPMiddleware) so SSE/streaming responses pass
    through without buffering. ``setdefault`` lets a route override any of
    these per-response if it ever needs to.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                headers = MutableHeaders(scope=message)
                # Public API is HTTPS-only behind the Cloudflare tunnel.
                headers.setdefault(
                    "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                )
                headers.setdefault("X-Content-Type-Options", "nosniff")
                # The API never renders framable UI.
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Added AFTER CORS/Session so it wraps them (outermost) — headers land on
# every response, including CORS preflights and error responses.
app.add_middleware(SecurityHeadersMiddleware)

# Request-ID correlation — added LAST so it is the outermost user middleware:
# the id is assigned before anything else runs/logs, and the X-Request-ID
# header lands on every response that passes through the middleware chain.
# (500s from the catch-all handler get the header from the handler itself —
# ServerErrorMiddleware sits above even this middleware.)
app.add_middleware(RequestIDMiddleware)

# Rate limiting (slowapi) — protects auth + AI endpoints from abuse.
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from app.core.rate_limiter import limiter  # noqa: E402

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register exception handlers
register_exception_handlers(app)

# Uploaded proof images are served through an authenticated, family-scoped route
# (app.api.routes.uploads), NOT a public StaticFiles mount — the old mount exposed
# every gig-proof / receipt image to anyone over the public tunnel.
import os
try:
    os.makedirs(os.path.join(settings.UPLOADS_ROOT, "gig-proofs"), exist_ok=True)
except OSError:
    # Non-container environments (e.g. running the test suite on the host)
    # have no writable /app; the uploads routes are container-only anyway.
    pass
from app.api.routes import uploads as uploads_routes  # noqa: E402
app.include_router(uploads_routes.router, tags=["Uploads"])

# Include API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/api/oauth", tags=["OAuth"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(onboarding.router, prefix="/api/families/onboarding", tags=["Onboarding"])
app.include_router(families.router, prefix="/api/families", tags=["Families"])
app.include_router(task_templates.router, prefix="/api/task-templates", tags=["Task Templates"])
app.include_router(task_assignments.router, prefix="/api/task-assignments", tags=["Task Assignments"])
app.include_router(rewards.router, prefix="/api/rewards", tags=["Rewards"])
app.include_router(
    consequences.router, prefix="/api/consequences", tags=["Consequences"]
)
app.include_router(invitations.router, prefix="/api/invitations", tags=["Invitations"])
app.include_router(budget_router, prefix="/api/budget", tags=["Budget"])
app.include_router(gigs_router, prefix="/api/gigs", tags=["Gigs"])
app.include_router(oversight.router, prefix="/api/oversight", tags=["Oversight"])
app.include_router(cash.router, prefix="/api/cash", tags=["Cash"])
app.include_router(bank.router, prefix="/api/bank", tags=["Family Bank"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["Subscriptions"])
app.include_router(referrals.router, prefix="/api/referrals", tags=["Referrals"])
from app.api.routes import subscriptions_webhook  # noqa: E402
app.include_router(
    subscriptions_webhook.router,
    prefix="/api/subscriptions",
    tags=["Subscriptions"],
)
app.include_router(push.router, prefix="/api/push", tags=["Push"])
app.include_router(shopping.router, prefix="/api/shopping", tags=["Shopping"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(kiosk.router, prefix="/api/kiosk", tags=["Kiosk"])
app.include_router(pet.router, prefix="/api/pet", tags=["Pet"])
app.include_router(routines.router, prefix="/api/routines", tags=["Routines"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(family_cup.router, prefix="/api/family-cup", tags=["Family Cup"])
app.include_router(jarvis.router, prefix="/api/jarvis", tags=["Jarvis"])
app.include_router(meals.router, prefix="/api/meals", tags=["Meals"])
app.include_router(family_chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(jarvis_schedules.router, prefix="/api/jarvis/schedules", tags=["Jarvis Schedules"])
app.include_router(dm.router, prefix="/api/dm", tags=["DM"])
from app.api.routes.internal import a2a_retry as _internal_a2a  # noqa: E402
app.include_router(_internal_a2a.router, prefix="/api/internal", tags=["internal"])
# Prometheus scrape target at the conventional root path /metrics (token-guarded,
# reuses INTERNAL_API_TOKEN). No prefix — Prometheus defaults to GET /metrics.
from app.api.routes.internal import metrics as _internal_metrics  # noqa: E402
app.include_router(_internal_metrics.router, tags=["internal"])

# Family-scoped MCP server over streamable-HTTP at /mcp, behind per-family
# bearer auth (see app.mcp.http). Each request authenticates its own token,
# binds a family-scoped McpContext, and runs a stateless json_response
# transport — no long-lived session manager task is needed in the lifespan.
#
# Bound at the exact path /mcp via ExactASGIRoute (no trailing-slash redirect):
# MCP clients POST JSON-RPC to /mcp and do not follow a 307 to /mcp/.
if settings.JARVIS_MCP_HTTP_ENABLED:
    from app.mcp.http import ExactASGIRoute, mcp_asgi  # noqa: E402

    app.router.routes.append(ExactASGIRoute("/mcp", mcp_asgi))


@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "name": "Family Task Manager API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """Liveness probe: the process is up. Cheap; does NOT touch dependencies."""
    return {"status": "healthy", "version": settings.VERSION}


@app.get("/ready")
async def readiness_check():
    """Readiness probe: can we actually serve — DB and Redis reachable?

    Returns 503 (degraded) if any dependency check fails, so orchestrators and
    uptime monitors see the truth instead of a static 'connected'.
    """
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    checks = {"database": "error", "redis": "error"}
    healthy = True

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception:
        logger.exception("Readiness: database check failed")
        healthy = False

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        try:
            await r.ping()
            checks["redis"] = "connected"
        finally:
            await r.aclose()
    except Exception:
        logger.exception("Readiness: redis check failed")
        healthy = False

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "degraded", **checks,
                 "version": settings.VERSION},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
