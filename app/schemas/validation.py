"""
Validation constants and field factories.
Centralizes all validation limits for consistency.
"""

from pydantic import Field
from typing import Optional


class Limits:
    """Validation limits for all schemas"""

    # String lengths
    TITLE_MIN = 1
    TITLE_MAX = 200
    NAME_MIN = 1
    NAME_MAX = 100
    DESCRIPTION_MAX = 1000
    EMAIL_MAX = 255
    PASSWORD_MIN = 8
    PASSWORD_MAX = 100
    REASON_MIN = 1
    REASON_MAX = 500
    ICON_MAX = 50

    # Numeric ranges
    TASK_POINTS_MIN = 0
    TASK_POINTS_MAX = 1000
    REWARD_POINTS_MIN = 1
    REWARD_POINTS_MAX = 10000
    ADJUSTMENT_POINTS_MIN = -1000
    ADJUSTMENT_POINTS_MAX = 1000
    TRANSFER_POINTS_MIN = 1
    TRANSFER_POINTS_MAX = 1000
    CONSEQUENCE_DAYS_MIN = 1
    CONSEQUENCE_DAYS_MAX = 30

    # List/Query limits
    TRANSACTION_HISTORY_LIMIT = 50
    LIST_DEFAULT_LIMIT = 100
    LIST_MAX_LIMIT = 500


class ErrorMessages:
    """Standard error messages"""

    TITLE_TOO_SHORT = f"Title must be at least {Limits.TITLE_MIN} character"
    TITLE_TOO_LONG = f"Title cannot exceed {Limits.TITLE_MAX} characters"
    PASSWORD_TOO_SHORT = f"Password must be at least {Limits.PASSWORD_MIN} characters"
    INSUFFICIENT_POINTS = "Insufficient points"
    INVALID_DATE = "Date must be in the future"


# Field factory functions
def title_field(description: str = "Title of the item", **kwargs) -> str:
    """Standard title field with consistent validation"""
    return Field(
        ...,
        min_length=Limits.TITLE_MIN,
        max_length=Limits.TITLE_MAX,
        description=description,
        **kwargs,
    )


def description_field(
    description: str = "Optional description", **kwargs
) -> Optional[str]:
    """Standard description field"""
    return Field(
        None, max_length=Limits.DESCRIPTION_MAX, description=description, **kwargs
    )


def name_field(description: str = "Name", **kwargs) -> str:
    """Standard name field"""
    return Field(
        ...,
        min_length=Limits.NAME_MIN,
        max_length=Limits.NAME_MAX,
        description=description,
        **kwargs,
    )


def email_field(description: str = "Email address", **kwargs) -> str:
    """Standard email field"""
    return Field(
        ...,
        max_length=Limits.EMAIL_MAX,
        description=description,
        pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        **kwargs,
    )


def points_field(
    min_value: int = Limits.TASK_POINTS_MIN,
    max_value: int = Limits.TASK_POINTS_MAX,
    description: str = "Points value",
    **kwargs,
) -> int:
    """Standard points field with configurable range"""
    return Field(..., ge=min_value, le=max_value, description=description, **kwargs)
