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
from app.models.push_subscription import PushSubscription
from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.budget import (
    BudgetCategoryGroup,
    BudgetCategory,
    BudgetAllocation,
    BudgetAccount,
    BudgetPayee,
    BudgetTransaction,
    BudgetSyncState,
    BudgetTransactionItem,
)
from app.models.a2a import FamilyA2AWebhook, A2AWebhookDelivery
from app.models.subscription import (
    SubscriptionPlan,
    FamilySubscription,
    UsageTracking,
)
from app.models.shopping import ShoppingList, ShoppingItem
from app.models.calendar_event import CalendarEvent
from app.models.notification import Notification, NotificationType
from app.models.kiosk_device import KioskDevice
from app.models.kid_pet import KidPet
from app.models.jarvis_message import JarvisMessage
from app.models.pup_snapshot import PupScoreSnapshot
from app.models.meal import Recipe, MealPlanEntry
from app.models.family_chat import FamilyChatMessage
from app.models.family_chat_reaction import FamilyChatReaction
from app.models.jarvis_schedule import JarvisSchedule
from app.models.dm import DMThread, DMMessage
from app.models.gig import GigOffering, GigClaim, GigCategory, GigClaimStatus
from app.models.reward_goal import UserRewardGoal
from app.models.onboarding_event import OnboardingEvent, ONBOARDING_EVENT_TYPES
from app.models.jarvis_pending_action import JarvisPendingAction
from app.models.jarvis_mcp_token import JarvisMcpToken

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
    "FamilyInvitation",
    # Budget Models
    "BudgetCategoryGroup",
    "BudgetCategory",
    "BudgetAllocation",
    "BudgetAccount",
    "BudgetPayee",
    "BudgetTransaction",
    "BudgetSyncState",
    "BudgetTransactionItem",
    # A2A webhook models
    "FamilyA2AWebhook",
    "A2AWebhookDelivery",
    # Subscription Models
    "SubscriptionPlan",
    "FamilySubscription",
    "UsageTracking",
    # Shopping Models
    "ShoppingList",
    "ShoppingItem",
    # Calendar Models
    "CalendarEvent",
    # Notifications
    "Notification",
    "NotificationType",
    # Kiosk
    "KioskDevice",
    # Virtual pet
    "KidPet",
    # Jarvis copilot
    "JarvisMessage",
    # Analytics snapshots
    "PupScoreSnapshot",
    # Meals
    "Recipe",
    "MealPlanEntry",
    # Family chat
    "FamilyChatMessage",
    "FamilyChatReaction",
    # Jarvis schedules
    "JarvisSchedule",
    # DM
    "DMThread",
    "DMMessage",
    # Gigs
    "GigOffering",
    "GigClaim",
    "GigCategory",
    "GigClaimStatus",
    # Reward goals
    "UserRewardGoal",
    # Onboarding analytics
    "OnboardingEvent",
    "ONBOARDING_EVENT_TYPES",
    # Jarvis HITL
    "JarvisPendingAction",
    # Jarvis MCP tokens
    "JarvisMcpToken",
    # Enums
    "UserRole",
    "TaskStatus",
    "TaskFrequency",
    "AssignmentStatus",
    "RewardCategory",
    "ConsequenceSeverity",
    "RestrictionType",
    "TransactionType",
    "InvitationStatus",
]

