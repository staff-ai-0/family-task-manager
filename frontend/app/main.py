"""
Family Task Manager - Frontend Application

Server-side rendered web interface that communicates with the backend API.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# Create FastAPI application
app = FastAPI(
    title="Family Task Manager - Web Interface",
    description="Server-side rendered web interface for Family Task Manager",
    version="1.0.0",
    docs_url=None,  # Disable docs on frontend
    redoc_url=None,
)

# Session Middleware (for auth state)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=1800,  # 30 minutes
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Import views
from app.views import router as views_router

# Include routers
app.include_router(views_router)


@app.get("/")
async def root():
    """Root endpoint - redirect to login or dashboard"""
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "frontend",
        "version": "1.0.0",
        "api_url": API_BASE_URL
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=DEBUG)
