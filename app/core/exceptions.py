"""Custom exceptions for the application"""


class FamilyAppException(Exception):
    """Base exception for all family app errors"""
    pass


class NotFoundException(FamilyAppException):
    """Raised when a resource is not found"""
    pass


class PermissionDeniedError(FamilyAppException):
    """Raised when user doesn't have permission for an operation"""
    pass


class ValidationError(FamilyAppException):
    """Raised when data validation fails"""
    pass


class InsufficientPointsError(FamilyAppException):
    """Raised when user doesn't have enough points"""
    pass


class ConsequenceActiveError(FamilyAppException):
    """Raised when trying to perform action while under consequence"""
    pass


class TaskAlreadyCompletedError(FamilyAppException):
    """Raised when trying to complete an already completed task"""
    pass


class FamilyNotFoundError(NotFoundException):
    """Raised when family is not found"""
    pass


class UserNotFoundError(NotFoundException):
    """Raised when user is not found"""
    pass
