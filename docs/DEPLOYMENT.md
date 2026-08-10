# Family Task Manager — Deployment

> Canonical ops context lives in [CLAUDE.md](../CLAUDE.md) (environments, tunnel wiring, rollback paths). This page is the hands-on runbook.

## Production Target (since 2026-07-05)

- **Host**: on-prem `10.1.0.91` (RHEL 10, rootless podman, user `jc`) — SHARED box; **never `sudo podman`**
- **App dir**: `/home/jc/family-task-manager/`
- **Compose file**: `docker-compose.onprem.yml`
- **Public URLs**: `https://family.agent-ia.mx` (frontend) + `https://api-family.agent-ia.mx` (backend) via Cloudflare Tunnel `family-onprem`
- **Secrets**: `.env` on the host (template `.env.onprem.example`); no Vault in the live path

## Deploy

```bash
./scripts/deploy-onprem.sh              # full: backup → rsync → rollback point → build → migrate → up → smoke
DEPLOY_DRY_RUN=1 ./scripts/deploy-onprem.sh -y   # print remote commands only
```

Deploy config (SSH target, paths) lives in `.deploy.onprem.env`.

The script does a scoped `down` + re-pins network DNS + `up` — never hand-roll `podman compose up -d` after a rebuild; partial recreate can silently keep the stale image running.

## Manual Operations (after SSH)

```bash
ssh jc@10.1.0.91
cd /home/jc/family-task-manager
DC="podman compose --env-file .env -f docker-compose.onprem.yml"

$DC ps                          # state
podman logs -f family_onprem_backend
$DC exec -T backend alembic upgrade head
```

## Backups

- `./scripts/backup-db.sh` — on-demand dump (also runs automatically at the start of each deploy). Writes three artifacts per run: `db-<ts>.sql.gz`, `globals-<ts>.sql.gz` (cluster roles — `pg_dump` does NOT contain them) and `uploads-<ts>.tar.gz`.
- `./scripts/restore-db.sh` — restore helper
- `./scripts/restore-drill.sh` — **proves the newest backup actually restores**, into a throwaway container; reads live only. Run it after any change to the backup/restore path.
- systemd timers in `scripts/systemd/` schedule host-side dumps (`family-onprem-backup.*`, every 6h) and the weekly restore drill (`family-onprem-restore-drill.*`, Sun 04:30)

> A dump and its `globals-` sidecar belong together: restoring into a fresh
> cluster without the roles the dump GRANTs to aborts the whole
> `--single-transaction` restore and recovers nothing. This is not theoretical
> — it was true of every production backup between 2026-07-07 and 2026-08-04.
> Keep them in the same directory (and the same offsite push) so
> `restore-db.sh` finds the pair automatically.

## Database Migrations

Alembic only. CI (`.github/workflows/ci.yml`) exercises `upgrade head → downgrade -1 → upgrade head` on every PR; the deploy script runs `alembic upgrade head` against the freshly built image before switching traffic.

## Rollback

1. **Images**: the deploy script tags the previously running backend/frontend images as a rollback point before rebuilding — retag + `up` to revert.
1a. **Database**: restoring from a dump is only a real option because the drill proves it. Before relying on a specific backup, run `./scripts/restore-drill.sh <that dump>` — it takes ~30s and tells you whether that file recovers anything at all.
2. **GCP (last resort)**: the decommissioned GCP VM (`family-app`, project `family-prod`) still has its volumes; `scripts/deploy-gcp.sh` + `docker-compose.gcp.yml` + the pre-cutover dump `backups/prod-cutover-gcp-20260705.sql` can resurrect it. Reassess before using — DNS/tunnel need switching back.

## Decommissioned targets

- **GCP `family-app`** — stopped 2026-07-05 (kept for rollback, see above)
- **On-prem 10.1.0.99** — stopped 2026-05-23; do not redeploy the app there (the box still hosts the shared LiteLLM proxy)

## Granting super-admin access

The operator console at `/admin` requires **two** independent grants plus a
network-level gate. There is deliberately no UI for either grant — this is a
manual, auditable act, and each of the two is insufficient on its own:
`require_superadmin` (`backend/app/core/dependencies.py`) checks both
`users.is_superadmin` and the `SUPERADMIN_EMAILS` allowlist, and rejects with
404 (not 403) if either is missing — so a caller who has only one of the two
can't even tell the surface exists.

1. **Env allowlist** — on the production host, add the operator's email to
   `SUPERADMIN_EMAILS` in `.env` (comma-separated, matched case-insensitively):

   ```bash
   SUPERADMIN_EMAILS=juan.mtz79@gmail.com
   ```

   Then redeploy so the backend picks it up: `./scripts/deploy-onprem.sh`.

2. **DB flag** — on the production host, as user `jc` (never `sudo podman` —
   see the rootless-storage rules in the root `CLAUDE.md`), flip
   `users.is_superadmin` for that account directly in postgres. The postgres
   container is `family_onprem_db` (see `docker-compose.onprem.yml` —
   it is *not* `family_onprem_postgres`), and the app DB user/name are both
   `familyapp` (`.env` → `POSTGRES_USER` / `POSTGRES_DB`):

   ```bash
   ssh jc@10.1.0.91 'podman exec family_onprem_db \
     psql -U familyapp -d familyapp -c \
     "UPDATE users SET is_superadmin = true WHERE email = '\''juan.mtz79@gmail.com'\'';"'
   ```

3. **Cloudflare Access** — in the Zero Trust dashboard, create an Access
   application scoped to the **path** `family.agent-ia.mx/admin*`, with a
   policy allowing only that email. It must be a path policy on the existing
   hostname, not a separate subdomain: the app's auth cookies
   (`frontend/src/lib/auth-cookies.ts`) are set with no `Domain=` attribute,
   so they are host-only to `family.agent-ia.mx` — a policy on any other
   hostname (e.g. `admin.family.agent-ia.mx`) would front a page that never
   receives a session cookie and can never authenticate. Don't "simplify"
   this into a subdomain later.

   This Access policy is a **page-level** gate only: it fronts the `/admin*`
   HTML pages, not the API. Every XHR those pages make goes to
   `api-family.agent-ia.mx/api/admin/...` — a different hostname, outside
   the `/admin*` path pattern, and not covered by this policy at all. That
   is not a hole: `frontend/src/middleware.ts` blocks unauthenticated/non-
   operator requests to both `/admin*` and `/api/admin*` before they reach
   the backend, and the backend's own `require_superadmin` dependency
   (checked independently, per request) is what actually authorizes every
   `/api/admin/*` call. Cloudflare Access is an extra, coarse, network-edge
   layer in front of the pages — not the mechanism protecting the API.

Revoking access means pulling grant 1, grant 2, *or* the Cloudflare Access
policy — any one alone is sufficient to lock the operator out of the parts
it covers: pulling grant 1 or grant 2 blocks `require_superadmin` entirely
(both the pages and every `/api/admin/*` call, since the backend check does
not depend on Access), while pulling the Access policy only blocks loading
the `/admin*` pages themselves — see the page-level-gate note above.
Every action taken through the console is recorded in `operator_audit_log`
(`backend/app/models/operator_audit.py`), which carries no foreign keys and
therefore survives the purge of any family it describes.
