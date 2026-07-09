"""Jarvis copilot service (W6.1 + W6.8).

Conversational parental coach. Reuses the LiteLLM proxy (same model alias
as the receipt scanner) for centralized spend tracking. Each call:

1. Pulls fresh family context (PUP score + today's task summary + pet states).
2. Loads last N chat turns for the family.
3. Builds an OpenAI-format messages array with a load-bearing system prompt.
4. Calls LiteLLM with tool definitions sourced from the in-memory MCP server.
5. Multi-hop tool execution (max ``MAX_TOOL_HOPS``); destructive ops are
   HITL-gated (queued as JarvisPendingAction + ``confirm`` SSE event) instead
   of executed inline.
6. Persists both the user's message and the reply.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, List
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from mcp.shared.memory import create_connected_server_and_client_session
from openai import OpenAI
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.metrics import record_llm_call
from app.mcp.confirm import is_destructive, summarize
from app.mcp.context import McpContext, use_context
from app.mcp.openai_bridge import mcp_tools_to_openai
from app.mcp.server import server as mcp_server
from app.models.jarvis_message import JarvisMessage
from app.models.kid_pet import KidPet
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.user import User
from app.services.analytics_service import AnalyticsService
from app.services.budget.receipt_scanner_service import LLM_TIMEOUT, RECEIPT_MODEL
from app.services.jarvis_pending_action_service import PendingActionService


# Jarvis model alias — defaults to receipt scanner's claude-haiku for
# shared LiteLLM budget. Override via JARVIS_MODEL env var.
CHAT_MODEL = settings.JARVIS_MODEL or RECEIPT_MODEL

SYSTEM_BASE = (
    "You are Jarvis, a calm, practical family-routines copilot. You help "
    "the parent see what's going on across chores, gigs, calendar, and "
    "kids' moods. Be concise — 2-4 sentences, then a clear next step. "
    "Avoid platitudes. If you don't know, say so."
)

LANG_NAMES = {"en": "English", "es": "Spanish"}

# Localized fallback when the model returns nothing useful.
_EMPTY_REPLY = {
    "en": "I had nothing useful to say. Try rephrasing?",
    "es": "No tengo nada útil que decir. ¿Puedes reformular?",
}


def _build_system(context_block: str, preferred_lang: str) -> str:
    """System prompt with a hard language directive so Jarvis replies in the
    user's app language from the first turn (not just after they switch)."""
    lang_name = LANG_NAMES.get(preferred_lang, "English")
    return (
        SYSTEM_BASE
        + f"\n\nIMPORTANT: Always respond in {lang_name}, regardless of the "
        "language of the family-state data below or earlier turns."
        + "\n\n"
        + context_block
    )


MAX_HISTORY_TURNS = 12
HISTORY_RETURN_LIMIT = 50
MAX_TOOL_HOPS = 4


async def _mcp_tool_definitions() -> list[dict]:
    """List tools from the in-memory MCP server, in OpenAI tool format.

    Uses the module-global ``mcp_server`` (already built once at import) so we
    never re-register the low-level handlers via ``build_server()``.
    """
    async with create_connected_server_and_client_session(mcp_server) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
    return mcp_tools_to_openai(tools)


async def _mcp_dispatch(
    db: AsyncSession,
    family_id: UUID,
    user_id: UUID,
    role: str,
    name: str,
    args: dict,
) -> dict:
    """Execute a tool through the MCP client, scoped to the family context.

    The MCP server reads family scope only from the bound ``McpContext`` (never
    from client args), preserving the multi-tenant invariant.
    """
    ctx = McpContext(family_id=family_id, user_id=user_id, role=role, db=db)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(mcp_server) as session:
            await session.initialize()
            result = await session.call_tool(name, args or {})
    try:
        return json.loads(result.content[0].text)
    except (IndexError, AttributeError, json.JSONDecodeError):
        return {"ok": False, "error": "tool returned no parseable result"}


class JarvisService:
    @staticmethod
    async def _build_context(db: AsyncSession, family_id: UUID) -> str:
        """Fetch live family state and render it as a system-prompt block."""
        pup = await AnalyticsService.pup_score(db, family_id)
        score = pup["pup_score"]
        label = pup["label"]

        from datetime import date
        today = date.today()
        q = (
            select(
                func.count(TaskAssignment.id).label("total"),
                func.count()
                .filter(TaskAssignment.status == AssignmentStatus.COMPLETED)
                .label("done"),
                func.count()
                .filter(TaskAssignment.status == AssignmentStatus.OVERDUE)
                .label("late"),
            )
            .select_from(TaskAssignment)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == today,
                )
            )
        )
        row = (await db.execute(q)).one()
        tasks_total = int(row.total or 0)
        tasks_done = int(row.done or 0)
        tasks_late = int(row.late or 0)

        pets_q = (
            select(KidPet)
            .join(User, User.id == KidPet.user_id)
            .where(User.family_id == family_id)
        )
        pets = list((await db.execute(pets_q)).scalars().all())
        pet_summary = ", ".join(
            f"{p.name} ({p.status_label})" for p in pets
        ) or "no pets"

        member_lines = "\n".join(
            f"  - {m['name']} ({m['role']}): {m['completion_rate']}% "
            f"done, {m['mandatory_late']} late, {m['gigs_completed']} gigs"
            for m in pup.get("members", [])
        )

        return (
            f"FAMILY STATE (live snapshot):\n"
            f"- PUP Score: {score}/100 ({label})\n"
            f"- Today's tasks: {tasks_done}/{tasks_total} done, {tasks_late} late\n"
            f"- Pets: {pet_summary}\n"
            f"- Members (last 4 weeks):\n{member_lines}\n"
            f"- Notes: {'; '.join(pup.get('notes', [])) or 'none'}"
        )

    @staticmethod
    async def _load_history(
        db: AsyncSession, family_id: UUID, limit: int
    ) -> List[JarvisMessage]:
        q = (
            select(JarvisMessage)
            .where(JarvisMessage.family_id == family_id)
            .order_by(JarvisMessage.created_at.desc())
            .limit(limit)
        )
        rows = list((await db.execute(q)).scalars().all())
        rows.reverse()
        return rows

    @staticmethod
    async def _execute_tool(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        name: str,
        args: dict,
        role: str = "PARENT",
    ) -> dict:
        """Backwards-compat shim — dispatches through the in-memory MCP client."""
        return await _mcp_dispatch(db, family_id, user_id, role, name, args)

    @staticmethod
    async def _today_message_count(
        db: AsyncSession, family_id: UUID
    ) -> int:
        """Count user→assistant pairs sent today (UTC). Cheap throttle."""
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        q = (
            select(func.count())
            .select_from(JarvisMessage)
            .where(
                and_(
                    JarvisMessage.family_id == family_id,
                    JarvisMessage.role == "user",
                    JarvisMessage.created_at >= cutoff,
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def chat_stream(
        family_id: UUID,
        user_id: UUID,
        message: str,
        model: str | None = None,
        preferred_lang: str = "en",
    ):
        """Public SSE generator — owns a short-lived DB session that is closed on
        completion AND on client disconnect (the async-with __aexit__ runs on
        GeneratorExit), so an abandoned stream never leaks a pooled connection
        ``idle in transaction``. Delegates to _chat_stream_inner.
        """
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            async for evt in JarvisService._chat_stream_inner(
                db, family_id, user_id, message, model, preferred_lang
            ):
                yield evt

    @staticmethod
    async def _chat_stream_inner(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        message: str,
        model: str | None = None,
        preferred_lang: str = "en",
    ):
        """Async generator yielding SSE event lines.

        Events:
          - event: thinking → {}                        (immediately)
          - event: tool     → {name, ok}                (after each non-destructive tool hop)
          - event: confirm  → {action_id, tool, summary, params}
                              (destructive tool queued for human approval; NOT executed)
          - event: reply    → {reply, actions, message_id}
          - event: error    → {detail}                  (on failure)
          - event: done     → {}                        (sentinel)

        Tools are sourced from the in-memory MCP server. Destructive ops
        (delete / money) are not executed inline: a JarvisPendingAction is
        created and a ``confirm`` event is emitted for the parent to approve
        out-of-band via POST /api/jarvis/actions/{id}/approve.
        """
        try:
            if not settings.LITELLM_API_KEY:
                raise ValidationError("Jarvis not configured. Set LITELLM_API_KEY.")
            msg = (message or "").strip()
            if not msg:
                raise ValidationError("Message is empty.")
            cap = int(settings.JARVIS_DAILY_MESSAGE_CAP or 0)
            if cap > 0:
                if await JarvisService._today_message_count(db, family_id) >= cap:
                    raise ValidationError(
                        f"Daily Jarvis cap reached ({cap}). Try again tomorrow."
                    )

            yield "event: thinking\ndata: {}\n\n"

            history = await JarvisService._load_history(
                db, family_id, limit=MAX_HISTORY_TURNS
            )
            context_block = await JarvisService._build_context(db, family_id)
            msgs: list[dict[str, Any]] = [
                {"role": "system", "content": _build_system(context_block, preferred_lang)}
            ]
            for h in history:
                if h.role in ("user", "assistant"):
                    msgs.append({"role": h.role, "content": h.content})
            msgs.append({"role": "user", "content": msg})

            client = OpenAI(
                base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
                api_key=settings.LITELLM_API_KEY,
                timeout=LLM_TIMEOUT,  # connect fails fast; read capped at 60s
            )

            actions_taken: list[str] = []
            reply = ""
            effective_model = model or CHAT_MODEL
            tool_defs = await _mcp_tool_definitions()

            for hop in range(MAX_TOOL_HOPS + 1):
                # Sync OpenAI client: offload each hop to a worker thread so a
                # slow provider can't stall the event loop (SSE heartbeats and
                # all other requests share it). This call is NOT stream=True —
                # the SSE framing is produced by this generator, so a plain
                # threadpool offload preserves event ordering exactly.
                record_llm_call()  # best-effort outbound-LLM counter
                completion = await run_in_threadpool(
                    lambda: client.chat.completions.create(
                        model=effective_model,
                        max_tokens=512,
                        messages=msgs,
                        tools=tool_defs,
                        tool_choice="auto",
                    )
                )
                choice = completion.choices[0].message
                tool_calls = getattr(choice, "tool_calls", None) or []

                if tool_calls and hop < MAX_TOOL_HOPS:
                    msgs.append({
                        "role": "assistant",
                        "content": choice.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    })
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        name = tc.function.name

                        if is_destructive(name):
                            # Do NOT execute. Queue for human approval and emit a
                            # confirm event. The LLM's tool slot is filled with a
                            # "pending" acknowledgement so the hop loop can resolve.
                            ctx = McpContext(
                                family_id=family_id, user_id=user_id,
                                role="PARENT", db=db,
                            )
                            pa = await PendingActionService.create(
                                db, ctx, name, args
                            )
                            actions_taken.append(f"{name}(pending)")
                            yield (
                                "event: confirm\ndata: "
                                + json.dumps({
                                    "action_id": str(pa.id),
                                    "tool": name,
                                    "summary": pa.summary,
                                    "params": args,
                                })
                                + "\n\n"
                            )
                            msgs.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps({
                                    "ok": True,
                                    "pending": True,
                                    "action_id": str(pa.id),
                                    "note": "Queued for parent approval; not executed.",
                                }),
                            })
                            continue

                        result = await _mcp_dispatch(
                            db, family_id, user_id, "PARENT", name, args
                        )
                        ok = bool(result.get("ok"))
                        actions_taken.append(
                            f"{name}({'ok' if ok else 'err'})"
                        )
                        yield (
                            "event: tool\ndata: "
                            + json.dumps({"name": name, "ok": ok})
                            + "\n\n"
                        )
                        msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        })
                    continue

                reply = (choice.content or "").strip()
                break

            if not reply:
                reply = _EMPTY_REPLY.get(preferred_lang, _EMPTY_REPLY["en"])

            user_row = JarvisMessage(
                family_id=family_id, user_id=user_id, role="user", content=msg
            )
            bot_row = JarvisMessage(
                family_id=family_id,
                user_id=None,
                role="assistant",
                content=reply
                + (
                    f"\n\n[actions: {', '.join(actions_taken)}]"
                    if actions_taken else ""
                ),
            )
            db.add(user_row)
            db.add(bot_row)
            await db.commit()
            await db.refresh(bot_row)
            yield (
                "event: reply\ndata: "
                + json.dumps({
                    "reply": reply,
                    "actions": actions_taken,
                    "message_id": str(bot_row.id),
                    "model": effective_model,
                })
                + "\n\n"
            )
        except ValidationError as exc:
            yield "event: error\ndata: " + json.dumps({"detail": str(exc)}) + "\n\n"
        except Exception as exc:
            yield "event: error\ndata: " + json.dumps({"detail": f"Jarvis failed: {exc}"}) + "\n\n"
        finally:
            yield "event: done\ndata: {}\n\n"

    @staticmethod
    async def chat(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        message: str,
        model: str | None = None,
        preferred_lang: str = "en",
    ) -> dict:
        if not settings.LITELLM_API_KEY:
            raise ValidationError(
                "Jarvis not configured. Set LITELLM_API_KEY."
            )
        message = (message or "").strip()
        if not message:
            raise ValidationError("Message is empty.")

        cap = int(settings.JARVIS_DAILY_MESSAGE_CAP or 0)
        if cap > 0:
            sent_today = await JarvisService._today_message_count(db, family_id)
            if sent_today >= cap:
                raise ValidationError(
                    f"Daily Jarvis cap reached ({cap}). Try again tomorrow."
                )

        history = await JarvisService._load_history(
            db, family_id, limit=MAX_HISTORY_TURNS
        )
        context_block = await JarvisService._build_context(db, family_id)

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": _build_system(context_block, preferred_lang)}
        ]
        for h in history:
            if h.role in ("user", "assistant"):
                msgs.append({"role": h.role, "content": h.content})
        msgs.append({"role": "user", "content": message})

        client = OpenAI(
            base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
            api_key=settings.LITELLM_API_KEY,
            timeout=LLM_TIMEOUT,  # connect fails fast; read capped at 60s
        )

        actions_taken: list[str] = []
        reply = ""
        effective_model = model or CHAT_MODEL
        tool_defs = await _mcp_tool_definitions()

        for hop in range(MAX_TOOL_HOPS + 1):
            try:
                # Sync client — offload to a worker thread per hop so the
                # event loop stays free; client timeout bounds the wait.
                record_llm_call()  # best-effort outbound-LLM counter
                completion = await run_in_threadpool(
                    lambda: client.chat.completions.create(
                        model=effective_model,
                        max_tokens=512,
                        messages=msgs,
                        tools=tool_defs,
                        tool_choice="auto",
                    )
                )
            except Exception as exc:
                raise ValidationError(f"Jarvis chat failed: {exc}")

            choice = completion.choices[0].message
            tool_calls = getattr(choice, "tool_calls", None) or []

            if tool_calls and hop < MAX_TOOL_HOPS:
                msgs.append({
                    "role": "assistant",
                    "content": choice.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                })
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    name = tc.function.name

                    if is_destructive(name):
                        # Queue for human approval; do not execute inline.
                        ctx = McpContext(
                            family_id=family_id, user_id=user_id,
                            role="PARENT", db=db,
                        )
                        pa = await PendingActionService.create(db, ctx, name, args)
                        actions_taken.append(f"{name}(pending)")
                        msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "ok": True,
                                "pending": True,
                                "action_id": str(pa.id),
                                "note": "Queued for parent approval; not executed.",
                            }),
                        })
                        continue

                    result = await _mcp_dispatch(
                        db, family_id, user_id, "PARENT", name, args
                    )
                    actions_taken.append(
                        f"{name}({'ok' if result.get('ok') else 'err'})"
                    )
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    })
                continue

            reply = (choice.content or "").strip()
            break

        if not reply:
            reply = _EMPTY_REPLY.get(preferred_lang, _EMPTY_REPLY["en"])

        user_msg = JarvisMessage(
            family_id=family_id, user_id=user_id, role="user", content=message
        )
        bot_msg = JarvisMessage(
            family_id=family_id,
            user_id=None,
            role="assistant",
            content=reply
            + (f"\n\n[actions: {', '.join(actions_taken)}]" if actions_taken else ""),
        )
        db.add(user_msg)
        db.add(bot_msg)
        await db.commit()
        await db.refresh(bot_msg)
        return {
            "reply": reply,
            "actions": actions_taken,
            "message_id": str(bot_msg.id),
        }

    @staticmethod
    async def list_history(
        db: AsyncSession, family_id: UUID, limit: int = HISTORY_RETURN_LIMIT
    ) -> List[JarvisMessage]:
        return await JarvisService._load_history(db, family_id, limit=limit)

    @staticmethod
    async def clear_history(db: AsyncSession, family_id: UUID) -> int:
        from sqlalchemy import delete as sql_delete
        result = await db.execute(
            sql_delete(JarvisMessage).where(JarvisMessage.family_id == family_id)
        )
        await db.commit()
        return result.rowcount or 0
