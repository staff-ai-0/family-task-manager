"""
Shared templates configuration for the application.

This module provides a centralized Jinja2Templates instance to be used
across all route handlers. This ensures consistency and follows the
SSR-First architecture pattern.

Usage:
    from app.core.templates import templates
    
    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})
"""

from fastapi.templating import Jinja2Templates

# Shared templates instance - ALWAYS use this instead of creating new instances
templates = Jinja2Templates(directory="app/templates")
