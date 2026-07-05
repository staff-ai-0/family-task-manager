# Migration Design — GCP VM → on-prem 10.1.0.91 (rootless podman)

**Date:** 2026-07-04
**Status:** Approved (design), pending implementation plan
**Author:** Claude + Juan

## Goal

Move Family Task Manager production off the GCP VM `family-app` (e2-medium,
`family-prod`/`us-central1-a`) onto on-prem host **10.1.0.91** (RHEL 10.2,
rootless podman 5.8.2, user `jc`, linger enabled). Decommission the GCP VM
after the new host is verified serving.

Canonical public URL moves to `https://family.agent-ia.mx` (retired on-prem
apex, now free). API on `https://api-family.agent-ia.mx`.

## Context / constraints

- **.91 is a shared, busy box.** Already runs school-admin, medical-omnichannel,
  platform, vault, and monitoring stacks (all rootless podman compose). Migration
  must not disturb them.
- **Global rootless rules apply** (same profile as decommissioned .99, per
  `~/.claude/CLAUDE.md`):
  - Rule 1 — **NEVER `sudo podman`** as jc's storage. `sudo podman` registers a
    system-level healthcheck timer that rewrites rootless overlay JSON as root and
    corrupts storage. Always rootless as `jc`.
  - Rule 3 — user-level systemd unit (`~/.config/systemd/user/`,
    `WantedBy=default.target`), not system unit with `User=jc`.
  - Rule 4 — volume ownership matches container UID via `podman unshare chown`:
    postgres `70:70`, redis `999:1000`, receipt_uploads `1000:1000` (appuser).
  - Rule 5 — **DNS service-name collision.** The box already has `postgres`/`redis`
    service names in other stacks' networks. Our stack must address DB/redis by
    **unique container name**, not bare `postgres`/`redis`.
- **CF tunnel token must be fresh** — reusing one token across hosts caused CF to
  load-balance to stale stacks before (multi-VM incident, 2026-05-27). New named
  tunnel, new token, unique to .91.
- **No host-port publishing** — CF tunnel container reaches frontend/backend by
  container DNS over our own bridge network. Avoids port collision with the box's
  other stacks and keeps postgres/redis unreachable off-stack.
- **LiteLLM unchanged** — AI (receipt scanner, auto-translate, Jarvis) routes to
  the on-prem proxy `https://litellm.agent-ia.mx` (same LAN). `LITELLM_API_KEY`
  must equal the proxy's `LITELLM_MASTER_KEY` (else 401 token_not_found).

## Chosen approach

**New compose file + rootless deploy script** (rejected: reuse gcp compose w/
override — carries GCS + gcp naming; quadlet .container units — full rewrite off
compose, inconsistent with the box's other stacks).

Mirrors the GCP deploy shape (rsync + build + migrate + healthcheck) but over
plain `ssh jc@10.1.0.91` with rootless `podman compose`, and stays consistent
with how school-admin/medical already run on the box.

## Deliverables (new files in repo)

| File | Purpose |
|------|---------|
| `docker-compose.onprem.yml` | .91 stack: postgres, redis, backend, frontend, tunnel — rootless-safe |
| `scripts/deploy-onprem.sh` | rsync over `ssh jc@10.1.0.91` + `podman compose build/up` + alembic + podman-native health poll + volume chown |
| `.deploy.onprem.env` | host/user/path/compose config (no gcloud) |
| `.env.onprem.example` | env template: new tunnel token, family.agent-ia.mx URLs, LiteLLM, no GCS |
| `scripts/systemd/family-task-manager.service` | user unit, `WantedBy=default.target`, brings stack up on boot |
| backup service/timer (retarget existing `family-backup.*`) | nightly `pg_dump` on host |

## Compose deltas from `docker-compose.gcp.yml`

- Container names `gcp_family_*` → `family_onprem_*` (unique on the box).
- **DB/redis addressed by unique container name** (Rule 5):
  - `DATABASE_URL=postgresql+asyncpg://<user>:<pw>@family_onprem_db:5432/<db>`
  - `REDIS_URL=redis://family_onprem_redis:6379/0`
- Drop `GCS_RECEIPT_BUCKET`. Receipts + gig proofs stay on local named volume
  `receipt_uploads` (`/app/uploads`).
- Keep `internal: true` on the backend network (netavark supports rootless internal).
- Keep tunnel service; token from env (`CLOUDFLARE_TUNNEL_TOKEN`).
- No `sudo`, no `ports:` publishing.
- Keep healthchecks, restart policy, memory limits.

## Rootless correctness

- After first `up`, chown named volumes via `podman unshare chown -R`:
  postgres `70:70`, redis `999:1000`, receipt_uploads `1000:1000`. Idempotent step
  in deploy script (fixes `InsufficientPrivilege` / receipt `Permission denied`).
- Deploy-script health-wait uses `podman inspect --format '{{.State.Health.Status}}'`
  per container — **not** the docker-compose `ps --format json` grep that
  `deploy-gcp.sh` uses (podman's json keys differ).
- Boot persistence: user systemd unit + existing linger (`Linger=yes` confirmed).

## Ingress — new Cloudflare tunnel

- New named tunnel (e.g. `family-onprem`), fresh token. Per-stack `cloudflared`
  container in the compose (bridge net + container DNS, like the GCP stack — not
  the .99 host cloudflared).
- Public hostnames (both single-label under `agent-ia.mx` → covered by universal
  `*.agent-ia.mx` SSL):
  - `family.agent-ia.mx` → `http://frontend:3000`
  - `api-family.agent-ia.mx` → `http://backend:8000`
  - (`api.family.agent-ia.mx` would be two-level, NOT under universal cert — hence
    the flat `api-family` form, same reasoning as the GCP `api-gcp-family`.)
- Tunnel creation + hostname routes: attempt via `cloudflared` / CF API where
  locally authed; otherwise Juan creates the tunnel in Zero Trust and pastes the
  token, and I supply exact route values.

## Config / external touchpoints

`.env` on .91 (from `.env.onprem.example`):
- `PUBLIC_API_URL=https://api-family.agent-ia.mx`
- `ALLOWED_ORIGINS=https://family.agent-ia.mx`
- email link base → `https://family.agent-ia.mx` (email links build from the
  frontend origin, not the API origin)
- `CLOUDFLARE_TUNNEL_TOKEN=<new tunnel token>`
- `LITELLM_API_BASE=https://litellm.agent-ia.mx`, `LITELLM_API_KEY=<proxy master key>`

External, requires Juan's dashboard action:
- Add `https://family.agent-ia.mx` to Google OAuth authorized JS origins + redirect
  URIs (Google Cloud console).
- Check PayPal return/webhook URLs for hardcoded `gcp-family`.
- Repo grep for hardcoded old hostnames (`gcp-family`, `api-gcp-family`) before
  cutover; parameterize any found.

## Cutover runbook (one-shot, brief downtime)

1. Build + start stack on .91; `alembic upgrade head` against empty DB.
2. Verify stack healthy internally (curl frontend + backend `/health` inside box).
3. Final `pg_dump` from GCP prod DB; `rsync` `receipt_uploads` files GCP → .91.
4. Stop GCP backend + frontend (halt writes).
5. Restore dump into .91 postgres; load receipt files into the .91 volume.
6. Bring up .91 tunnel; add CF public-hostname routes + DNS.
7. Verify public: `https://family.agent-ia.mx` + `https://api-family.agent-ia.mx/health`.

Expected downtime ~10–20 min (family app, low traffic).

## GCP decommission (after verified)

- Stop the GCP tunnel container first (prevents dual-serving / CF load-balance to
  stale stack).
- Stop the GCP stack.
- Keep the final DB dump locally and on .91.
- Delete the GCP VM.
- Retire `gcp-family.*` + `api-gcp-family.*` CF hostnames.

## Verification

- Public curls return healthy (200/redirect).
- Login flow (cookie auth) works on new origin.
- Receipt scan works (LiteLLM path reachable from .91).
- A gig-proof image loads via the frontend proxy (volume present + perms correct).
- Nav SSR sanity (Inbox + Chat links in the SSR bundle) — port the check to the
  onprem container name.

## Docs / memory updates

- `CLAUDE.md` production section: canonical prod = .91 rootless podman; add on-prem
  ops incantations (rootless, no sudo); mark GCP decommissioned like the .99 note.
- Memory: new project entry for the .91 prod home + the fresh-tunnel constraint.

## Out of scope

- No app feature changes. Pure infra move.
- No schema changes beyond running existing alembic head.
- Redis data not migrated (sessions ephemeral — users re-login).
