# Jarvis Full-PG MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Jarvis copilot full, family-scoped CRUD over the app's activity domains via a real in-repo MCP server, with destructive ops gated by in-chat confirmation and an HTTP transport for external clients.

**Architecture:** A low-level `mcp.server.Server` ("family-pg") in `backend/app/mcp/`, fed by a declarative `EntitySpec` registry. Each tool wraps an existing app Service class (no raw SQL). Family context flows through a `ContextVar` set by the caller — Jarvis (in-memory MCP client) injects it from the JWT; the mounted HTTP `/mcp` transport injects it from a per-family bearer token. Destructive/money tools called by the LLM are not executed inline — they create a `jarvis_pending_action` and emit an SSE `confirm` event for the parent to approve.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async (asyncpg), Alembic, `mcp` Python SDK, pytest (separate test DB on 5435), Astro 5 frontend.

## Global Constraints

- Pin `mcp==1.12.4` in `backend/requirements.txt` (the API used below is the low-level `mcp.server.Server` + `mcp.types`; confirm import paths against the installed version in Task 1).
- Multi-tenant invariant: the MCP server MUST NEVER trust a client-supplied `family_id`. Family scope comes only from the `ContextVar`, set from the JWT (in-app) or the token (HTTP). Any `family_id` field in tool arguments is ignored.
- Every tool routes through an existing app Service class; no raw SQL in tool handlers.
- Excluded domains (no tools, ever): users/members/roles/passwords, subscriptions/PayPal billing.
- TDD: write the failing test first, watch it fail, implement minimal, watch it pass, commit. Tests run against the test DB via the existing `conftest.py` fixtures.
- All new SQLAlchemy models are family-scoped with `family_id` non-nullable FK to `families.id`.
- Run backend tests with: `podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -v` (local dev). If the container is not running, `cd backend && pytest <path> -v` inside the venv with the test DB env.
- Commit message footer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Phase 0 — MCP server skeleton + family context

### Task 1: Stand up the MCP server with one `ping` tool + in-memory smoke test

**Files:**
- Modify: `backend/requirements.txt` (add `mcp==1.12.4`)
- Create: `backend/app/mcp/__init__.py`
- Create: `backend/app/mcp/server.py`
- Test: `backend/tests/mcp/test_server_smoke.py`

**Interfaces:**
- Produces: `build_server() -> mcp.server.Server` and module-global `server`; a `register_registry(server)` hook (filled in Task 5). The low-level handlers `list_tools()` / `call_tool(name, arguments)` are registered inside `build_server()`.

- [ ] **Step 1: Add the dependency**

In `backend/requirements.txt` add a line:
```
mcp==1.12.4
```
Install it: `cd backend && pip install mcp==1.12.4` (or rebuild the container image).

- [ ] **Step 2: Write the failing smoke test**

`backend/tests/mcp/test_server_smoke.py`:
```python
import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp.server import build_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_ping_tool_roundtrip():
    server = build_server()
    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert "ping" in [t.name for t in tools.tools]
        result = await session.call_tool("ping", {})
        payload = json.loads(result.content[0].text)
        assert payload == {"ok": True, "pong": True}
```

- [ ] **Step 3: Run it, expect failure**

Run: `cd backend && pytest tests/mcp/test_server_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: app.mcp.server`.

- [ ] **Step 4: Implement the server skeleton**

`backend/app/mcp/server.py`:
```python
import json
from mcp.server import Server
from mcp.types import Tool, TextContent

SERVER_NAME = "family-pg"


def build_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="ping",
                description="Health check; returns pong.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "ping":
            return [TextContent(type="text", text=json.dumps({"ok": True, "pong": True}))]
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": f"unknown tool {name}"}))]

    return server


server = build_server()
```
Create empty `backend/app/mcp/__init__.py` and `backend/tests/mcp/__init__.py`.

> If `create_connected_server_and_client_session` is missing in 1.12.4, use the migration-doc client: `from mcp.client import Client` / `async with Client(server) as c: await c.call_tool(...)`. Adjust the test import to whichever the installed version exposes; the tool contract is unchanged.

- [ ] **Step 5: Run it, expect pass**

Run: `cd backend && pytest tests/mcp/test_server_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/requirements.txt backend/app/mcp/ backend/tests/mcp/
git commit -m "feat(mcp): family-pg MCP server skeleton with ping tool

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Family context (`McpContext`) + ContextVar plumbing

**Files:**
- Create: `backend/app/mcp/context.py`
- Test: `backend/tests/mcp/test_context.py`

**Interfaces:**
- Produces:
  - `@dataclass McpContext(family_id: UUID, user_id: UUID | None, role: str, db: AsyncSession)`
  - `current_context: ContextVar[McpContext | None]`
  - `def get_context() -> McpContext` (raises `McpContextError` if unset)
  - `@asynccontextmanager async def use_context(ctx)` — sets/resets the ContextVar.

- [ ] **Step 1: Write the failing test**

`backend/tests/mcp/test_context.py`:
```python
import pytest
from uuid import uuid4
from app.mcp.context import McpContext, get_context, use_context, McpContextError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_context_set_and_cleared():
    with pytest.raises(McpContextError):
        get_context()
    ctx = McpContext(family_id=uuid4(), user_id=uuid4(), role="PARENT", db=None)
    async with use_context(ctx):
        assert get_context().family_id == ctx.family_id
    with pytest.raises(McpContextError):
        get_context()
```

- [ ] **Step 2: Run it, expect failure**

Run: `cd backend && pytest tests/mcp/test_context.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`backend/app/mcp/context.py`:
```python
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class McpContextError(RuntimeError):
    pass


@dataclass
class McpContext:
    family_id: UUID
    user_id: UUID | None
    role: str
    db: AsyncSession


current_context: ContextVar["McpContext | None"] = ContextVar("mcp_current_context", default=None)


def get_context() -> McpContext:
    ctx = current_context.get()
    if ctx is None:
        raise McpContextError("MCP tool called with no family context bound")
    return ctx


@asynccontextmanager
async def use_context(ctx: McpContext):
    token = current_context.set(ctx)
    try:
        yield ctx
    finally:
        current_context.reset(token)
```

- [ ] **Step 4: Run it, expect pass**

Run: `cd backend && pytest tests/mcp/test_context.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/app/mcp/context.py backend/tests/mcp/test_context.py
git commit -m "feat(mcp): McpContext + ContextVar family-scope plumbing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1 — Declarative registry + generic CRUD (budget account end-to-end)

### Task 3: `EntitySpec`, `ServiceAdapter`, and the registry container

**Files:**
- Create: `backend/app/mcp/registry.py`
- Create: `backend/app/mcp/adapters.py`
- Test: `backend/tests/mcp/test_registry.py`

**Interfaces:**
- Produces:
  - `class ServiceAdapter` with async methods `list(ctx) / get(ctx, id) / create(ctx, data) / update(ctx, id, data) / delete(ctx, id)`, each `NotImplementedError` by default.
  - `@dataclass(frozen=True) EntitySpec(name, domain, ops: frozenset[str], create_schema, update_schema, destructive_ops: frozenset[str], adapter: ServiceAdapter, summarize: Callable[[str, dict], str])`
  - `REGISTRY: list[EntitySpec]` (empty for now) + `tool_name(spec, op) -> str` returning `f"{spec.domain}_{spec.name}_{op}"`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/mcp/test_registry.py
from app.mcp.registry import EntitySpec, ServiceAdapter, tool_name


def test_tool_name_convention():
    spec = EntitySpec(
        name="account", domain="budget", ops=frozenset({"list", "create"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset(),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
    )
    assert tool_name(spec, "create") == "budget_account_create"
    assert tool_name(spec, "list") == "budget_account_list"
```

- [ ] **Step 2: Run it, expect failure** — `cd backend && pytest tests/mcp/test_registry.py -v` → FAIL.

- [ ] **Step 3: Implement `adapters.py`**
```python
from uuid import UUID
from app.mcp.context import McpContext


class ServiceAdapter:
    """Binds a generic CRUD op to a concrete app Service. Override what the entity supports."""

    async def list(self, ctx: McpContext) -> list[dict]:
        raise NotImplementedError

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        raise NotImplementedError

    async def create(self, ctx: McpContext, data: dict) -> dict:
        raise NotImplementedError

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        raise NotImplementedError

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        raise NotImplementedError
```

- [ ] **Step 4: Implement `registry.py`**
```python
from dataclasses import dataclass
from typing import Callable
from pydantic import BaseModel
from app.mcp.adapters import ServiceAdapter


@dataclass(frozen=True)
class EntitySpec:
    name: str
    domain: str
    ops: frozenset[str]
    create_schema: type[BaseModel] | type[dict]
    update_schema: type[BaseModel] | type[dict]
    destructive_ops: frozenset[str]
    adapter: ServiceAdapter
    summarize: Callable[[str, dict], str]


def tool_name(spec: "EntitySpec", op: str) -> str:
    return f"{spec.domain}_{spec.name}_{op}"


REGISTRY: list[EntitySpec] = []
```

- [ ] **Step 5: Run it, expect pass** — `pytest tests/mcp/test_registry.py -v` → PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/app/mcp/registry.py backend/app/mcp/adapters.py backend/tests/mcp/test_registry.py
git commit -m "feat(mcp): declarative EntitySpec registry + ServiceAdapter base

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Generic op handlers + tool generation; wire budget_account through MCP

**Files:**
- Create: `backend/app/mcp/schemas/budget.py` (pydantic create/update schemas for account)
- Create: `backend/app/mcp/adapters_budget.py` (concrete `AccountAdapter`)
- Modify: `backend/app/mcp/registry.py` (append the account `EntitySpec`)
- Modify: `backend/app/mcp/server.py` (generate tools from REGISTRY)
- Create: `backend/app/mcp/dispatch.py` (op → adapter dispatch, returns `{"ok": ...}` dicts)
- Test: `backend/tests/mcp/test_budget_account_crud.py`

**Interfaces:**
- Consumes: `EntitySpec`, `tool_name`, `get_context`, `BaseFamilyService` CRUD, `AccountService` (`backend/app/services/budget/account_service.py`).
- Produces: `async def dispatch_tool(name: str, arguments: dict) -> dict` in `dispatch.py`; `register_registry(server)` in `server.py` building `Tool` objects from REGISTRY (one per `(spec, op)`), `inputSchema` from the pydantic schema (`.model_json_schema()`) for create/update and a `{id}` schema for get/delete and `{}` for list.

- [ ] **Step 1: Read the real AccountService signatures**

Read `backend/app/services/budget/account_service.py` lines 19–230. Confirm `create(db, family_id, ...)`, `update(db, account_id, family_id, ...)`, `list_for_family(db, family_id)`, and that `BaseFamilyService.get_by_id/delete_by_id` apply. Use the actual signatures in the adapter below (adjust kwargs to match).

- [ ] **Step 2: Write the failing CRUD test**
```python
# backend/tests/mcp/test_budget_account_crud.py
import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_account_create_list_update_delete(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            assert "budget_account_create" in names

            created = json.loads((await s.call_tool(
                "budget_account_create",
                {"name": "Checking", "account_type": "checking", "starting_balance": 0},
            )).content[0].text)
            assert created["ok"] is True
            acc_id = created["data"]["id"]

            listed = json.loads((await s.call_tool("budget_account_list", {})).content[0].text)
            assert any(a["id"] == acc_id for a in listed["data"])

            updated = json.loads((await s.call_tool(
                "budget_account_update", {"id": acc_id, "name": "Checking 2"},
            )).content[0].text)
            assert updated["data"]["name"] == "Checking 2"

            deleted = json.loads((await s.call_tool("budget_account_delete", {"id": acc_id})).content[0].text)
            assert deleted["ok"] is True
```
> Reuse existing `conftest.py` fixtures for `db_session`, `family`, `parent_user`. If the names differ, read `backend/tests/conftest.py` and use the actual fixture names.

- [ ] **Step 3: Run it, expect failure** — `pytest tests/mcp/test_budget_account_crud.py -v` → FAIL.

- [ ] **Step 4: Implement the pydantic schemas**

`backend/app/mcp/schemas/budget.py`:
```python
from pydantic import BaseModel
from typing import Optional


class AccountCreate(BaseModel):
    name: str
    account_type: str
    starting_balance: int = 0


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
```
Add empty `backend/app/mcp/schemas/__init__.py`.

- [ ] **Step 5: Implement the concrete adapter**

`backend/app/mcp/adapters_budget.py` (adjust calls to the real `AccountService` signatures from Step 1):
```python
from uuid import UUID
from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.services.budget.account_service import AccountService
from app.services.base_service import BaseFamilyService
from app.models.budget import BudgetAccount


def _ser(a: BudgetAccount) -> dict:
    return {"id": str(a.id), "name": a.name, "account_type": a.account_type}


class _AccountBase(BaseFamilyService[BudgetAccount]):
    model = BudgetAccount


class AccountAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        rows = await AccountService.list_for_family(ctx.db, ctx.family_id)
        return [_ser(a) for a in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        return _ser(await _AccountBase.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        a = await AccountService.create(ctx.db, family_id=ctx.family_id, **data)
        return _ser(a)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        a = await _AccountBase.update_by_id(ctx.db, entity_id, ctx.family_id, data)
        return _ser(a)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        await _AccountBase.delete_by_id(ctx.db, entity_id, ctx.family_id)
```

- [ ] **Step 6: Register the account EntitySpec**

Append to `REGISTRY` in `registry.py` (import at bottom to avoid cycles, or in a `register_builtin()` called from `server.py`):
```python
from app.mcp.adapters_budget import AccountAdapter
from app.mcp.schemas.budget import AccountCreate, AccountUpdate

REGISTRY.append(EntitySpec(
    name="account", domain="budget",
    ops=frozenset({"list", "get", "create", "update", "delete"}),
    create_schema=AccountCreate, update_schema=AccountUpdate,
    destructive_ops=frozenset({"delete"}),
    adapter=AccountAdapter(),
    summarize=lambda op, p: f"{op} budget account {p.get('name') or p.get('id', '')}",
))
```

- [ ] **Step 7: Implement dispatch + tool generation**

`backend/app/mcp/dispatch.py`:
```python
from uuid import UUID
from app.mcp.registry import REGISTRY, tool_name
from app.mcp.context import get_context


def _spec_for(name: str):
    for spec in REGISTRY:
        for op in spec.ops:
            if tool_name(spec, op) == name:
                return spec, op
    return None, None


async def dispatch_tool(name: str, arguments: dict) -> dict:
    spec, op = _spec_for(name)
    if spec is None:
        return {"ok": False, "error": f"unknown tool {name}"}
    arguments = {k: v for k, v in arguments.items() if k != "family_id"}  # never trust client family_id
    ctx = get_context()
    try:
        if op == "list":
            return {"ok": True, "data": await spec.adapter.list(ctx)}
        if op == "get":
            return {"ok": True, "data": await spec.adapter.get(ctx, UUID(arguments["id"]))}
        if op == "create":
            payload = spec.create_schema(**arguments).model_dump(exclude_none=True)
            return {"ok": True, "data": await spec.adapter.create(ctx, payload)}
        if op == "update":
            eid = UUID(arguments.pop("id"))
            payload = spec.update_schema(**arguments).model_dump(exclude_none=True)
            return {"ok": True, "data": await spec.adapter.update(ctx, eid, payload)}
        if op == "delete":
            await spec.adapter.delete(ctx, UUID(arguments["id"]))
            return {"ok": True}
        return {"ok": False, "error": f"unsupported op {op}"}
    except Exception as e:  # surfaced to the LLM as a tool error, not a 500
        return {"ok": False, "error": str(e)}
```

In `server.py`, replace the hand-written `ping` handlers with registry-driven generation:
```python
import json
from mcp.server import Server
from mcp.types import Tool, TextContent
from app.mcp.registry import REGISTRY, tool_name
from app.mcp.dispatch import dispatch_tool

SERVER_NAME = "family-pg"


def _input_schema(spec, op) -> dict:
    if op == "list":
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if op in ("get", "delete"):
        return {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    schema = (spec.create_schema if op == "create" else spec.update_schema).model_json_schema()
    if op == "update":
        schema.setdefault("properties", {})["id"] = {"type": "string"}
        schema["required"] = ["id"]
    return schema


def build_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = []
        for spec in REGISTRY:
            for op in sorted(spec.ops):
                tools.append(Tool(
                    name=tool_name(spec, op),
                    description=f"{op} {spec.domain}.{spec.name}",
                    inputSchema=_input_schema(spec, op),
                ))
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await dispatch_tool(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


server = build_server()
```
Delete the now-obsolete `ping` smoke test or update it to assert `budget_account_list` exists.

- [ ] **Step 8: Run it, expect pass** — `pytest tests/mcp/test_budget_account_crud.py -v` → PASS.

- [ ] **Step 9: Commit**
```bash
git add backend/app/mcp/ backend/tests/mcp/test_budget_account_crud.py
git commit -m "feat(mcp): generic CRUD dispatch + budget_account tools end-to-end

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Cross-family isolation test (the critical security gate)

**Files:**
- Test: `backend/tests/mcp/test_isolation.py`

- [ ] **Step 1: Write the failing/expected-pass test**
```python
# backend/tests/mcp/test_isolation.py
import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_account_from_family_a_invisible_to_family_b(db_session, family, other_family, parent_user, other_parent):
    server = build_server()
    # create under family A
    ctx_a = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx_a):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            created = json.loads((await s.call_tool(
                "budget_account_create", {"name": "A-secret", "account_type": "checking"},
            )).content[0].text)
            acc_id = created["data"]["id"]
    # family B must NOT see it, and must NOT be able to get/update/delete it
    ctx_b = McpContext(family_id=other_family.id, user_id=other_parent.id, role="PARENT", db=db_session)
    async with use_context(ctx_b):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            listed = json.loads((await s.call_tool("budget_account_list", {})).content[0].text)
            assert all(a["id"] != acc_id for a in listed["data"])
            got = json.loads((await s.call_tool("budget_account_get", {"id": acc_id})).content[0].text)
            assert got["ok"] is False  # NotFound, scoped out
            # client-supplied family_id must be ignored, not honored
            spoof = json.loads((await s.call_tool(
                "budget_account_get", {"id": acc_id, "family_id": str(family.id)},
            )).content[0].text)
            assert spoof["ok"] is False
```
> Add `other_family` / `other_parent` fixtures to `conftest.py` if absent (a second `Family` + `User`).

- [ ] **Step 2: Run it** — `pytest tests/mcp/test_isolation.py -v` → expected PASS (service-layer scoping already enforces this; this test locks it).

- [ ] **Step 3: Commit**
```bash
git add backend/tests/mcp/test_isolation.py backend/tests/conftest.py
git commit -m "test(mcp): cross-family isolation for budget_account tools

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Destructive-op HITL gate (in-app)

### Task 6: `jarvis_pending_action` model + migration

**Files:**
- Create: `backend/app/models/jarvis_pending_action.py`
- Modify: `backend/app/models/__init__.py` (export it)
- Create: `backend/migrations/versions/2026_06_24_jarvis_pending_action.py`
- Test: `backend/tests/mcp/test_pending_action_model.py`

**Interfaces:**
- Produces: `JarvisPendingAction(id, family_id, user_id, message_id, tool_name, params: JSONB, summary, status, created_at, resolved_at, expires_at)`; status values `pending|approved|rejected|expired`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/mcp/test_pending_action_model.py
import pytest
from datetime import datetime, timedelta, timezone
from app.models.jarvis_pending_action import JarvisPendingAction


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_pending_action_persists(db_session, family, parent_user):
    pa = JarvisPendingAction(
        family_id=family.id, user_id=parent_user.id, tool_name="budget_account_delete",
        params={"id": "x"}, summary="delete account", status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(pa)
    await db_session.commit()
    await db_session.refresh(pa)
    assert pa.id is not None and pa.status == "pending"
```

- [ ] **Step 2: Run it, expect failure** — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the model** (mirror an existing model, e.g. `backend/app/models/notification.py`, for column conventions / UUID PK / `family_id` FK with `ondelete="CASCADE"`). Use `from sqlalchemy.dialects.postgresql import JSONB, UUID`.

- [ ] **Step 4: Generate + edit the migration**

Get the current head: `cd backend && alembic heads`. Create the migration file with `down_revision` set to that head. Hand-write `op.create_table("jarvis_pending_action", ...)` (autogenerate may miss JSONB defaults — verify). Run `alembic upgrade head` against the test DB.

- [ ] **Step 5: Run it, expect pass** — `pytest tests/mcp/test_pending_action_model.py -v` → PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/app/models/jarvis_pending_action.py backend/app/models/__init__.py backend/migrations/versions/2026_06_24_jarvis_pending_action.py backend/tests/mcp/test_pending_action_model.py
git commit -m "feat(jarvis): jarvis_pending_action model + migration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Destructive classification + pending-action service + approve/reject endpoints

**Files:**
- Create: `backend/app/services/jarvis_pending_action_service.py`
- Create: `backend/app/mcp/confirm.py` (`is_destructive(name) -> bool`, `summarize(name, args) -> str`)
- Modify: `backend/app/api/routes/jarvis.py` (add `POST /actions/{id}/approve`, `POST /actions/{id}/reject`, `GET /actions`)
- Test: `backend/tests/mcp/test_confirm_flow.py`

**Interfaces:**
- Consumes: `REGISTRY`, `tool_name`, `dispatch_tool`, `JarvisPendingAction`, `get_current_user`.
- Produces:
  - `is_destructive(tool: str) -> bool` (true if the tool's op is in its spec's `destructive_ops`).
  - `PendingActionService.create(db, ctx, tool, args) -> JarvisPendingAction`
  - `PendingActionService.approve(db, action_id, current_user) -> dict` (re-checks `family_id`, not expired, status pending; binds `McpContext` and calls `dispatch_tool`; marks approved).
  - `PendingActionService.reject(db, action_id, current_user) -> None`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/mcp/test_confirm_flow.py
import pytest
from uuid import uuid4
from app.mcp.confirm import is_destructive
from app.services.jarvis_pending_action_service import PendingActionService
from app.mcp.context import McpContext
from app.models.budget import BudgetAccount


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_delete_is_destructive_create_is_not():
    assert is_destructive("budget_account_delete") is True
    assert is_destructive("budget_account_create") is False


@pytest.mark.anyio
async def test_approve_executes_once_reject_discards(db_session, family, parent_user):
    # seed an account to delete
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    acc = BudgetAccount(family_id=family.id, name="Doomed", account_type="checking")
    db_session.add(acc); await db_session.commit(); await db_session.refresh(acc)

    pa = await PendingActionService.create(db_session, ctx, "budget_account_delete", {"id": str(acc.id)})
    assert pa.status == "pending"
    # not executed yet
    assert await db_session.get(BudgetAccount, acc.id) is not None

    result = await PendingActionService.approve(db_session, pa.id, parent_user)
    assert result["ok"] is True
    assert await db_session.get(BudgetAccount, acc.id) is None

    # second approve is a no-op error (already resolved)
    with pytest.raises(Exception):
        await PendingActionService.approve(db_session, pa.id, parent_user)


@pytest.mark.anyio
async def test_cross_family_approve_denied(db_session, family, other_family, parent_user, other_parent):
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    pa = await PendingActionService.create(db_session, ctx, "budget_account_delete", {"id": str(uuid4())})
    with pytest.raises(Exception):
        await PendingActionService.approve(db_session, pa.id, other_parent)  # different family
```

- [ ] **Step 2: Run it, expect failure** — FAIL.

- [ ] **Step 3: Implement `confirm.py`**
```python
from app.mcp.registry import REGISTRY, tool_name


def _spec_op(tool: str):
    for spec in REGISTRY:
        for op in spec.ops:
            if tool_name(spec, op) == tool:
                return spec, op
    return None, None


def is_destructive(tool: str) -> bool:
    spec, op = _spec_op(tool)
    return bool(spec and op in spec.destructive_ops)


def summarize(tool: str, args: dict) -> str:
    spec, op = _spec_op(tool)
    return spec.summarize(op, args) if spec else tool
```

- [ ] **Step 4: Implement `PendingActionService`** — `create` builds the row (summary via `confirm.summarize`, `expires_at = now + 10min`). `approve`: load row; assert `row.family_id == current_user.family_id` else raise `PermissionError`; assert `status == "pending"` and `expires_at > now` else raise; bind `McpContext(family_id=row.family_id, user_id=current_user.id, role=current_user.role, db=db)` via `use_context` and `await dispatch_tool(row.tool_name, row.params)`; set `status="approved"`, `resolved_at=now`; commit; return the dispatch result. `reject`: same ownership check, set `status="rejected"`.

- [ ] **Step 5: Add routes** in `jarvis.py` (`Depends(get_current_user)`, parent-only): approve/reject/list, delegating to the service.

- [ ] **Step 6: Run it, expect pass** — `pytest tests/mcp/test_confirm_flow.py -v` → PASS.

- [ ] **Step 7: Commit**
```bash
git add backend/app/services/jarvis_pending_action_service.py backend/app/mcp/confirm.py backend/app/api/routes/jarvis.py backend/tests/mcp/test_confirm_flow.py
git commit -m "feat(jarvis): destructive-op HITL gate (pending actions + approve/reject)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Rewire Jarvis to the MCP client

### Task 8: Source Jarvis tools from the in-memory MCP client + `confirm` SSE event + migrate the 11 legacy tools

**Files:**
- Modify: `backend/app/services/jarvis_service.py` (tool list from MCP client; destructive gate; new `confirm` SSE event)
- Create: `backend/app/mcp/openai_bridge.py` (`mcp_tools_to_openai(tools) -> list[dict]`)
- Modify: `backend/app/mcp/registry.py` (add EntitySpecs covering the 11 legacy capabilities: task_template create, calendar event create, shopping item, recipe, meal plan, notification, jarvis schedule; plus read tools)
- Modify: `backend/app/services/jarvis_tools.py` (delete handlers now covered by the registry; keep any not yet migrated)
- Test: `backend/tests/mcp/test_jarvis_bridge.py`, update `backend/tests/test_jarvis*.py`

**Interfaces:**
- Consumes: `build_server`, in-memory `create_connected_server_and_client_session` (or a persistent in-process client session opened in the FastAPI lifespan), `is_destructive`, `summarize`, `PendingActionService`.
- Produces: `mcp_tools_to_openai(tools_result) -> list[dict]` mapping each MCP `Tool` to `{"type":"function","function":{"name","description","parameters": inputSchema}}`.

- [ ] **Step 1: Write the failing bridge test**
```python
# backend/tests/mcp/test_jarvis_bridge.py
from app.mcp.openai_bridge import mcp_tools_to_openai
from mcp.types import Tool


def test_bridge_shapes_openai_function():
    tools = [Tool(name="budget_account_list", description="list", inputSchema={"type": "object", "properties": {}})]
    out = mcp_tools_to_openai(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "budget_account_list"
    assert out[0]["function"]["parameters"]["type"] == "object"
```

- [ ] **Step 2: Run it, expect failure** — FAIL.

- [ ] **Step 3: Implement `openai_bridge.py`**
```python
def mcp_tools_to_openai(tools) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": t.name,
            "description": t.description or t.name,
            "parameters": t.inputSchema or {"type": "object", "properties": {}},
        }}
        for t in tools
    ]
```

- [ ] **Step 4: Rewire `jarvis_service.py`** — In the chat-stream loop:
  - replace `tools=tool_definitions()` with the MCP-sourced list: open an in-process client to `build_server()` (or a lifespan-scoped session), `list_tools()`, `mcp_tools_to_openai(...)`. Cache per-request.
  - In the tool-dispatch branch, before executing: `if is_destructive(tool_name):` create a `JarvisPendingAction` via `PendingActionService.create(db, ctx, tool_name, args)` and `yield` an SSE `confirm` event `{"action_id","tool","summary","params"}`, then continue WITHOUT executing (the LLM's hop ends; the human approves out-of-band). Else bind `McpContext` (from the request's `family_id`/`user_id`/`role` + `db`) via `use_context` and dispatch through the MCP client; append the result; continue the hop loop.
  - Add `confirm` to the documented SSE taxonomy.

- [ ] **Step 5: Migrate the 11 legacy tools** — add EntitySpecs/adapters so the old capabilities exist as registry tools (e.g. `tasks_template_create`, `calendar_event_create`, `shopping_item_create`, `meals_recipe_create`, `meals_planentry_create`, `notifications_notification_create`, `jarvis_schedule_create`, plus read tools `tasks_*_list`). Remove the duplicated handlers from `jarvis_tools.py`. Keep `jarvis_tools.py` only if something is not yet migrated.

- [ ] **Step 6: Update existing Jarvis tests** — `backend/tests/test_jarvis*.py` likely assert the old tool names/dispatch. Update them to the new tool names and the MCP path. Run the full Jarvis suite.

- [ ] **Step 7: Run tests, expect pass** — `pytest tests/mcp/test_jarvis_bridge.py tests/test_jarvis*.py -v` → PASS.

- [ ] **Step 8: Commit**
```bash
git add backend/app/services/jarvis_service.py backend/app/mcp/openai_bridge.py backend/app/mcp/registry.py backend/app/services/jarvis_tools.py backend/tests/
git commit -m "feat(jarvis): source tools from MCP client + destructive confirm event + migrate legacy tools

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — External HTTP transport + per-family tokens

### Task 9: `jarvis_mcp_token` model + migration + token service

**Files:**
- Create: `backend/app/models/jarvis_mcp_token.py`
- Create: `backend/app/services/jarvis_mcp_token_service.py`
- Create: `backend/migrations/versions/2026_06_24_jarvis_mcp_token.py`
- Test: `backend/tests/mcp/test_token_service.py`

**Interfaces:**
- Produces:
  - `JarvisMcpToken(id, family_id, created_by, label, token_hash, token_prefix, last_used_at, revoked_at, created_at)`.
  - `TokenService.mint(db, family_id, user_id, label) -> tuple[JarvisMcpToken, str]` (returns the row + the one-time plaintext secret `mcp_<32 hex>`; stores only `sha256(secret)` + first 8 chars).
  - `TokenService.resolve(db, secret) -> JarvisMcpToken | None` (hash + lookup; None if missing/revoked; updates `last_used_at`).
  - `TokenService.revoke(db, token_id, family_id) -> None`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/mcp/test_token_service.py
import pytest
from app.services.jarvis_mcp_token_service import TokenService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mint_resolve_revoke(db_session, family, parent_user):
    row, secret = await TokenService.mint(db_session, family.id, parent_user.id, "laptop")
    assert secret.startswith("mcp_") and row.token_prefix == secret[:8]
    resolved = await TokenService.resolve(db_session, secret)
    assert resolved is not None and resolved.family_id == family.id
    await TokenService.revoke(db_session, row.id, family.id)
    assert await TokenService.resolve(db_session, secret) is None
```

- [ ] **Step 2: Run it, expect failure** — FAIL.

- [ ] **Step 3: Implement** the model, the service (`hashlib.sha256`, `secrets.token_hex(16)`), and the migration (chain to current `alembic heads`; `alembic upgrade head`).

- [ ] **Step 4: Run it, expect pass** — `pytest tests/mcp/test_token_service.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/app/models/jarvis_mcp_token.py backend/app/services/jarvis_mcp_token_service.py backend/migrations/versions/2026_06_24_jarvis_mcp_token.py backend/tests/mcp/test_token_service.py
git commit -m "feat(mcp): per-family MCP bearer token model + service

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Mount `/mcp` streamable-HTTP with bearer auth → family-scoped context

**Files:**
- Create: `backend/app/mcp/http.py` (ASGI mount + auth middleware)
- Modify: `backend/app/main.py` (mount `/mcp`, run `session_manager` in lifespan, behind `JARVIS_MCP_HTTP_ENABLED`)
- Modify: `backend/app/core/config.py` (`JARVIS_MCP_HTTP_ENABLED: bool = True`, `JARVIS_MCP_DB_ROLE: str | None = None`)
- Test: `backend/tests/mcp/test_http_transport.py`

**Interfaces:**
- Consumes: `build_server`, `TokenService`, `use_context`, `AsyncSessionLocal`.
- Produces: a Starlette sub-app at `/mcp`; an auth middleware that reads `Authorization: Bearer <secret>`, resolves the token to a family, opens a fresh `AsyncSessionLocal()` (using `JARVIS_MCP_DB_ROLE` if set), binds `McpContext` (user_id=None, role="MCP_TOKEN") for the request, and returns 401 on missing/invalid/revoked token.

- [ ] **Step 1: Write the failing transport test**
```python
# backend/tests/mcp/test_http_transport.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_requires_bearer():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401
```
> A full MCP handshake over HTTP is heavy to assert in-process; this test pins the auth gate. Add a happy-path handshake test using a minted token if the SDK's test client supports it.

- [ ] **Step 2: Run it, expect failure** — FAIL (no `/mcp` route).

- [ ] **Step 3: Implement `http.py`** — build the streamable-HTTP ASGI app from `build_server().streamable_http_app(...)`; wrap with a middleware that extracts the bearer token, calls `TokenService.resolve`, and on success opens a session + binds context for the downstream call (401 otherwise). Mount it in `main.py` (`app.mount("/mcp", mcp_asgi)`) and run `server.session_manager.run()` (or the low-level equivalent) inside the existing lifespan, gated on `settings.JARVIS_MCP_HTTP_ENABLED`.

- [ ] **Step 4: Run it, expect pass** — `pytest tests/mcp/test_http_transport.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/app/mcp/http.py backend/app/main.py backend/app/core/config.py backend/tests/mcp/test_http_transport.py
git commit -m "feat(mcp): mount /mcp streamable-http with per-family bearer auth

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Restricted DB role for the HTTP transport (hardening)

**Files:**
- Create: `backend/migrations/versions/2026_06_24_mcp_restricted_role.py` (or a documented one-off SQL in `docs/`)
- Modify: `backend/app/mcp/http.py` (open the HTTP-path session with `JARVIS_MCP_DB_ROLE` via `SET ROLE`)
- Test: `backend/tests/mcp/test_restricted_role.py` (skipped if role unset)

- [ ] **Step 1:** Write a migration creating role `jarvis_mcp` with `GRANT SELECT, INSERT, UPDATE, DELETE` on the activity-domain tables only, and **no** grants on `users`, `families`, `*subscription*`, billing tables; `NOLOGIN`-via-`SET ROLE` from the app role. Document the exact `GRANT` list.
- [ ] **Step 2:** In `http.py`, after opening the session, `await session.execute(text("SET ROLE :role"))` when `JARVIS_MCP_DB_ROLE` is set; log a warning when unset.
- [ ] **Step 3:** Test (guarded by the env var) that a write to `users` from an HTTP-path session is rejected by the DB. Skip when the role isn't provisioned.
- [ ] **Step 4: Commit** (message: `feat(mcp): restricted DB role for external /mcp sessions`).

---

## Phase 5 — Expand the registry to all activity domains

Each entity below is a **data-only** addition: a pydantic create/update schema + a `ServiceAdapter` subclass binding to the existing service + a `REGISTRY.append(EntitySpec(...))`. The mechanism is already proven (Tasks 4–5); no new control flow. Group the work into one task per domain. Each task ends by running the coverage test (Task N+last) and a quick CRUD smoke for one representative entity in that domain.

**Entity table** (domain · entity · service module · ops · destructive ops):

| domain | entity | service (`backend/app/services/...`) | ops | destructive |
|---|---|---|---|---|
| budget | category_group | `budget/category_service.py` | LGCUD | delete |
| budget | category | `budget/category_service.py` | LGCUD | delete |
| budget | payee | `budget/payee_service.py` | LGCUD | delete |
| budget | transaction | `budget/transaction_service.py` | LGCUD | delete, create, update *(money)* |
| budget | allocation | `budget/allocation_service.py` | LGCUD | delete |
| budget | goal | `budget/goal_service.py` | LGCUD | delete |
| budget | rule | `budget/categorization_rule_service.py` | LGCUD | delete |
| budget | recurring | `budget/recurring_transaction_service.py` | LGCUD | delete |
| budget | tag | `budget/tag_service.py` | LGCUD | delete |
| budget | saved_filter | `budget/saved_filter_service.py` | LGCUD | delete |
| budget | custom_report | `budget/custom_report_service.py` | LGCUD | delete |
| budget | receipt_draft | `budget/receipt_draft_service.py` | LGD | delete |
| points | ledger | `points_service.py` | LG | — |
| points | adjust | `points_service.py` (parent adjustment) | C | create *(money)* |
| points | transfer | `points_service.py` | C | create *(money)* |
| rewards | reward | `reward_service.py` (locate) | LGCUD | delete |
| rewards | redemption | `reward_service.py` | LC | create *(money)* |
| tasks | template | `task_template_service.py` | LGCUD | delete |
| tasks | assignment | `task_assignment_service.py` (locate) | LGUD | delete |
| gigs | offering | gig service (locate, `gig_service.py`) | LGCUD | delete |
| gigs | claim | gig service | LGUD | delete |
| meals | recipe | `meal_service.py` | LGCUD | delete |
| meals | planentry | `meal_service.py` | LGCUD | delete |
| shopping | list | `shopping_service.py` | LGCUD | delete |
| shopping | item | `shopping_service.py` | LGCUD | delete |
| calendar | event | `calendar_service.py` | LGCUD | delete |
| chat | message | `chat_service.py` (locate) | LGCD | delete |
| pet | pet | `pet_service.py` (locate) | LG + `feed`/`interact` as custom ops | — |
| consequences | consequence | `consequence_service.py` (locate) | LGCUD | delete |
| notifications | notification | `notification_service.py` | LGCD | delete |

> `LGCUD` = list/get/create/update/delete. "*(money)*" = also gate the create/update even though it's not a delete. For each service, read the real method names first (they vary: `create`, `add_*`, `list_for_family`, etc.) and bind the adapter accordingly; fall back to `BaseFamilyService` classmethods where the service subclasses it.

### Tasks 12–19 (one per domain group): budget-rest, points+rewards, tasks+gigs, meals+shopping, calendar+chat, pet+consequences+notifications

For each domain group, per entity:
- [ ] Read the service to get real method signatures.
- [ ] Add the pydantic create/update schema in `backend/app/mcp/schemas/<domain>.py`.
- [ ] Add the `ServiceAdapter` subclass in `backend/app/mcp/adapters_<domain>.py`.
- [ ] Append the `EntitySpec` to `REGISTRY`, setting `destructive_ops` per the table.
- [ ] Write a CRUD smoke test for one representative entity (mirror Task 4's test).
- [ ] Run the domain test + the coverage test (below). Commit per domain group.

### Task 20: Registry coverage test (guards every spec)

**Files:** `backend/tests/mcp/test_registry_coverage.py`
- [ ] Parametrize over `REGISTRY`: assert each spec's `adapter` implements every method named in `ops` (no `NotImplementedError` for declared ops — call with a probing stub or assert the method is overridden), `create_schema`/`update_schema` are `BaseModel` subclasses when `create`/`update` in ops, and `destructive_ops <= ops`. Assert no tool name collides. Commit.

---

## Phase 6 — Frontend

### Task 21: Confirm-card handler for the `confirm` SSE event

**Files:** Modify `frontend/src/pages/parent/jarvis.astro`
- [ ] In the SSE parse loop (~lines 210–253), add a branch for `event === "confirm"`: render a card with `data.tool`, `data.summary`, a `<pre>` of `data.params`, and **Approve** / **Cancel** buttons.
- [ ] Approve → `fetch('/api/jarvis/actions/'+id+'/approve', {method:'POST'})`; on success render the returned result as a completed-action bubble. Cancel → `.../reject`.
- [ ] Manual check: `cd frontend && npm run dev`, trigger a destructive ask, confirm the card appears and approve executes. Commit.

### Task 22: Parent-settings token management UI

**Files:** Create `frontend/src/pages/parent/settings/mcp-tokens.astro`; add a nav link near subscription settings.
- [ ] List tokens (prefix, label, last-used, revoke button) via `GET /api/jarvis/mcp-tokens`; **Mint** form shows the one-time secret once (copy button); **Revoke** posts to the delete endpoint. (Add these list/mint/revoke routes to `jarvis.py` if not added in Task 9.)
- [ ] Manual check + commit.

---

## Phase 7 — Finalize

### Task 23: Full suite + deploy notes
- [ ] Run the whole backend suite: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v` (or venv). Fix regressions. Target: 0 failures (matches the repo's green-suite invariant).
- [ ] Add a short `docs/` note: provision `jarvis_mcp` DB role on prod before enabling external `/mcp`; the external URL is `https://api-gcp-family.agent-ia.mx/mcp`; tokens minted in parent settings.
- [ ] Update `CLAUDE.md` Jarvis row to note: "MCP server (`/mcp`) + in-app MCP client; full family-scoped CRUD over activity domains; destructive ops HITL-gated."
- [ ] Final commit.

---

## Self-Review (filled by author)

- **Spec coverage:** MCP server (T1,4,8,10) · in-memory transport for Jarvis (T8) · HTTP `/mcp` + tokens (T9,10) · declarative service-backed CRUD (T3,4,Phase5) · activity-only, auth/billing excluded (Global Constraints + entity table) · destructive HITL (T6,7,8,21) · family isolation (T5, + token resolve T9/10) · 2 tables (T6,9) · tests incl. cross-family (T5, coverage T20) · restricted role (T11) · frontend confirm + token UI (T21,22). All spec sections map to tasks.
- **Placeholder scan:** Phase-5 per-entity bodies are data-driven and fully specified by the entity table + the Task-4 pattern (not placeholders); the only deferred specifics are real service method names, which each task's first step reads from source (correct practice, not a gap).
- **Type consistency:** `McpContext`, `dispatch_tool`, `tool_name`, `EntitySpec`, `ServiceAdapter`, `is_destructive`, `mcp_tools_to_openai`, `PendingActionService`, `TokenService` names are used consistently across tasks.
