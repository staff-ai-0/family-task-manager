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


@router.post("/logout")
async def logout(request: Request):
    """Logout user"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
async def logout_get(request: Request):
    """Logout user (GET fallback)"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """Render tasks list page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # Fetch tasks and family members from backend API
    tasks = []
    family_members = []
    async with httpx.AsyncClient() as client:
        try:
            # Fetch tasks
            response = await client.get(
                f"{API_BASE_URL}/api/tasks",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                tasks = response.json()
            
            # Fetch family members for assignment dropdown (parents only)
            if current_user and current_user.get("role", "").lower() == "parent":
                family_response = await client.get(
                    f"{API_BASE_URL}/api/families/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0
                )
                if family_response.status_code == 200:
                    family_data = family_response.json()
                    family_members = family_data.get("members", [])
        except Exception:
            pass
    
    return templates.TemplateResponse("tasks/list.html", {
        "request": request,
        "current_user": current_user,
        "tasks": tasks,
        "family_members": family_members,
        "pending_tasks_count": len([t for t in tasks if t.get("status") == "pending"])
    })


@router.post("/tasks/new")
async def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    points: int = Form(...),
    frequency: str = Form("ONCE"),
    is_default: bool = Form(False),
    assigned_to_id: str = Form(None)
):
    """Create a new task"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    if not current_user or current_user.get("role", "").lower() != "parent":
        return RedirectResponse(url="/tasks", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            task_data = {
                "title": title,
                "description": description,
                "points": points,
                "frequency": frequency,
                "is_default": is_default
            }
            if assigned_to_id:
                task_data["assigned_to_id"] = assigned_to_id
            
            await client.post(
                f"{API_BASE_URL}/api/tasks",
                headers={"Authorization": f"Bearer {token}"},
                json=task_data,
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/tasks/{task_id}/complete")
async def complete_task(request: Request, task_id: str):
    """Mark a task as complete"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{API_BASE_URL}/api/tasks/{task_id}/complete",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/tasks/{task_id}/delete")
async def delete_task(request: Request, task_id: str):
    """Delete a task"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    if not current_user or current_user.get("role", "").lower() != "parent":
        return RedirectResponse(url="/tasks", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            await client.delete(
                f"{API_BASE_URL}/api/tasks/{task_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/tasks", status_code=303)


@router.get("/rewards", response_class=HTMLResponse)
async def rewards_page(request: Request):
    """Render rewards list page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # Fetch rewards from backend API
    rewards = []
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/api/rewards",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                rewards = response.json()
        except Exception:
            pass
    
    return templates.TemplateResponse("rewards/list.html", {
        "request": request,
        "current_user": current_user,
        "rewards": rewards
    })


@router.post("/rewards/new")
async def create_reward(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    points_cost: int = Form(...),
    quantity: int = Form(-1)
):
    """Create a new reward"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    if not current_user or current_user.get("role", "").lower() != "parent":
        return RedirectResponse(url="/rewards", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            reward_data = {
                "name": name,
                "description": description,
                "points_cost": points_cost,
                "quantity": quantity if quantity > 0 else -1  # -1 means unlimited
            }
            
            await client.post(
                f"{API_BASE_URL}/api/rewards",
                headers={"Authorization": f"Bearer {token}"},
                json=reward_data,
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/rewards", status_code=303)


@router.post("/rewards/{reward_id}/redeem")
async def redeem_reward(request: Request, reward_id: str):
    """Redeem a reward"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{API_BASE_URL}/api/rewards/{reward_id}/redeem",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/rewards", status_code=303)


@router.post("/rewards/{reward_id}/delete")
async def delete_reward(request: Request, reward_id: str):
    """Delete a reward"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    if not current_user or current_user.get("role", "").lower() != "parent":
        return RedirectResponse(url="/rewards", status_code=303)
    
    async with httpx.AsyncClient() as client:
        try:
            await client.delete(
                f"{API_BASE_URL}/api/rewards/{reward_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
        except Exception:
            pass
    
    return RedirectResponse(url="/rewards", status_code=303)


@router.get("/consequences", response_class=HTMLResponse)
async def consequences_page(request: Request):
    """Render consequences list page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # Fetch consequences from backend API
    consequences = []
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/api/consequences",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                consequences = response.json()
        except Exception:
            pass
    
    return templates.TemplateResponse("consequences/list.html", {
        "request": request,
        "current_user": current_user,
        "consequences": consequences,
        "active_consequences_count": len([c for c in consequences if c.get("status") == "active"])
    })


@router.get("/points", response_class=HTMLResponse)
async def points_page(request: Request):
    """Render points history page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # Fetch transactions from backend API
    transactions = []
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/api/points/history",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                transactions = response.json()
        except Exception:
            pass
    
    return templates.TemplateResponse("points/history.html", {
        "request": request,
        "current_user": current_user,
        "transactions": transactions
    })


@router.get("/family", response_class=HTMLResponse)
async def family_page(request: Request):
    """Render family management page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    # Only parents can access family management
    if current_user and current_user.get("role", "").lower() != "parent":
        return RedirectResponse(url="/dashboard", status_code=303)
    
    # Fetch family and members from backend API
    family = None
    members = []
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_BASE_URL}/api/family",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                family = data.get("family")
                members = data.get("members", [])
        except Exception:
            pass
    
    return templates.TemplateResponse("family/manage.html", {
        "request": request,
        "current_user": current_user,
        "family": family,
        "members": members
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render settings page"""
    token = get_access_token_from_session(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)
    
    current_user = get_current_user_from_session(request)
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "current_user": current_user
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
