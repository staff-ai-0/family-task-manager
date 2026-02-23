"""
Pydantic schemas for Family Task Manager

This module exports all Pydantic schemas for request/response validation.
"""

from app.schemas.user import (
    UserBase,
    UserCreate,
    UserUpdate,
    UserPasswordUpdate,
    UserResponse,
    UserWithStats,
    UserLogin,
    TokenResponse,
)

from app.schemas.family import (
    FamilyBase,
    FamilyCreate,
    FamilyUpdate,
    FamilyResponse,
    FamilyWithMembers,
    FamilyStats,
)

from app.schemas.task import (
    TaskBase,
    TaskCreate,
    TaskUpdate,
    TaskComplete,
    TaskResponse,
    TaskWithDetails,
)

from app.schemas.task_template import (
    TaskTemplateBase,
    TaskTemplateCreate,
    TaskTemplateUpdate,
    TaskTemplateResponse,
    TaskTemplateWithStats,
)

from app.schemas.task_assignment import (
    AssignmentComplete,
    ShuffleRequest,
    ShuffleResponse,
    TaskAssignmentResponse,
    TaskAssignmentWithDetails,
    DailyProgressResponse,
)

from app.schemas.reward import (
    RewardBase,
    RewardCreate,
    RewardUpdate,
    RewardRedeem,
    RewardRedeemApproval,
    RewardResponse,
    RewardWithStatus,
)

from app.schemas.consequence import (
    ConsequenceBase,
    ConsequenceCreate,
    ConsequenceUpdate,
    ConsequenceResolve,
    ConsequenceResponse,
    ConsequenceWithDetails,
)

from app.schemas.points import (
    PointTransactionBase,
    PointTransactionCreate,
    ParentAdjustment,
    PointTransfer,
    PointTransactionResponse,
    PointTransactionWithDetails,
    PointsSummary,
)

__all__ = [
    # User schemas
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserPasswordUpdate",
    "UserResponse",
    "UserWithStats",
    "UserLogin",
    "TokenResponse",
    # Family schemas
    "FamilyBase",
    "FamilyCreate",
    "FamilyUpdate",
    "FamilyResponse",
    "FamilyWithMembers",
    "FamilyStats",
    # Task schemas (legacy)
    "TaskBase",
    "TaskCreate",
    "TaskUpdate",
    "TaskComplete",
    "TaskResponse",
    "TaskWithDetails",
    # Task Template schemas
    "TaskTemplateBase",
    "TaskTemplateCreate",
    "TaskTemplateUpdate",
    "TaskTemplateResponse",
    "TaskTemplateWithStats",
    # Task Assignment schemas
    "AssignmentComplete",
    "ShuffleRequest",
    "ShuffleResponse",
    "TaskAssignmentResponse",
    "TaskAssignmentWithDetails",
    "DailyProgressResponse",
    # Reward schemas
    "RewardBase",
    "RewardCreate",
    "RewardUpdate",
    "RewardRedeem",
    "RewardRedeemApproval",
    "RewardResponse",
    "RewardWithStatus",
    # Consequence schemas
    "ConsequenceBase",
    "ConsequenceCreate",
    "ConsequenceUpdate",
    "ConsequenceResolve",
    "ConsequenceResponse",
    "ConsequenceWithDetails",
    # Points schemas
    "PointTransactionBase",
    "PointTransactionCreate",
    "ParentAdjustment",
    "PointTransfer",
    "PointTransactionResponse",
    "PointTransactionWithDetails",
    "PointsSummary",
]

