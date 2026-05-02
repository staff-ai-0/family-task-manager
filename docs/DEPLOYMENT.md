# Family Task Manager — Deployment

## Production Target

- **Host**: `10.1.0.99` (RHEL 10, podman 5.6 rootless)
- **App dir**: `/mnt/nvme/docker-prod/family-task-manager/`
- **Compose file**: `docker-compose.yml` (single file is prod-ready; `docker-compose.stage.yml` for staging only)
- **Public URL**: `https://family.agent-ia.mx` (Cloudflare Tunnel)
- **Backend URL**: `https://fam-backend.agent-ia.mx` (Cloudflare Tunnel)

## Prerequisites

- SSH access to `10.1.0.99` as `jc` (key in `~/.ssh/`)
- Clean working tree on local machine (deploy script refuses dirty state)
- Vault periodic token in prod `.env` (rotated per memory)

## Deploy

```bash
./deploy-prod.sh
```

The script:
1. Verifies clean git state
2. SSHes to `10.1.0.99`
3. `git pull` in `/mnt/nvme/docker-prod/family-task-manager/`
4. `sudo docker compose` (docker-compatible shim over podman) build + up -d
5. Runs `alembic upgrade head` inside backend container
6. Health-checks `/api/sync/health` (expects HTTP 410 — sync deprecation marker)

## Manual Operations (after SSH)

```bash
ssh jc@10.1.0.99
cd /mnt/nvme/docker-prod/family-task-manager
DC="podman compose --env-file .env -f docker-compose.yml"

$DC ps                          # state
$DC logs -f backend             # tail
$DC exec -T backend alembic upgrade head
$DC restart backend frontend
```

## Vault

- Path: `secret/family-task-manager/prod`
- Token: periodic per-app in `.env` on host (auto-renews on use)
- Loader: `backend/app/core/config.py` reads via `vault-client-python`

To rotate the periodic token:

```bash
vault token create -policy=family-task-manager-prod -period=720h \
  -display-name=family-task-manager-prod
# Update /mnt/nvme/docker-prod/family-task-manager/.env on host
$DC restart backend
```

## File-Mode Drift (NVMe)

NVMe ext4 at `/mnt/nvme/docker-prod` mangles file modes (644→755) on `git checkout`. Per-repo workaround:

```bash
git config core.fileMode false
```

(Per workspace memory `prod_nvme_filemode_drift`.)

## Database Migrations

Always Alembic — never raw SQL. Test locally first:

```bash
docker exec family_app_backend alembic revision --autogenerate -m "description"
docker exec family_app_backend alembic upgrade head
```

In production, deploy script runs `alembic upgrade head` automatically.

## Rollback

If a deploy goes bad:

```bash
ssh jc@10.1.0.99
cd /mnt/nvme/docker-prod/family-task-manager
git log --oneline -10            # find last good commit
git checkout <good-sha>
$DC up -d --build
$DC exec -T backend alembic downgrade -1   # only if migration ran
```

## Health & Monitoring

- Backend health: `https://fam-backend.agent-ia.mx/health`
- `/api/sync/*` deprecated: returns 410 Gone (used as proof-of-life check)
- Logs: stdout via podman → host journald

## Service Ports (Production)

| Service       | Container port | Host port | Notes |
| ------------- | -------------- | --------- | ----- |
| Frontend SSR  | 3000           | 3003      | Astro 5 |
| Backend API   | 8000           | 8003      | FastAPI |
| PostgreSQL    | 5432           | 5437      | Per-family schema |
| Redis         | 6379           | 6380      | Sessions |

## Last Deployment of Note

`docs/deployments/2026-04-11.md` — cold-start deployment after `deploy-prod.sh` rewrite.
