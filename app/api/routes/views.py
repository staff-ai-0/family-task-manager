"""
HTML views router

Server-side rendered pages using Jinja2 templates.
Follows SSR-First architecture with Flowbite components.
"""

from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
from datetime import datetime

from app.core.templates import templates
from app.core.dependencies import get_db, get_optional_user, get_current_user, get_current_user_session
from app.models.user import User, UserRole
from app.models.task import TaskStatus, TaskFrequency
from app.services.task_service import TaskService
from app.services.auth_service import AuthService
from app.services.family_service import FamilyService
from app.services.email_service import EmailService
from app.services.oauth_service import GoogleOAuthService, oauth
from app.schemas.task import TaskCreate
from app.schemas.user import UserCreate
from app.schemas.family import FamilyCreate
from app.core.security import verify_password

router = APIRouter(tags=["HTML Views"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render dashboard page"""
    
    stats = {
        "pending_tasks": 0,
        "completed_today": 0,
        "active_consequences": 0
    }
    tasks = []
    rewards = []
    active_consequences = []
    
    if current_user and current_user.family_id:
        # Get pending tasks count
        stats["pending_tasks"] = await TaskService.get_user_pending_tasks_count(
            db=db,
            user_id=current_user.id
        )
        
        # Get recent tasks
        tasks = await TaskService.list_tasks(
            db=db,
            family_id=current_user.family_id,
            user_id=current_user.id
        )
        tasks = tasks[:5]  # Limit to 5 most recent
        
        # TODO: Get completed today count
        # TODO: Get real rewards from database
        # TODO: Get active consequences
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats,
        "tasks": tasks,
        "rewards": rewards,
        "active_consequences": active_consequences,
        "pending_tasks_count": stats["pending_tasks"],
        "active_consequences_count": stats["active_consequences"]
    })


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render tasks list page"""
    
    tasks = []
    if current_user and current_user.family_id:
        # Get tasks for the user's family
        tasks = await TaskService.list_tasks(
            db=db,
            family_id=current_user.family_id,
            user_id=current_user.id if current_user.role != "PARENT" else None
        )
    
    return templates.TemplateResponse("tasks/list.html", {
        "request": request,
        "current_user": current_user,
        "tasks": tasks
    })


@router.get("/rewards", response_class=HTMLResponse)
async def rewards_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render rewards catalog page"""
    
    # TODO: Get real rewards from database
    rewards = []
    
    return templates.TemplateResponse("rewards/list.html", {
        "request": request,
        "current_user": current_user,
        "rewards": rewards
    })


@router.get("/consequences", response_class=HTMLResponse)
async def consequences_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render consequences page"""
    
    # TODO: Get real consequences from database
    consequences = []
    
    return templates.TemplateResponse("consequences/list.html", {
        "request": request,
        "current_user": current_user,
        "consequences": consequences
    })


@router.get("/points", response_class=HTMLResponse)
async def points_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render points history page"""
    
    # TODO: Get real point transactions from database
    transactions = []
    
    return templates.TemplateResponse("points/history.html", {
        "request": request,
        "current_user": current_user,
        "transactions": transactions
    })


@router.get("/family", response_class=HTMLResponse)
async def family_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Render family management page (parents only)"""
    
    # TODO: Check if user is parent
    # TODO: Get family members from database
    members = []
    
    return templates.TemplateResponse("family/manage.html", {
        "request": request,
        "current_user": current_user,
        "members": members
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user)
):
    """Render settings page"""
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "current_user": current_user
    })


# ============================================================================
# POST Routes (Following PRG Pattern - Post-Redirect-Get)
# ============================================================================

@router.post("/tasks/new")
async def create_task(
    title: str = Form(...),
    description: str = Form(""),
    points: int = Form(...),
    assigned_to: str = Form(...),
    due_date: Optional[str] = Form(None),
    frequency: str = Form("ONCE"),
    is_default: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new task (PRG pattern)"""
    try:
        # Parse due_date if provided
        parsed_due_date = None
        if due_date:
            parsed_due_date = datetime.fromisoformat(due_date)
        
        # Create task
        task_data = TaskCreate(
            title=title,
            description=description,
            points=points,
            assigned_to=UUID(assigned_to),
            due_date=parsed_due_date,
            frequency=TaskFrequency(frequency),
            is_default=is_default
        )
        
        await TaskService.create_task(
            db=db,
            task_data=task_data,
            family_id=current_user.family_id,
            created_by=current_user.id
        )
        
        # Redirect to tasks page (PRG pattern)
        return RedirectResponse(url="/tasks", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        # On error, redirect back with error (TODO: add flash messages)
        return RedirectResponse(url="/tasks?error=create_failed", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Complete task (PRG pattern)"""
    try:
        await TaskService.complete_task(
            db=db,
            task_id=task_id,
            family_id=current_user.family_id,
            user_id=current_user.id
        )
        
        # Redirect to tasks page (PRG pattern)
        return RedirectResponse(url="/tasks", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        # On error, redirect back with error
        return RedirectResponse(url="/tasks?error=complete_failed", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/delete")
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete task (PRG pattern - Parents only)"""
    try:
        await TaskService.delete_task(
            db=db,
            task_id=task_id,
            family_id=current_user.family_id
        )
        
        # Redirect to tasks page (PRG pattern)
        return RedirectResponse(url="/tasks", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        # On error, redirect back with error
        return RedirectResponse(url="/tasks?error=delete_failed", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================================
# Authentication Routes (Login/Register/Logout)
# ============================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    """Render login page"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error
    })


@router.post("/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    remember: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Login user (PRG pattern)"""
    try:
        # Authenticate user
        from sqlalchemy import select
        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user or not verify_password(password, user.password_hash):
            return RedirectResponse(
                url="/login?error=invalid_credentials",
                status_code=status.HTTP_303_SEE_OTHER
            )
        
        # Create response with redirect
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        
        # Set session cookie
        max_age = 30 * 24 * 60 * 60 if remember else None  # 30 days if remember me
        response.set_cookie(
            key="user_id",
            value=str(user.id),
            httponly=True,
            max_age=max_age,
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        return RedirectResponse(
            url="/login?error=server_error",
            status_code=status.HTTP_303_SEE_OTHER
        )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: Optional[str] = None):
    """Render register page"""
    return templates.TemplateResponse("register.html", {
        "request": request,
        "error": error
    })


@router.post("/register")
async def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    family_option: str = Form(...),
    family_name: Optional[str] = Form(None),
    invite_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Register new user (PRG pattern)"""
    from sqlalchemy import select
    from app.models.family import Family
    
    try:
        # First, check if user already exists
        result = await db.execute(select(User).filter(User.email == email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            return RedirectResponse(
                url="/register?error=email_exists",
                status_code=status.HTTP_303_SEE_OTHER
            )
        
        # Determine family_id based on option
        family_id = None
        newly_created_family = None  # Track if we created a new family
        
        if family_option == "join" and invite_code:
            # Join existing family by invite code
            result = await db.execute(
                select(Family).filter(Family.invite_code == invite_code)
            )
            family = result.scalar_one_or_none()
            if not family:
                return RedirectResponse(
                    url="/register?error=invalid_invite_code",
                    status_code=status.HTTP_303_SEE_OTHER
                )
            family_id = family.id
        
        elif family_option == "create" and family_name:
            # Create new family FIRST (before user, to get family_id)
            # Create family without specifying created_by yet
            newly_created_family = Family(
                name=family_name,
            )
            db.add(newly_created_family)
            await db.flush()  # Get the family.id without committing
            family_id = newly_created_family.id
        
        if not family_id:
            return RedirectResponse(
                url="/register?error=family_required",
                status_code=status.HTTP_303_SEE_OTHER
            )
        
        # Create user with family_id
        user_data = UserCreate(
            name=name,
            email=email,
            password=password,
            role=UserRole(role.lower()),
            family_id=family_id
        )
        
        user = await AuthService.register_user(db, user_data)
        
        # If we created a new family, update it to add created_by
        if newly_created_family:
            newly_created_family.created_by = user.id
        
        await db.commit()
        
        # Send verification email (don't block on this)
        try:
            from app.core.config import settings
            await EmailService.send_verification_email(db, user, base_url=settings.BASE_URL)
        except Exception as e:
            print(f"Failed to send verification email: {e}")
        
        # Redirect to login with success message
        return RedirectResponse(
            url="/login?success=registered",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    except Exception as e:
        print(f"Registration error: {e}")  # For debugging
        return RedirectResponse(
            url="/register?error=registration_failed",
            status_code=status.HTTP_303_SEE_OTHER
        )


@router.post("/logout")
async def logout():
    """Logout user (PRG pattern)"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="user_id")
    return response


# ========================================
# Email Verification Routes
# ========================================

@router.get("/auth/verify-email", response_class=HTMLResponse)
async def verify_email(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Verify email with token"""
    user = await EmailService.verify_email_token(db, token)
    
    if user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "success": "email_verified"
        })
    else:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "invalid_token"
        })


@router.post("/auth/resend-verification")
async def resend_verification(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_session)
):
    """Resend verification email"""
    if current_user.email_verified:
        return RedirectResponse(
            url="/dashboard?message=already_verified",
            status_code=status.HTTP_303_SEE_OTHER
        )
    
    # Send verification email
    from app.core.config import settings
    await EmailService.send_verification_email(db, current_user, base_url=settings.BASE_URL)
    
    return RedirectResponse(
        url="/dashboard?message=verification_sent",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ========================================
# Google OAuth Routes
# ========================================

@router.get("/auth/google/login")
async def google_login(request: Request):
    """Redirect to Google OAuth"""
    from app.core.config import settings
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Google OAuth callback"""
    from app.models.family import Family
    
    try:
        # Get user info from Google
        google_user_info = await GoogleOAuthService.get_user_info(request)
        
        if not google_user_info:
            return RedirectResponse(
                url="/login?error=oauth_failed",
                status_code=status.HTTP_303_SEE_OTHER
            )
        
        # Try to find existing user
        user = await GoogleOAuthService.find_or_create_user(
            db,
            google_user_info,
            family_id=None  # Will return None if user doesn't exist
        )
        
        if not user:
            # New user - create family and user automatically
            # Generate family name from user's name
            user_name = google_user_info.get('name', 'User')
            family_name = f"{user_name}'s Family"
            
            # Create new family
            new_family = Family(name=family_name)
            db.add(new_family)
            await db.flush()  # Get family_id
            
            # Create user with family
            user = await GoogleOAuthService.find_or_create_user(
                db,
                google_user_info,
                family_id=new_family.id
            )
            
            if not user:
                return RedirectResponse(
                    url="/login?error=oauth_failed",
                    status_code=status.HTTP_303_SEE_OTHER
                )
            
            # Set family creator
            new_family.created_by = user.id
            await db.commit()
        
        # Create session cookie
        response = RedirectResponse(
            url="/dashboard",
            status_code=status.HTTP_303_SEE_OTHER
        )
        response.set_cookie(
            key="user_id",
            value=str(user.id),
            httponly=True,
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        print(f"Google OAuth error: {e}")
        return RedirectResponse(
            url="/login?error=oauth_failed",
            status_code=status.HTTP_303_SEE_OTHER
        )


# ========================================
# Password Reset Routes
# ========================================

@router.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("forgot_password.html", {
        "request": request
    })


@router.post("/auth/forgot-password")
async def forgot_password(
    email: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Request password reset email"""
    from sqlalchemy import select
    
    # Find user by email
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalar_one_or_none()
    
    # Always show success message (don't reveal if email exists)
    if user:
        try:
            from app.core.config import settings
            await EmailService.send_password_reset_email(
                db, user, base_url=settings.BASE_URL
            )
        except Exception as e:
            print(f"Failed to send password reset email: {e}")
    
    # Redirect with success message regardless
    return RedirectResponse(
        url="/login?message=reset_email_sent",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/auth/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Render password reset page"""
    # Verify token is valid
    reset_token = await EmailService.verify_password_reset_token(db, token)
    
    if not reset_token:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "invalid_reset_token"
        })
    
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token
    })


@router.post("/auth/reset-password")
async def reset_password(
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Reset password with token"""
    # Validate passwords match
    if password != password_confirm:
        return RedirectResponse(
            url=f"/auth/reset-password?token={token}&error=passwords_mismatch",
            status_code=status.HTTP_303_SEE_OTHER
        )
    
    # Verify token
    reset_token = await EmailService.verify_password_reset_token(db, token)
    
    if not reset_token:
        return RedirectResponse(
            url="/login?error=invalid_reset_token",
            status_code=status.HTTP_303_SEE_OTHER
        )
    
    # Hash new password
    from app.core.security import get_password_hash
    password_hash = get_password_hash(password)
    
    # Reset password
    user = await EmailService.reset_password(db, reset_token, password_hash)
    
    if not user:
        return RedirectResponse(
            url="/login?error=reset_failed",
            status_code=status.HTTP_303_SEE_OTHER
        )
    
    # Redirect to login with success message
    return RedirectResponse(
        url="/login?success=password_reset",
        status_code=status.HTTP_303_SEE_OTHER
    )

