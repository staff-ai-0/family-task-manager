"""
Task management routes

Handles task CRUD operations, completion, and overdue management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services import TaskService
from app.schemas.task import (
    TaskCreate,
    TaskUpdate,
    TaskComplete,
    TaskResponse,
)
from app.models import User
from app.models.task import TaskStatus
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
)

router = APIRouter()


@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None, description="Filter by assigned user"),
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    is_default: Optional[bool] = Query(None, description="Filter by default tasks"),
):
    """List all tasks"""
    tasks = await TaskService.list_tasks(
        db,
        family_id=to_uuid_required(current_user.family_id),
        user_id=user_id,
        status=status,
        is_default=is_default,
    )
    return tasks


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_data: TaskCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new task (parent only)"""
    try:
        task = await TaskService.create_task(
            db,
            task_data,
            family_id=to_uuid_required(current_user.family_id),
            created_by=to_uuid_required(current_user.id),
        )
        return task
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get task by ID"""
    try:
        task = await TaskService.get_task(
            db, task_id, to_uuid_required(current_user.family_id)
        )
        return task
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark task as completed"""
    try:
        task = await TaskService.complete_task(
            db,
            task_id,
            family_id=to_uuid_required(current_user.family_id),
            user_id=to_uuid_required(current_user.id),
        )
        return task
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    task_data: TaskUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update task"""
    try:
        task = await TaskService.update_task(
            db, task_id, task_data, to_uuid_required(current_user.family_id)
        )
        return task
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete task"""
    try:
        await TaskService.delete_task(
            db, task_id, to_uuid_required(current_user.family_id)
        )
        return None
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/check-overdue", response_model=List[TaskResponse])
async def check_overdue_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check for overdue tasks and update status"""
    tasks = await TaskService.check_overdue_tasks(
        db, to_uuid_required(current_user.family_id)
    )
    return tasks
