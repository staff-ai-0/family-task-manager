"""Guard against the SSE connection-leak regression.

Long-lived SSE generators (family chat, DM, Jarvis stream) must NOT take a
request-scoped Depends(get_db) session — that pins a pooled connection
idle-in-transaction for the whole stream, exhausting the pool (size 30) and
causing app-wide 502s. They must own short-lived sessions internally. This
guard fails if a session param sneaks back as the first argument.
"""
import inspect

from app.services.family_chat_service import FamilyChatService
from app.services.dm_service import DMService
from app.services.jarvis_service import JarvisService


def _first_param(func) -> str:
    params = list(inspect.signature(func).parameters)
    return params[0] if params else ""


def test_family_chat_stream_has_no_session_param():
    assert _first_param(FamilyChatService.stream_messages) == "family_id"


def test_dm_stream_has_no_session_param():
    assert _first_param(DMService.stream_messages) == "thread_id"


def test_jarvis_public_stream_has_no_session_param():
    # Public chat_stream owns its own session; first arg must not be a db handle.
    assert _first_param(JarvisService.chat_stream) == "family_id"
