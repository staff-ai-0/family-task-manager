"""
Frontend views router

Handles all web page rendering and communicates with backend API.
"""

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx
import os
from typing import Optional

router = APIRouter(tags=["Frontend Views"])
templates = Jinja2Templates(directory="app/templates")

# Backend API configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://backend:8000")


def get_current_user_from_session(request: Request) -> Optional[dict]:
    """Get current user from session"""
    return request.session.get("user")


def get_access_token_from_session(request: Request) -> Optional[str]:
    """Get access token from session"""
    return request.session.get("access_token")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page"""
    # If already logged in, redirect to dashboard
    if get_access_token_from_session(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "success": None
    })


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    """Handle login form submission"""
    async with httpx.AsyncClient() as client:
        try:
            # Call backend API
            response = await client.post(
                f"{API_BASE_URL}/api/auth/login",
                json={"email": email, "password": password},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # Store token and user in session
                request.session["access_token"] = data["access_token"]
                request.session["user"] = data["user"]
                return RedirectResponse(url="/dashboard", status_code=303)
            else:
                error = response.json().get("detail", "Login failed")
                return templates.TemplateResponse("login.html", {
                    "request": request,
                    "error": error,
                    "success": None
                })
        except httpx.TimeoutException:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Backend service timeout. Please try again.",
                "success": None
            })
        except Exception as e:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": f"An error occurred: {str(e)}",
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
    # Check if user is logged in
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # TODO: Fetch data from backend API using token
    # For now, return basic structure
    stats = {
        "pending_tasks": 0,
        "completed_today": 0,
        "active_consequences": 0
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats,
        "tasks": [],
        "rewards": [],
        "active_consequences": [],
        "pending_tasks_count": 0,
        "active_consequences_count": 0
    })


@router.get("/logout")
async def logout(request: Request):
    """Logout user"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


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
