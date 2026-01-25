"""
Type conversion utilities for SQLAlchemy Column to Python type conversions.

This module provides safe conversion functions to handle the mismatch between
SQLAlchemy Column types (e.g., Column[UUID]) and Python native types (e.g., UUID).
This is necessary when passing model properties to functions that expect Python types.
"""

from typing import Any, Optional
from uuid import UUID


def to_uuid(value: Any) -> Optional[UUID]:
    """
    Safely convert SQLAlchemy Column or any value to Python UUID (nullable).

    This function handles the conversion from SQLAlchemy Column[UUID] to Python UUID,
    which is necessary when passing model properties to service methods or comparing
    UUID values.

    Args:
        value: Can be Column[UUID], UUID, str, or None

    Returns:
        Python UUID object or None if input is None

    Examples:
        >>> # For optional UUIDs
        >>> user_id = to_uuid(optional_user_id)
        >>>
        >>> # In comparisons
        >>> if to_uuid(task.family_id) == to_uuid(current_user.family_id):
        ...     # Safe comparison
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def to_uuid_required(value: Any) -> UUID:
    """
    Convert SQLAlchemy Column or any value to Python UUID (non-nullable).

    Use this when the UUID is required and should never be None.
    This is common for authenticated user IDs and family IDs.

    Args:
        value: Can be Column[UUID], UUID, or str (must not be None)

    Returns:
        Python UUID object

    Raises:
        ValueError: If value is None or cannot be converted to UUID

    Examples:
        >>> # For required UUIDs like current_user.id or current_user.family_id
        >>> user_id = to_uuid_required(current_user.id)
        >>> family_id = to_uuid_required(current_user.family_id)
    """
    if value is None:
        raise ValueError("UUID value is required but got None")
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def safe_bool(value: Any) -> bool:
    """
    Safely convert SQLAlchemy Column[bool] to Python bool.

    SQLAlchemy Column[bool] types can cause issues when used in Python conditionals
    because ColumnElement[bool].__bool__ returns NoReturn. This function provides
    a safe conversion.

    Args:
        value: Can be Column[bool], bool, or any truthy value

    Returns:
        Python bool (True or False)

    Examples:
        >>> # Instead of direct conditionals
        >>> if safe_bool(task.is_active):
        ...     # Safe to use in Python code
        >>>
        >>> # Or in filters
        >>> is_default = safe_bool(task.is_default)
    """
    return bool(value)


def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert SQLAlchemy Column[int] to Python int.

    Args:
        value: Can be Column[int], int, or any numeric value
        default: Default value to return if conversion fails

    Returns:
        Python int

    Examples:
        >>> points = safe_int(user.points)
        >>> age = safe_int(user.age, default=0)
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """
    Safely convert SQLAlchemy Column[str] to Python str.

    Args:
        value: Can be Column[str], str, or any value
        default: Default value to return if value is None

    Returns:
        Python str

    Examples:
        >>> name = safe_str(user.name)
        >>> email = safe_str(user.email)
    """
    if value is None:
        return default
    return str(value)
