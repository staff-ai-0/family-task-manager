"""Request-ID correlation (WS-EXH).

Pure-ASGI middleware + logging plumbing so every log line and every error
response can be tied back to a single request:

- ``RequestIDMiddleware`` accepts an inbound ``X-Request-ID`` header (or mints
  a uuid4), stashes it in ``scope["state"]`` (→ ``request.state.request_id``)
  and a :class:`~contextvars.ContextVar`, and echoes it back as an
  ``X-Request-ID`` response header.
- ``RequestIDLogFilter`` injects the current id into every log record so the
  ``%(request_id)s`` token in the logging format resolves everywhere.

Deliberately dependency-free (stdlib only, raw ASGI — no BaseHTTPMiddleware,
so SSE/streaming responses pass through unbuffered).
"""

import logging
import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = b"x-request-id"

# Cap + charset guard on inbound ids: they land verbatim in logs and response
# headers, so strip anything that could smuggle formatting/log noise.
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._\-]")
_MAX_ID_LEN = 64

_DEFAULT_ID = "-"

request_id_ctx: ContextVar[str] = ContextVar("request_id", default=_DEFAULT_ID)


def get_request_id() -> str:
    """Current request id, or '-' outside a request context."""
    return request_id_ctx.get()


class RequestIDLogFilter(logging.Filter):
    """Stamp ``record.request_id`` on every record passing through a handler.

    Attach to logging *handlers* (not loggers) so propagated records from any
    module — including third-party libs — pick up the id.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def _sanitize(raw: str) -> str:
    cleaned = _SAFE_ID_RE.sub("", raw.strip())[:_MAX_ID_LEN]
    return cleaned


class RequestIDMiddleware:
    """Assign/propagate a per-request correlation id.

    Note: the contextvar is intentionally NOT reset in a ``finally`` — the
    catch-all exception handler runs *above* this middleware (in Starlette's
    ServerErrorMiddleware) and still needs the id after the exception has
    propagated through us. Each request task gets a fresh context under
    uvicorn, so there is no cross-request leakage in production.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = ""
        for key, value in scope.get("headers") or ():
            if key.lower() == REQUEST_ID_HEADER:
                rid = _sanitize(value.decode("latin-1"))
                break
        if not rid:
            rid = uuid.uuid4().hex

        # request.state is backed by scope["state"] (Starlette ≥0.27), so the
        # id is visible to routes, dependencies AND exception handlers that
        # re-wrap the same scope.
        scope.setdefault("state", {})["request_id"] = rid
        request_id_ctx.set(rid)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                if not any(k.lower() == REQUEST_ID_HEADER for k, _ in headers):
                    headers.append((REQUEST_ID_HEADER, rid.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_request_id)
