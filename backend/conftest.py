"""Top-level conftest.py — loaded by pytest BEFORE tests/conftest.py.

Sets environment variables that must be present before app.main is imported
(route registration is conditional on settings values read at import time).
"""

import os

# The external /mcp HTTP transport is OFF by default (safe prod default).
# Explicitly enable it for the test suite so that tests/mcp/test_http_transport.py
# and tests/mcp/test_restricted_role.py can exercise the mounted route.
# Production sets this via JARVIS_MCP_HTTP_ENABLED=true in its .env.
os.environ.setdefault("JARVIS_MCP_HTTP_ENABLED", "true")
