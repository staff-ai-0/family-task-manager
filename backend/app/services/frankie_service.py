"""Frankie copilot service (W6.1 + W6.8).

Conversational parental coach. Reuses the LiteLLM proxy (same model alias
as the receipt scanner) for centralized spend tracking. Each call:

1. Pulls fresh family context (PUP score + today's task summary + pet states).
2. Loads last N chat turns for the family.
3. Builds an OpenAI-format messages array with a load-bearing system prompt.
4. Calls LiteLLM with tool definitions from ``frankie_tools.REGISTRY``.
5. Multi-hop tool execution (max ``MAX_TOOL_HOPS``).
6. Persists both the user's message and the reply.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, List
from uuid import UUID

from openai import OpenAI
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.frankie_message import FrankieMessage
from app.models.kid_pet import KidPet
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.user import User
from app.services.analytics_service import AnalyticsService
from app.services.budget.receipt_scanner_service import RECEIPT_MODEL
from app.services.frankie_tools import REGISTRY, dispatch, tool_definitions


# Frankie model alias — defaults to receipt scanner's claude-haiku for
# shared LiteLLM budget. Override via FRANKIE_MODEL env var.
CHAT_MODEL = settings.FRANKIE_MODEL or RECEIPT_MODEL

SYSTEM_BASE = (
    "You are Jarvis, a calm, practical family-routines copilot. You help "
    "the parent see what's going on across chores, gigs, calendar, and "
    "kids' moods. Be concise — 2-4 sentences, then a clear next step. "
    "Avoid platitudes. If you don't know, say so."
)

MAX_HISTORY_TURNS = 12
HISTORY_RETURN_LIMIT = 50
MAX_TOOL_HOPS = 4


# Module-level alias kept for tests that import TOOL_DEFINITIONS directly.
# Source of truth is ``frankie_tools.REGISTRY``.
TOOL_DEFINITIONS: list[dict] = tool_definitions()


class FrankieService:
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
    ) -> List[FrankieMessage]:
        q = (
            select(FrankieMessage)
            .where(FrankieMessage.family_id == family_id)
            .order_by(FrankieMessage.created_at.desc())
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
    ) -> dict:
        """Backwards-compat shim — delegates to the tool registry."""
        return await dispatch(db, family_id, user_id, name, args)

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
            .select_from(FrankieMessage)
            .where(
                and_(
                    FrankieMessage.family_id == family_id,
                    FrankieMessage.role == "user",
                    FrankieMessage.created_at >= cutoff,
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        message: str,
        model: str | None = None,
    ):
        """Async generator yielding SSE event lines.

        Events:
          - event: thinking → {}                        (immediately)
          - event: tool     → {name, ok}                (after each tool hop)
          - event: reply    → {reply, actions, message_id}
          - event: error    → {detail}                  (on failure)
          - event: done     → {}                        (sentinel)

        Tool calls and the final reply still hit the LLM the same way as
        ``chat()`` — this wrapper just splits the timeline into events so
        the UI can show progress instead of a long spinner.
        """
        try:
            if not settings.LITELLM_API_KEY:
                raise ValidationError("Jarvis not configured. Set LITELLM_API_KEY.")
            msg = (message or "").strip()
            if not msg:
                raise ValidationError("Message is empty.")
            cap = int(settings.FRANKIE_DAILY_MESSAGE_CAP or 0)
            if cap > 0:
                if await FrankieService._today_message_count(db, family_id) >= cap:
                    raise ValidationError(
                        f"Daily Jarvis cap reached ({cap}). Try again tomorrow."
                    )

            yield "event: thinking\ndata: {}\n\n"

            history = await FrankieService._load_history(
                db, family_id, limit=MAX_HISTORY_TURNS
            )
            context_block = await FrankieService._build_context(db, family_id)
            msgs: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_BASE + "\n\n" + context_block}
            ]
            for h in history:
                if h.role in ("user", "assistant"):
                    msgs.append({"role": h.role, "content": h.content})
            msgs.append({"role": "user", "content": msg})

            client = OpenAI(
                base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
                api_key=settings.LITELLM_API_KEY,
            )

            actions_taken: list[str] = []
            reply = ""
            effective_model = model or CHAT_MODEL

            for hop in range(MAX_TOOL_HOPS + 1):
                completion = client.chat.completions.create(
                    model=effective_model,
                    max_tokens=512,
                    messages=msgs,
                    tools=tool_definitions(),
                    tool_choice="auto",
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
                        result = await dispatch(
                            db, family_id, user_id, tc.function.name, args
                        )
                        ok = bool(result.get("ok"))
                        actions_taken.append(
                            f"{tc.function.name}({'ok' if ok else 'err'})"
                        )
                        yield (
                            "event: tool\ndata: "
                            + json.dumps({"name": tc.function.name, "ok": ok})
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
                reply = "I had nothing useful to say. Try rephrasing?"

            user_row = FrankieMessage(
                family_id=family_id, user_id=user_id, role="user", content=msg
            )
            bot_row = FrankieMessage(
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
    ) -> dict:
        if not settings.LITELLM_API_KEY:
            raise ValidationError(
                "Jarvis not configured. Set LITELLM_API_KEY."
            )
        message = (message or "").strip()
        if not message:
            raise ValidationError("Message is empty.")

        cap = int(settings.FRANKIE_DAILY_MESSAGE_CAP or 0)
        if cap > 0:
            sent_today = await FrankieService._today_message_count(db, family_id)
            if sent_today >= cap:
                raise ValidationError(
                    f"Daily Jarvis cap reached ({cap}). Try again tomorrow."
                )

        history = await FrankieService._load_history(
            db, family_id, limit=MAX_HISTORY_TURNS
        )
        context_block = await FrankieService._build_context(db, family_id)

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_BASE + "\n\n" + context_block}
        ]
        for h in history:
            if h.role in ("user", "assistant"):
                msgs.append({"role": h.role, "content": h.content})
        msgs.append({"role": "user", "content": message})

        client = OpenAI(
            base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
            api_key=settings.LITELLM_API_KEY,
        )

        actions_taken: list[str] = []
        reply = ""
        effective_model = model or CHAT_MODEL

        for hop in range(MAX_TOOL_HOPS + 1):
            try:
                completion = client.chat.completions.create(
                    model=effective_model,
                    max_tokens=512,
                    messages=msgs,
                    tools=tool_definitions(),
                    tool_choice="auto",
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
                    result = await dispatch(
                        db, family_id, user_id, tc.function.name, args
                    )
                    actions_taken.append(
                        f"{tc.function.name}({'ok' if result.get('ok') else 'err'})"
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
            reply = "I had nothing useful to say. Try rephrasing?"

        user_msg = FrankieMessage(
            family_id=family_id, user_id=user_id, role="user", content=message
        )
        bot_msg = FrankieMessage(
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
    ) -> List[FrankieMessage]:
        return await FrankieService._load_history(db, family_id, limit=limit)

    @staticmethod
    async def clear_history(db: AsyncSession, family_id: UUID) -> int:
        from sqlalchemy import delete as sql_delete
        result = await db.execute(
            sql_delete(FrankieMessage).where(FrankieMessage.family_id == family_id)
        )
        await db.commit()
        return result.rowcount or 0
