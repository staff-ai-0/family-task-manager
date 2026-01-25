"""
Frontend views router

Handles all web page rendering and communicates with backend API.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Frontend Views"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "success": None
    })


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render registration page"""
    return templates.TemplateResponse("register.html", {
        "request": request
    })


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render dashboard page"""
    # TODO: Fetch data from backend API
    stats = {
        "pending_tasks": 0,
        "completed_today": 0,
        "active_consequences": 0
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": None,  # TODO: Get from session/API
        "stats": stats,
        "tasks": [],
        "rewards": [],
        "active_consequences": [],
        "pending_tasks_count": 0,
        "active_consequences_count": 0
    })


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """Render tasks list page"""
    return templates.TemplateResponse("tasks/list.html", {
        "request": request,
        "current_user": None,
        "tasks": []
    })


@router.get("/rewards", response_class=HTMLResponse)
async def rewards_page(request: Request):
    """Render rewards list page"""
    return templates.TemplateResponse("rewards/list.html", {
        "request": request,
        "current_user": None,
        "rewards": []
    })


@router.get("/consequences", response_class=HTMLResponse)
async def consequences_page(request: Request):
    """Render consequences list page"""
    return templates.TemplateResponse("consequences/list.html", {
        "request": request,
        "current_user": None,
        "consequences": []
    })


@router.get("/points", response_class=HTMLResponse)
async def points_page(request: Request):
    """Render points history page"""
    return templates.TemplateResponse("points/history.html", {
        "request": request,
        "current_user": None,
        "transactions": []
    })


@router.get("/family", response_class=HTMLResponse)
async def family_page(request: Request):
    """Render family management page"""
    return templates.TemplateResponse("family/manage.html", {
        "request": request,
        "current_user": None,
        "family": None,
        "members": []
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render settings page"""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "current_user": None
    })


@router.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("forgot_password.html", {
        "request": request
    })


@router.get("/auth/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = ""):
    """Render reset password page"""
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token
    })
