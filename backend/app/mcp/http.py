"""Streamable-HTTP ASGI mount for the family-scoped MCP server.

Exposes ``build_server()`` over HTTP at ``/mcp`` behind per-family bearer auth.

Auth model (multi-tenant invariant): the client supplies *only* a bearer token
(``Authorization: Bearer mcp_...``). The token resolves to a single family via
``TokenService``; family scope comes exclusively from the resolved token —
never from request body / args. A fresh ``AsyncSessionLocal()`` is opened per
request and an ``McpContext`` (user_id=None, role="MCP_TOKEN") is bound for the
downstream tool call. Missing / invalid / revoked tokens get a 401.

Transport: the MCP streamable-HTTP transport runs in *stateless + json_response*
mode. json_response avoids the SSE response path (and thus the sse-starlette /
starlette version skew) — each JSON-RPC POST gets a single JSON reply.

Context propagation: ``dispatch_tool`` reads the bound family context from a
``contextvars.ContextVar``. The transport runs ``server.run`` in a child task,
which is spawned *inside* the ``use_context`` block so it inherits the bound
context (contextvars are copied to a task at spawn time).
"""

import logging

import anyio
from sqlalchemy import text
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match
from starlette.types import Receive, Scope, Send

from mcp.server.streamable_http import StreamableHTTPServerTransport

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.mcp.context import McpContext, use_context
from app.mcp.server import build_server
from app.services.jarvis_mcp_token_service import TokenService

logger = logging.getLogger(__name__)

# Built once at import time (registers builtin tools). Stateless transports are
# created per request; this server instance only holds the tool registry.
_server = build_server()


def _extract_bearer(scope: Scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"authorization":
            raw = value.decode("latin-1")
            if raw.lower().startswith("bearer "):
                return raw[7:].strip()
            continue  # non-Bearer header; keep looking
    return None


async def _unauthorized(scope: Scope, receive: Receive, send: Send) -> None:
    resp = JSONResponse({"error": "unauthorized"}, status_code=401)
    await resp(scope, receive, send)


async def mcp_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI app mounted at ``/mcp``.

    Authenticates the bearer token, binds a family-scoped ``McpContext``, then
    delegates the JSON-RPC exchange to a per-request streamable-HTTP transport.
    """
    if scope["type"] != "http":
        await _unauthorized(scope, receive, send)
        return

    token = _extract_bearer(scope)
    if not token:
        await _unauthorized(scope, receive, send)
        return

    # Resolve the token on its own short-lived session so a SET ROLE on the
    # request session can never restrict the lookup of users-adjacent tables.
    # An auth lookup that fails for any reason is treated as unauthenticated
    # (fail-closed) rather than surfacing a 500 through the transport.
    try:
        async with AsyncSessionLocal() as auth_session:
            row = await TokenService.resolve(auth_session, token)
    except Exception:
        logger.exception("MCP token resolution failed")
        row = None
    if row is None:
        await _unauthorized(scope, receive, send)
        return

    family_id = row.family_id

    async with AsyncSessionLocal() as session:
        if settings.JARVIS_MCP_DB_ROLE:
            await session.execute(
                text("SET ROLE " + _quote_ident(settings.JARVIS_MCP_DB_ROLE))
            )
        else:
            logger.warning(
                "JARVIS_MCP_DB_ROLE unset — /mcp session runs with the full app DB role"
            )

        ctx = McpContext(
            family_id=family_id,
            user_id=None,
            role="MCP_TOKEN",
            db=session,
        )
        async with use_context(ctx):
            transport = StreamableHTTPServerTransport(
                mcp_session_id=None,
                is_json_response_enabled=True,
            )
            async with transport.connect() as (read_stream, write_stream):
                async with anyio.create_task_group() as tg:
                    # Spawned inside use_context → inherits the bound family ctx.
                    tg.start_soon(
                        _run_server, read_stream, write_stream
                    )
                    await transport.handle_request(scope, receive, send)
                    tg.cancel_scope.cancel()


async def _run_server(read_stream, write_stream) -> None:
    try:
        await _server.run(
            read_stream,
            write_stream,
            _server.create_initialization_options(),
            stateless=True,
        )
    except anyio.get_cancelled_exc_class():
        raise
    except Exception:  # pragma: no cover - defensive; surfaced via transport
        logger.exception("MCP stateless session crashed")


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier for use in ``SET ROLE``.

    ``SET ROLE`` does not accept bind parameters, so the role name is embedded
    directly. It comes from app config (not a request), but we still quote it
    defensively to neutralise any embedded quote.
    """
    return '"' + name.replace('"', '""') + '"'


class ExactASGIRoute(BaseRoute):
    """Serve a raw ASGI app at a single exact path with no slash-redirect.

    A plain ``Mount`` 307-redirects the bare path (``/mcp`` → ``/mcp/``) under the
    app router's ``redirect_slashes``; MCP clients POST to the exact ``/mcp`` URL
    and do not follow that redirect. ``Route`` would wrap the callable as a
    request/response endpoint. This route matches only the exact path and hands
    the untouched ASGI scope to the app.
    """

    def __init__(self, path: str, app) -> None:
        self.path = path
        self.app = app

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and scope.get("path") == self.path:
            return Match.FULL, {"endpoint": self.app}
        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)

    def url_path_for(self, name: str, /, **path_params):  # pragma: no cover
        raise NotImplementedError
