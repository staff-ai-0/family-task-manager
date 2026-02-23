"""
SQLAlchemy models for Family Task Manager

This module exports all database models for the application.
Import models from this module to ensure proper initialization order.
"""

# Import Base first
from app.core.database import Base

# Import models in dependency order
from app.models.family import Family
from app.models.user import User, UserRole
from app.models.task import Task, TaskStatus, TaskFrequency
from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.reward import Reward, RewardCategory
from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.password_reset import PasswordResetToken
from app.models.email_verification import EmailVerificationToken

__all__ = [
    "Base",
    # Models
    "Family",
    "User",
    "Task",
    "TaskTemplate",
    "TaskAssignment",
    "Reward",
    "Consequence",
    "PointTransaction",
    "PasswordResetToken",
    "EmailVerificationToken",
    # Enums
    "UserRole",
    "TaskStatus",
    "TaskFrequency",
    "AssignmentStatus",
    "RewardCategory",
    "ConsequenceSeverity",
    "RestrictionType",
    "TransactionType",
]

