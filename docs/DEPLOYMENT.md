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
./scripts/deploy-onprem.sh --dry-run    # print remote commands only
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

- `./scripts/backup-db.sh` — on-demand dump (also runs automatically at the start of each deploy)
- `./scripts/restore-db.sh` — restore helper
- systemd timers in `scripts/systemd/` (`family-onprem-backup.*`) schedule host-side dumps

## Database Migrations

Alembic only. CI (`.github/workflows/ci.yml`) exercises `upgrade head → downgrade -1 → upgrade head` on every PR; the deploy script runs `alembic upgrade head` against the freshly built image before switching traffic.

## Rollback

1. **Images**: the deploy script tags the previously running backend/frontend images as a rollback point before rebuilding — retag + `up` to revert.
2. **GCP (last resort)**: the decommissioned GCP VM (`family-app`, project `family-prod`) still has its volumes; `scripts/deploy-gcp.sh` + `docker-compose.gcp.yml` + the pre-cutover dump `backups/prod-cutover-gcp-20260705.sql` can resurrect it. Reassess before using — DNS/tunnel need switching back.

## Decommissioned targets

- **GCP `family-app`** — stopped 2026-07-05 (kept for rollback, see above)
- **On-prem 10.1.0.99** — stopped 2026-05-23; do not redeploy the app there (the box still hosts the shared LiteLLM proxy)
