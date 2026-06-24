# SDD progress — Jarvis full-PG MCP

Plan: docs/superpowers/plans/2026-06-24-jarvis-full-pg-mcp.md
Branch: feat/jarvis-full-pg-mcp
Merge-base (plan start): ee18de51cbc45e92dbfc3591a410cea4896da16c

## Task ledger
(none complete yet)

## Known risks
- Task 10 (HTTP /mcp): sse-starlette 3.4.5 wants starlette>=0.49.1 but app pins starlette 0.41.3 (fastapi 0.115.6 needs <0.42). In-memory path unaffected. Resolve at Task 10: pin older sse-starlette compatible with starlette<0.42, or bump fastapi, or avoid SSE (json_response).

## Task ledger (updates)
- Task 1: complete (commits ee18de5..eae2aaa, review Approved). Minor (deferred to final): tighten starlette pin to ==0.41.3.
- CALLOUT for Task 5: do NOT call build_server() on the module-global `server`; use `from app.mcp.server import server` directly (avoids double-registration of handlers).
- Task 2: complete (commits eae2aaa..ee6b42e, review Approved). Minor (final): McpContext.db could be `AsyncSession | None`.
- Task 4: complete (commit dea39a0). Generic CRUD dispatch + budget_account tools end-to-end; register_builtin() idempotent (guarded), fresh Server per build_server(). MCP AccountCreate/Update expose account_type, adapter maps to model.type + passes app AccountCreate/Update schemas to AccountService.
- Task 5: complete (HEAD). Cross-family isolation test for budget_account tools; added parent_user + other_parent fixtures to conftest.py; test confirms family-B cannot see/get family-A accounts even when spoofing family_id in args.
- Task 6: complete (2cfe062). JarvisPendingAction model + migration (down_revision=onboarding_events); JSONB params, status CHECK constraint, family_id CASCADE FK; imported in __init__.py for create_all; 1 test passing.
- Task 7: complete (d778c5b). confirm.py (is_destructive/summarize, registry-driven with register_builtin() for standalone use); PendingActionService (create/approve/reject/list_pending with multi-tenant gate + expiry check); jarvis.py routes GET /actions, POST /actions/{id}/approve|reject; 3 new tests passing, 0 regressions.
- Task 8: complete (0ab2edb). JarvisService sources tools from in-memory MCP client (mcp_tools_to_openai); dispatch via _mcp_dispatch binds McpContext (uses module-global `server`, no build_server() re-call). Destructive ops gated: chat_stream creates JarvisPendingAction + emits new 'confirm' SSE event (not executed inline); chat() queues similarly. Migrated all 11 legacy jarvis_tools handlers to registry EntitySpecs/adapters (tasks_template/today/pending/overdue, calendar_event, shopping_item, meals_recipe/planentry, notifications_notification, jarvis_schedule); jarvis_tools.py deleted. 37 registry tools, unique names. Updated test_jarvis_tools/sse to new names+MCP envelope; added test_jarvis_bridge. 35 mcp+jarvis tests pass; 53 related-service regression tests pass; full suite collects 1057 (no errors).
- Task 9: complete (8af78d7). JarvisMcpToken model + migration (down_revision=jarvis_pending_action); SHA-256 hash only stored; token_prefix=first 8 chars; TokenService.mint/resolve/revoke with last_used_at tracking; imported in __init__.py; 1 test passing (test_mint_resolve_revoke); 15 MCP tests all passing.
