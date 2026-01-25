"""
Global exception handlers for FastAPI application.
Eliminates the need for try-catch blocks in route handlers.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from typing import Dict, Any

from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
    UnauthorizedException,
    InsufficientPointsError,
    ConsequenceActiveError,
    TaskAlreadyCompletedError,
)


def create_error_response(
    status_code: int, message: str, error_type: str, details: Dict[str, Any] = None
) -> JSONResponse:
    """Create standardized error response"""
    content = {"error": error_type, "message": message, "status_code": status_code}
    if details:
        content["details"] = details

    return JSONResponse(status_code=status_code, content=content)


async def not_found_handler(request: Request, exc: NotFoundException) -> JSONResponse:
    """Handle 404 Not Found errors"""
    return create_error_response(
        status_code=status.HTTP_404_NOT_FOUND, message=str(exc), error_type="not_found"
    )


async def validation_handler(
    request: Request, exc: ValidationException
) -> JSONResponse:
    """Handle 400 Bad Request validation errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="validation_error",
    )


async def forbidden_handler(request: Request, exc: ForbiddenException) -> JSONResponse:
    """Handle 403 Forbidden errors"""
    return create_error_response(
        status_code=status.HTTP_403_FORBIDDEN, message=str(exc), error_type="forbidden"
    )


async def unauthorized_handler(
    request: Request, exc: UnauthorizedException
) -> JSONResponse:
    """Handle 401 Unauthorized errors"""
    return create_error_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        message=str(exc),
        error_type="unauthorized",
        details={"www_authenticate": "Bearer"},
    )


async def insufficient_points_handler(
    request: Request, exc: InsufficientPointsError
) -> JSONResponse:
    """Handle insufficient points errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="insufficient_points",
    )


async def consequence_active_handler(
    request: Request, exc: ConsequenceActiveError
) -> JSONResponse:
    """Handle active consequence restriction errors"""
    return create_error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        message=str(exc),
        error_type="consequence_active",
    )


async def task_already_completed_handler(
    request: Request, exc: TaskAlreadyCompletedError
) -> JSONResponse:
    """Handle task already completed errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="task_already_completed",
    )


def register_exception_handlers(app):
    """Register all exception handlers with FastAPI app"""
    app.add_exception_handler(NotFoundException, not_found_handler)
    app.add_exception_handler(ValidationException, validation_handler)
    app.add_exception_handler(ForbiddenException, forbidden_handler)
    app.add_exception_handler(UnauthorizedException, unauthorized_handler)
    app.add_exception_handler(InsufficientPointsError, insufficient_points_handler)
    app.add_exception_handler(ConsequenceActiveError, consequence_active_handler)
    app.add_exception_handler(TaskAlreadyCompletedError, task_already_completed_handler)
