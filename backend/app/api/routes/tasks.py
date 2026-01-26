"""
Task management routes

Handles task CRUD operations, completion, and overdue management.
"""

from fastapi import APIRouter, Depends, status, Query
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
    TaskBulkCreate,
    TaskBulkCreateResponse,
    TaskDuplicate,
    TaskRegenerateRequest,
)
from app.models import User
from app.models.task import TaskStatus

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
    task = await TaskService.create_task(
        db,
        task_data,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
    )
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get task by ID"""
    task = await TaskService.get_task(
        db, task_id, to_uuid_required(current_user.family_id)
    )
    return task


@router.patch("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark task as completed"""
    task = await TaskService.complete_task(
        db,
        task_id,
        family_id=to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
    )
    return task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    task_data: TaskUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update task"""
    task = await TaskService.update_task(
        db, task_id, task_data, to_uuid_required(current_user.family_id)
    )
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete task"""
    await TaskService.delete_task(db, task_id, to_uuid_required(current_user.family_id))
    return None


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


@router.post("/bulk-create", response_model=TaskBulkCreateResponse, status_code=status.HTTP_201_CREATED)
async def bulk_create_tasks(
    task_data: TaskBulkCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create the same task for multiple users at once (parent only)"""
    tasks = await TaskService.bulk_create_tasks(
        db,
        task_data,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
    )
    return TaskBulkCreateResponse(created_count=len(tasks), tasks=tasks)


@router.post("/{task_id}/duplicate", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_task(
    task_id: UUID,
    duplicate_data: TaskDuplicate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate an existing task (parent only)"""
    task = await TaskService.duplicate_task(
        db,
        task_id,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
        assigned_to=duplicate_data.assigned_to,
        include_due_date=duplicate_data.include_due_date,
    )
    return task


@router.post("/regenerate", response_model=List[TaskResponse], status_code=status.HTTP_201_CREATED)
async def regenerate_tasks(
    request: TaskRegenerateRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate recurring tasks based on frequency (parent only)
    
    Creates new pending task instances from completed tasks of the specified frequency.
    Useful for resetting daily/weekly/monthly tasks for a new period.
    """
    tasks = await TaskService.regenerate_tasks(
        db,
        request,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
    )
    return tasks
