# Jarvis full-PG access via an in-repo MCP server — design

- **Date:** 2026-06-24
- **Status:** Approved (brainstorm) → pending spec review
- **Author:** Jarvis copilot work (juan)
- **Branch:** `feat/jarvis-full-pg-mcp`

## 1. Context

Today "Jarvis" (the parent-facing AI copilot, `/api/jarvis`) is **not** MCP. It is a custom
OpenAI-tool-call loop in `backend/app/services/jarvis_service.py` (model `gemini-2.5-flash`
via the LiteLLM proxy, `tool_choice="auto"`, `MAX_TOOL_HOPS=4`). Tools live in
`backend/app/services/jarvis_tools.py` as a `REGISTRY: Dict[name, (schema, handler)]` with
`dispatch(db, family_id, user_id, name, args)`. It exposes **11 tools**, ~8/32 tables,
**CREATE + READ only** — no UPDATE, no DELETE, **zero budget access**.

We want Jarvis to have full CRUD across the family's *activity* domains, delivered as a
**genuine MCP server** (the protocol — reusable by external clients), while preserving the
app's non-negotiable multi-tenant isolation (every query scoped by `family_id`).

## 2. Goals / Non-goals

**Goals**
- A real, in-repo MCP server exposing **family-scoped full CRUD** over the activity domains.
- Jarvis becomes an **MCP client** of that server (in-process).
- The same server is reachable by **external MCP clients** (Claude Desktop, n8n) over HTTP, token-scoped to one family.
- Destructive / money-moving operations initiated by the Jarvis LLM are **gated by an in-chat confirmation** (HITL).
- Reuse the existing app **Service classes** (no raw SQL) so validation + family scoping are inherited.

**Non-goals (out of scope)**
- Auth/identity domains: user/member management, roles, passwords.
- Subscription / PayPal billing mutations.
- Cross-family / operator ("admin over all families") access — the model is strictly single-family.
- Changing the Jarvis LLM model (stays `gemini-2.5-flash`, already overridable via `JARVIS_MODEL`).
- Raw-SQL / arbitrary-query access.

## 3. Decisions (from brainstorm)

| # | Decision |
|---|----------|
| Intent | Full CRUD, structured + family-scoped, single family |
| Mechanism | **Real in-repo MCP server**; backend is an MCP client; tools **reuse app Service classes** |
| Write safety | **Confirm destructive/money ops**; routine reads + writes run inline |
| Domain scope | **Activity domains only** — exclude auth/billing |
| External access | **Full external v1**: HTTP `/mcp` transport + per-family token minting |
| Model | Keep `gemini-2.5-flash`; revisit if tool-selection misfires |
| Tool surface | **Declarative per-entity CRUD** (list/get/create/update/delete), ~50–60 tools |

## 4. Architecture

New package `backend/app/mcp/`:

```
backend/app/mcp/
  server.py        # builds the mcp.Server, registers generated tools, exposes 2 transports
  registry.py      # declarative EntitySpec list (the source of truth for tools)
  tools.py         # generic op handlers (list/get/create/update/delete) over a service + ctx
  context.py       # McpContext + resolution (in-app trusted vs HTTP token)
  schemas.py       # per-entity pydantic create/update arg schemas
  http.py          # ASGI mount at /mcp + bearer-token auth middleware + rate limit
  confirm.py       # destructive-op gate helpers (classify + pending-action creation)
```

**One tool core, two transports** (both off the same `mcp.Server`):
- **In-memory transport** — `jarvis_service` opens an in-memory MCP client session; no network hop.
- **Streamable-HTTP transport** — mounted on the FastAPI app at `/mcp`; reachable through the
  existing Cloudflare tunnel (`api-gcp-family.agent-ia.mx/mcp`); **bearer-token gated**.

Hosting: **in-process** in the existing FastAPI app (no sidecar) — consistent with the app's
pure-async model (APScheduler + `asyncio.create_task`, Redis leader election). The `mcp` Python
SDK supports ASGI mounting and in-memory client/server, so no new container or process.

## 5. Declarative tool registry

`registry.py` declares one `EntitySpec` per entity:

```python
@dataclass(frozen=True)
class EntitySpec:
    name: str                       # "budget_transaction"
    domain: str                     # "budget"
    service: type                   # TransactionService (existing app service)
    ops: frozenset[str]             # {"list","get","create","update","delete"}
    create_schema: type[BaseModel]  # validated args for create
    update_schema: type[BaseModel]  # validated args for update
    destructive_ops: frozenset[str] # {"delete"} + money ops flagged here
    summarize: Callable[[str, dict], str]  # (op, params) -> human confirm summary
    adapter: ServiceAdapter | None  # optional, when a service signature deviates
```

- **Tool name convention:** `{domain}_{entity}_{op}` (MCP-safe `[a-zA-Z0-9_]+`), e.g.
  `budget_transaction_create`, `tasks_template_delete`, `shopping_item_list`.
- **Generic op handlers** (`tools.py`) map each op to the canonical service signature
  (`list(db, family_id, **filters)`, `get(db, family_id, id)`, `create(db, family_id, payload)`,
  `update(db, family_id, id, payload)`, `delete(db, family_id, id)`). Services that deviate get a
  thin per-entity `adapter` — no logic duplicated, just signature glue.
- Tool schemas are generated from the pydantic `create_schema`/`update_schema` (JSON Schema),
  so the MCP tool list and the OpenAI function schema are both derived from one source.

**In-scope domains/entities** (full CRUD unless a service lacks an op):
budget (category-group, category, account, payee, transaction, allocation, goal, rule,
recurring, tag, saved-filter, custom-report, receipt-draft), points (adjust/transfer/list),
rewards (catalog + redemptions), tasks (template, assignment), gigs (offering, claim),
meals (recipe, plan-entry), shopping (list, item), calendar (event), chat (message), pet
(read + feed/interact), consequences, notifications.

The existing 11 Jarvis tools are **re-expressed** as entries in this registry (single code path,
no parallel dispatch).

## 6. Family context & isolation (security core)

```python
@dataclass
class McpContext:
    family_id: UUID
    user_id: UUID | None   # the acting human (None for token-only external calls)
    role: str
    db: AsyncSession
```

The server **never trusts a client-supplied `family_id`**; any `family_id` in tool args is ignored.

- **In-app (Jarvis):** `jarvis_service` sets the context (family_id/user_id/role from the parent's
  JWT + the request's `AsyncSession`) via a `contextvar` before each tool dispatch.
- **External (HTTP):** bearer token → `jarvis_mcp_token` lookup → `family_id`; a fresh
  `AsyncSession` is opened per call, scoped to that family.

**Defense-in-depth**
1. Trusted context injection (never from client args).
2. Every wrapped Service already filters by `family_id`.
3. **Restricted DB role** for the HTTP transport's sessions (DML only; no DDL; no access to
   `users`/auth/`*subscription*`/billing tables). Elevated to **v1** because external network
   exposure was chosen.
4. Audit log row per tool call (tool, family_id, user/token id, ok/err) extending the existing
   action logging.

## 7. New data model (2 tables + alembic migration)

```
jarvis_mcp_token
  id uuid pk
  family_id uuid  -> families(id) ON DELETE CASCADE
  created_by uuid -> users(id)    ON DELETE SET NULL
  label text                      # human label ("Juan's laptop")
  token_hash text                 # sha256 of the secret; secret shown ONCE at creation
  token_prefix text               # first 8 chars, for identification in UI
  last_used_at timestamptz
  revoked_at timestamptz
  created_at timestamptz default now()

jarvis_pending_action
  id uuid pk
  family_id uuid  -> families(id) ON DELETE CASCADE
  user_id uuid    -> users(id)    ON DELETE SET NULL   # initiator (nullable; row survives user deletion)
  message_id uuid -> jarvis_messages(id) ON DELETE SET NULL  # chat turn that proposed it
  tool_name text
  params jsonb
  summary text
  status text  default 'pending'   # pending|approved|rejected|expired
  created_at timestamptz default now()
  resolved_at timestamptz
  expires_at timestamptz           # e.g. now() + 10 min
```

## 8. Destructive-op HITL flow

A tool is **destructive** when `op == "delete"`, a bulk mutation, or money-moving
(points adjust, point transfer, reward redeem) — declared via `destructive_ops`.

**LLM-initiated (Jarvis chat) path** — the gate:
1. LLM calls a destructive tool.
2. Backend does **not** execute. It writes a `jarvis_pending_action` (tool, params, summary,
   `expires_at`) and emits a **new SSE `confirm` event**:
   `event: confirm` / `data: {"action_id", "tool", "summary", "params"}`.
3. Frontend renders a confirm/cancel card.
4. **Approve** → `POST /api/jarvis/actions/{id}/approve` → re-checks `current_user.family_id ==
   action.family_id` + not expired → executes the MCP tool with stored params → marks `approved`,
   stores result, records a `JarvisMessage` action note → returns result to the UI.
   **Reject/expire** → `POST /api/jarvis/actions/{id}/reject` → marks `rejected`, discards.

Routine reads + non-destructive writes execute inline (unchanged behavior, existing `tool` SSE event).

**Human-initiated (external MCP client) path:** no chat to confirm against — the client *is* the
human operator. Destructive tools execute directly, but strictly within the token's family scope.
(The chat HITL gate is a Jarvis-LLM construct, not a server-wide policy.)

## 9. Jarvis rewire (`jarvis_service.py`)

The hop loop, SSE stream, history, and context block are unchanged. Only the tool source changes:
- On stream start, open the in-memory MCP client session; `list_tools()` → convert MCP tool
  schemas → OpenAI function schemas (replacing `tool_definitions()`).
- On a tool_call: classify destructive (→ §8 gate) else dispatch through the MCP client
  (replacing local `dispatch()`), append result, continue the hop loop.
- New SSE event `confirm` added to the taxonomy (`thinking|tool|reply|error|done|confirm`).

## 10. Frontend (`frontend/src/pages/parent/jarvis.astro`)

- Add a handler for the `confirm` SSE event → render a confirm card (tool name, human `summary`,
  params preview, **Approve** / **Cancel**), wired to the approve/reject endpoints.
- New **parent settings** surface to **mint / label / revoke** `jarvis_mcp_token`s (secret shown
  once), under `/parent/settings/` (sibling to subscription). Shows prefix + last-used + revoke.
- Everything else in the chat UI unchanged.

## 11. Config / dependencies

- `backend/requirements.txt`: add `mcp` (latest; verify version at implementation).
- Env: `JARVIS_MCP_HTTP_ENABLED` (default `true`), `JARVIS_MCP_DB_ROLE` (restricted role name,
  optional — falls back to the app role if unset, with a logged warning).
- Alembic migration adds the 2 tables (head chain extends `wave3_custom_reports_table`).
- The restricted Postgres role is provisioned by a migration / one-off SQL documented in the plan.

## 12. Testing strategy

- **Cross-family isolation (critical):** a token scoped to family A cannot read/write family B
  (every entity); tool args carrying a foreign `family_id` are ignored.
- **Per-entity CRUD:** representative entity per domain — list/get/create/update/delete round-trip.
- **Destructive gate:** destructive tool → pending action created, **not** executed; approve
  executes once; reject discards; expired cannot be approved.
- **HTTP transport auth:** no token → 401; revoked/invalid token → 401; valid token → scoped session.
- **Registry coverage:** every `EntitySpec` resolves a real service + valid schemas (parametrized).
- **Regression:** the 11 migrated tools keep behavior.
- Fits the existing pytest suite (separate test DB on 5435); all new code TDD.

## 13. Rollout

- Additive feature; no destructive migration. Ship via `./scripts/deploy-gcp.sh` + `alembic upgrade head`.
- Provision the restricted DB role on prod before enabling the HTTP transport externally.
- Smoke: in-app Jarvis CRUD on a test family; external `/mcp` handshake with a minted token.

## 14. Open questions / future (v2)

- Feed destructive-op results back into the LLM loop so Jarvis can comment (v1: execute + show result).
- Per-tool rate limits / spend caps for external tokens.
- Streaming partial assistant text (today only tool/reply events; no token streaming).
- Bumping the Jarvis model if many-tool selection proves unreliable on flash.
