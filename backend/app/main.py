import asyncio
from datetime import datetime, timedelta, time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.exception_handlers import register_exception_handlers
from app.api.routes import auth, users, rewards, consequences, families, task_templates, task_assignments, sync, oauth, payment, points_conversion, invitations, subscriptions, push, shopping, calendar, notifications, kiosk, pet, analytics, jarvis, meals, family_chat, jarvis_schedules, dm
from app.api.routes.budget import router as budget_router
from app.api.routes.gigs import router as gigs_router
from app.api.routes import oversight, onboarding
from app.jobs.subscription_sweep import run_sweep
from app.services.task_assignment_service import TaskAssignmentService
from app.services.consequence_service import ConsequenceService
from app.services.pet_service import PetService
from app.services.analytics_service import AnalyticsService
from app.services.jarvis_schedule_service import JarvisScheduleService

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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

        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_sweep, "cron", hour=3, minute=0, id="subscription_sweep")
        scheduler.add_job(_pet_decay_sweep, "cron", hour=8, minute=0, id="pet_decay_sweep")
        scheduler.add_job(_pup_snapshot_sweep, "cron", hour=23, minute=30, id="pup_snapshot_sweep")
        scheduler.add_job(_jarvis_schedule_sweep, "cron", minute="*/5", id="jarvis_sched_sweep")
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
    secret_key=settings.SECRET_KEY,
    max_age=1800,  # 30 minutes
)

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
os.makedirs("/app/uploads/gig-proofs", exist_ok=True)
from app.api.routes import uploads as uploads_routes  # noqa: E402
app.include_router(uploads_routes.router, tags=["Uploads"])

# Include API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/api/oauth", tags=["OAuth"])
app.include_router(payment.router, prefix="/api/payment", tags=["Payment"])
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
app.include_router(points_conversion.router, prefix="/api/points-conversion", tags=["Points Conversion"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["Subscriptions"])
from app.api.routes import subscriptions_webhook  # noqa: E402
app.include_router(
    subscriptions_webhook.router,
    prefix="/api/subscriptions",
    tags=["Subscriptions"],
)
app.include_router(sync.router, tags=["Sync"])
app.include_router(push.router, prefix="/api/push", tags=["Push"])
app.include_router(shopping.router, prefix="/api/shopping", tags=["Shopping"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(kiosk.router, prefix="/api/kiosk", tags=["Kiosk"])
app.include_router(pet.router, prefix="/api/pet", tags=["Pet"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(jarvis.router, prefix="/api/jarvis", tags=["Jarvis"])
app.include_router(meals.router, prefix="/api/meals", tags=["Meals"])
app.include_router(family_chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(jarvis_schedules.router, prefix="/api/jarvis/schedules", tags=["Jarvis Schedules"])
app.include_router(dm.router, prefix="/api/dm", tags=["DM"])
from app.api.routes.internal import a2a_retry as _internal_a2a  # noqa: E402
app.include_router(_internal_a2a.router, prefix="/api/internal", tags=["internal"])


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
