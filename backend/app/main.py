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
from app.api.routes import auth, users, rewards, consequences, families, task_templates, task_assignments, sync, oauth, payment, points_conversion, invitations, subscriptions, push, shopping, calendar, notifications, kiosk, pet, analytics, frankie, meals, family_chat, frankie_schedules, dm
from app.api.routes.budget import router as budget_router
from app.jobs.subscription_sweep import run_sweep
from app.services.task_assignment_service import TaskAssignmentService
from app.services.pet_service import PetService
from app.services.analytics_service import AnalyticsService
from app.services.frankie_schedule_service import FrankieScheduleService

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
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Overdue sweep failed")
        await asyncio.sleep(60 * 60)  # 1 hour


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting Family Task Manager API...")
    logger.info(
        f"Database URL: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'Not configured'}"
    )

    # Create database tables (in production, use Alembic migrations)
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)

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

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_sweep, "cron", hour=3, minute=0, id="subscription_sweep")
    scheduler.add_job(_pet_decay_sweep, "cron", hour=8, minute=0, id="pet_decay_sweep")
    scheduler.add_job(_pup_snapshot_sweep, "cron", hour=23, minute=30, id="pup_snapshot_sweep")

    async def _frankie_schedule_sweep():
        async with AsyncSessionLocal() as session:
            try:
                n = await FrankieScheduleService.sweep_due(session)
                if n:
                    logger.info("Jarvis schedule sweep fired %d", n)
            except Exception:
                logger.exception("Jarvis schedule sweep failed")
    scheduler.add_job(_frankie_schedule_sweep, "cron", minute="*/5", id="frankie_sched_sweep")

    scheduler.start()

    yield

    # Shutdown
    logger.info("Shutting down API...")
    scheduler.shutdown(wait=True)
    overdue_task.cancel()
    try:
        await overdue_task
    except asyncio.CancelledError:
        pass
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

# Register exception handlers
register_exception_handlers(app)

# Static files (gig proof images, etc.). The container mounts the volume at
# /app/uploads; subdirectories like /app/uploads/gig-proofs/ are created on demand.
import os
from fastapi.staticfiles import StaticFiles
os.makedirs("/app/uploads/gig-proofs", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="/app/uploads"), name="uploads")

# Include API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/api/oauth", tags=["OAuth"])
app.include_router(payment.router, prefix="/api/payment", tags=["Payment"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(families.router, prefix="/api/families", tags=["Families"])
app.include_router(task_templates.router, prefix="/api/task-templates", tags=["Task Templates"])
app.include_router(task_assignments.router, prefix="/api/task-assignments", tags=["Task Assignments"])
app.include_router(rewards.router, prefix="/api/rewards", tags=["Rewards"])
app.include_router(
    consequences.router, prefix="/api/consequences", tags=["Consequences"]
)
app.include_router(invitations.router, prefix="/api/invitations", tags=["Invitations"])
app.include_router(budget_router, prefix="/api/budget", tags=["Budget"])
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
app.include_router(frankie.router, prefix="/api/frankie", tags=["Frankie"])
app.include_router(meals.router, prefix="/api/meals", tags=["Meals"])
app.include_router(family_chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(frankie_schedules.router, prefix="/api/frankie/schedules", tags=["Frankie Schedules"])
app.include_router(dm.router, prefix="/api/dm", tags=["DM"])


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
    """Health check endpoint"""
    return {"status": "healthy", "database": "connected", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
