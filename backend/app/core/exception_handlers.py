"""
Global exception handlers for FastAPI application.
Eliminates the need for try-catch blocks in route handlers.
"""

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional

from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
    UnauthorizedException,
    InsufficientPointsError,
    ConsequenceActiveError,
    TaskAlreadyCompletedError,
)
from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)


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


def _resolve_user_id(request: Request) -> Optional[str]:
    """Best-effort user id for error correlation. Never raises.

    Order: (1) anything a dependency stashed on ``request.state``;
    (2) the ``sub`` claim of a bearer access token (most API routes);
    (3) the OAuth session cookie used by ``get_optional_user``.
    """
    try:
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return str(user_id)

        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            from app.core.security import decode_token

            return decode_token(auth[7:], expected_type="access").get("sub")

        return request.cookies.get("user_id")
    except Exception:
        return None


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for anything no domain handler claimed (WS-EXH).

    Logs the full traceback with method + path + user_id + request_id, and
    returns an opaque JSON 500 — ``str(exc)`` must NEVER reach the client.

    Sentry: Starlette's ServerErrorMiddleware re-raises ``exc`` after this
    handler's response is sent (verified against starlette 0.41.3), so the
    Sentry ASGI wrapper installed by ``sentry_sdk.init`` (outermost) still
    captures the exception — no explicit ``capture_exception`` needed here.

    Response note: this runs in ServerErrorMiddleware, ABOVE all user
    middleware, so RequestIDMiddleware's header injection does not apply —
    the handler sets ``X-Request-ID`` itself.
    """
    request_id = get_request_id()
    state_rid = (request.scope.get("state") or {}).get("request_id")
    if state_rid:
        request_id = state_rid

    logger.error(
        "Unhandled exception: %s %s (user_id=%s, request_id=%s)",
        request.method,
        request.url.path,
        _resolve_user_id(request),
        request_id,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id},
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
    # Catch-all: keyed on `Exception`, Starlette wires it into
    # ServerErrorMiddleware — it cannot shadow the specific handlers above or
    # slowapi's RateLimitExceeded handler, which all resolve first in the
    # inner ExceptionMiddleware.
    app.add_exception_handler(Exception, unhandled_exception_handler)
