"""In-process MCP client session over memory streams.

Replaces ``mcp.shared.memory.create_connected_server_and_client_session``,
which the SDK removed in mcp 2.0. It was a test convenience upstream, but we
depend on it in application code too: ``jarvis_service`` speaks to our own MCP
server in-process rather than over HTTP, so the Jarvis copilot and the tool
registry can never drift apart.

Keeping our own copy means the next SDK reshuffle is a one-file change here
instead of a change in eleven call sites.

The building blocks it composes (``create_client_server_memory_streams``,
``ClientSession``, ``Server.run``) are all still public in 2.0 — only the
convenience wrapper went away.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import anyio
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.shared.memory import create_client_server_memory_streams


@asynccontextmanager
async def connected_mcp_session(
    server: Server[Any],
    *,
    raise_exceptions: bool = False,
) -> AsyncGenerator[ClientSession, None]:
    """Yield a ``ClientSession`` already connected to ``server`` and initialized.

    Both halves run in this process, wired together by in-memory streams — no
    sockets, no HTTP, no transport auth. Callers get a session that is ready to
    use; ``initialize()`` has already been awaited (calling it again is
    harmless, and several call sites do).

    Args:
        server: the low-level MCP server to serve on the other end.
        raise_exceptions: propagate handler exceptions instead of turning them
            into JSON-RPC error responses. Useful in tests that assert on a
            failure; leave False in application code so a failing tool degrades
            to an error result rather than tearing down the request.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            # Spawned inside the caller's context, so the server task inherits
            # whatever McpContext is bound — that binding is what scopes every
            # tool to one family. Do not hoist this into a longer-lived task
            # group: contextvars are captured at spawn time, so a server task
            # started outside the request would see no family scope at all.
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                    raise_exceptions=raise_exceptions,
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                ) as client_session:
                    await client_session.initialize()
                    yield client_session
            finally:
                # The server task has no other stop condition; without this the
                # task group would block forever on exit.
                tg.cancel_scope.cancel()
