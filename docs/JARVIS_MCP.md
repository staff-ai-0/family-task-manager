# Jarvis MCP server — deploy notes

The Jarvis copilot is backed by an in-repo MCP server (`family-pg`) that exposes
family-scoped CRUD over the app's activity domains. It is reachable two ways:

- **In-app** — Jarvis chat uses an in-memory MCP client; family scope comes from
  the caller's JWT. Always on.
- **External HTTP** — a streamable-HTTP transport mounted at `/mcp`, behind a
  per-family bearer token. Gated by `JARVIS_MCP_HTTP_ENABLED` (default `true`).

Destructive and money-moving tools are never executed inline: they create a
`jarvis_pending_action` and emit an SSE `confirm` event for a parent to approve.
Tool arguments never carry a trusted `family_id` — scope comes only from the
bound `McpContext` (JWT in-app, token on the HTTP path).

## External URL

```
https://api-gcp-family.agent-ia.mx/mcp
```

(The same backend that serves `/api/*`. Cloudflare Tunnel `gcp-family` already
routes `api-gcp-family.agent-ia.mx` → `http://backend:8000`, so no new tunnel
route is needed.)

## Tokens

Per-family bearer tokens are minted by a parent in
**Parent Settings → MCP tokens** (`/parent/settings/mcp-tokens`, backed by
`GET/POST/DELETE /api/jarvis/mcp-tokens`). The plaintext secret (`mcp_<hex>`) is
shown exactly once at mint time; only its SHA-256 hash + 8-char prefix are
stored. Clients send it as `Authorization: Bearer mcp_...`. Revoke from the same
page.

## Provision the restricted DB role BEFORE enabling external `/mcp` on prod

External `/mcp` sessions should run under the restricted `jarvis_mcp` Postgres
role, which has SELECT/INSERT/UPDATE/DELETE on activity-domain tables only and
**no** access to `users`, `families`, billing/subscription, or auth-secret
tables. Migration `mcp_restricted_role` creates the role; one manual grant and
one env var wire it up:

```bash
# 1. Run migrations (creates the NOLOGIN jarvis_mcp role + grants).
sudo docker compose --env-file .env -f docker-compose.gcp.yml \
  exec -T backend alembic upgrade head

# 2. Allow the app role to assume it (NOT in the migration — app-role name
#    varies per environment; it is `familyapp` in prod).
sudo docker compose --env-file .env -f docker-compose.gcp.yml \
  exec -T postgres psql -U familyapp familyapp -c "GRANT jarvis_mcp TO familyapp;"

# 3. Point the HTTP transport at the restricted role, then redeploy/restart.
echo 'JARVIS_MCP_DB_ROLE=jarvis_mcp' >> .env
```

If `JARVIS_MCP_DB_ROLE` is unset, the `/mcp` session runs with the full app DB
role and the backend logs a warning at request time. Do **not** enable external
`/mcp` on prod (`JARVIS_MCP_HTTP_ENABLED=true`) until the role is provisioned and
`JARVIS_MCP_DB_ROLE` is set.

To disable the external transport entirely, set `JARVIS_MCP_HTTP_ENABLED=false`
(the in-app Jarvis client is unaffected).
