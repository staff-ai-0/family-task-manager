from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import engine, Base
from app.core.exception_handlers import register_exception_handlers
from app.api.routes import auth, users, tasks, rewards, consequences, families, task_templates, task_assignments, sync, oauth, payment, points_conversion
from app.api.routes.budget import router as budget_router

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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

    yield

    # Shutdown
    logger.info("Shutting down API...")
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
allowed_origins.extend(["http://localhost:3000", "http://localhost:3003", "http://localhost:8080"])  # Add common frontend ports

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

# Include API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(oauth.router, prefix="/api/oauth", tags=["OAuth"])
app.include_router(payment.router, prefix="/api/payment", tags=["Payment"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(families.router, prefix="/api/families", tags=["Families"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks (Legacy)"])
app.include_router(task_templates.router, prefix="/api/task-templates", tags=["Task Templates"])
app.include_router(task_assignments.router, prefix="/api/task-assignments", tags=["Task Assignments"])
app.include_router(rewards.router, prefix="/api/rewards", tags=["Rewards"])
app.include_router(
    consequences.router, prefix="/api/consequences", tags=["Consequences"]
)
app.include_router(budget_router, prefix="/api/budget", tags=["Budget"])
app.include_router(points_conversion.router, prefix="/api/points-conversion", tags=["Points Conversion"])
app.include_router(sync.router, tags=["Sync"])


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
