# Scheduled backups (canonical: on-prem 10.1.0.91)

Daily PostgreSQL + uploads-volume backups for the canonical prod host
**10.1.0.91** (rootless podman, user `jc`). Closes the 2026-07-07 audit gaps:
no offsite copy (CRITICAL), uploads volume never backed up (HIGH), restore
defaults pointing at the decommissioned GCP path (HIGH).

Rootless rules apply on this host: **never `sudo podman`**, user-level
systemd units only (see `~/.claude/CLAUDE.md` global rules).

## What it does

`scripts/backup-db.sh` (run by the `family-onprem-backup.timer` user unit):

1. `pg_dump`s the postgres container → `backups/scheduled/db-<ts>.sql.gz`
2. `podman volume export`s the `receipt_uploads` volume (gig proof photos,
   receipt images) → `backups/scheduled/uploads-<ts>.tar.gz`
3. Prunes local artifacts older than `RETENTION_DAYS` (default 14)
4. If `OFFSITE_RCLONE_REMOTE` is set, `rclone copy`s both artifacts to
   `<remote>/scheduled/` and prunes remote copies older than
   `OFFSITE_RETENTION_DAYS` (default 30). **Any offsite failure exits
   non-zero**, so the unit shows as failed.

Restore with `scripts/restore-db.sh` (see below).

## Install (one-time, on 10.1.0.91, as user jc — NO sudo)

```bash
cd /home/jc/family-task-manager
chmod +x scripts/backup-db.sh scripts/restore-db.sh

mkdir -p ~/.config/systemd/user
cp scripts/systemd/family-onprem-backup.service ~/.config/systemd/user/
cp scripts/systemd/family-onprem-backup.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now family-onprem-backup.timer

# Verify
systemctl --user list-timers family-onprem-backup.timer
systemctl --user start family-onprem-backup.service   # run once now
ls -lh backups/scheduled/
```

(`loginctl enable-linger jc` is already set on the host, so user timers fire
without an open session.)

## Offsite setup (rclone, as user jc)

Backups on the same disk as the live DB are not backups. One-time setup:

```bash
# 1. Install rclone (the only sudo step — package install, not podman)
sudo dnf install -y rclone     # or: https://rclone.org/install/

# 2. Configure a remote AS USER jc (config lands in ~/.config/rclone/rclone.conf)
rclone config                  # e.g. name "b2-family", type b2 (or s3/r2/gcs/sftp)

# 3. Smoke-test the remote
rclone mkdir b2-family:family-backups/scheduled
rclone lsd b2-family:family-backups

# 4. Enable the push: uncomment in ~/.config/systemd/user/family-onprem-backup.service
#      Environment=OFFSITE_RCLONE_REMOTE=b2-family:family-backups
#      Environment=OFFSITE_RETENTION_DAYS=30
#    (keep the repo copy scripts/systemd/family-onprem-backup.service in sync)
systemctl --user daemon-reload
systemctl --user start family-onprem-backup.service

# 5. Verify the copy landed offsite
rclone ls b2-family:family-backups/scheduled | tail
```

Until `OFFSITE_RCLONE_REMOTE` is set, every run prints a loud
`backups exist ONLY on this host` warning to stderr. Once set, a failed push
(bad credentials, network down, missing rclone) makes the run exit non-zero:

```bash
systemctl --user status family-onprem-backup.service   # shows failed
journalctl --user -u family-onprem-backup.service -n 50
```

## Environment variables (set in the .service, all optional)

| Var | Default | Purpose |
|-----|---------|---------|
| `COMPOSE_CMD` | `podman compose` | set in the unit (also the script default) |
| `COMPOSE_FILE` | `docker-compose.onprem.yml` | set in the unit (also the script default) |
| `PG_SERVICE` | `postgres` | compose service name (`db` in local dev compose) |
| `BACKUP_DIR` | `backups/scheduled` | where artifacts land (relative to `APP_DIR`) |
| `RETENTION_DAYS` | `14` | local prune age |
| `UPLOADS_VOLUME` | autodetect | override `<project>_receipt_uploads` detection |
| `SKIP_UPLOADS` | unset | `1` = DB dump only (docker-only GCP rollback host) |
| `OFFSITE_RCLONE_REMOTE` | unset | e.g. `b2-family:family-backups`; unset = no push |
| `OFFSITE_RETENTION_DAYS` | `30` | remote prune age |

## Restore

```bash
cd /home/jc/family-task-manager

# DB only (prompts for a typed 'restore' — it overwrites current data)
./scripts/restore-db.sh backups/scheduled/db-YYYYMMDD-HHMMSS.sql.gz

# Uploads volume only
./scripts/restore-db.sh --uploads backups/scheduled/uploads-YYYYMMDD-HHMMSS.tar.gz

# Both
./scripts/restore-db.sh --uploads backups/scheduled/uploads-....tar.gz backups/scheduled/db-....sql.gz

# Pull a copy back from offsite first if the host disk is gone:
rclone copy b2-family:family-backups/scheduled/db-YYYYMMDD-HHMMSS.sql.gz /tmp/
```

Defaults target the on-prem host (`podman compose` +
`docker-compose.onprem.yml`). For the decommissioned GCP rollback host only:
`COMPOSE_FILE=docker-compose.gcp.yml COMPOSE_CMD="sudo docker compose" ./scripts/restore-db.sh ...`

## RESTORE DRILL (run quarterly; ~5 minutes; zero risk to prod)

Restores the latest scheduled dump into a **scratch postgres container**,
runs a sanity query, and drops it. Does not touch the prod DB or volumes.

```bash
cd /home/jc/family-task-manager
POSTGRES_USER="$(sed -n 's/^POSTGRES_USER=//p' .env | tail -1)"
POSTGRES_DB="$(sed -n 's/^POSTGRES_DB=//p' .env | tail -1)"
LATEST="$(ls -1t backups/scheduled/db-*.sql.gz | head -1)"
echo "drilling with: $LATEST"

# 1. Scratch postgres (same major version as prod), throwaway volume
podman run -d --name family_restore_drill \
  -e POSTGRES_USER="$POSTGRES_USER" \
  -e POSTGRES_PASSWORD=drill \
  -e POSTGRES_DB="$POSTGRES_DB" \
  docker.io/library/postgres:15-alpine

# 2. Wait until it accepts connections
until podman exec family_restore_drill pg_isready -U "$POSTGRES_USER" >/dev/null 2>&1; do sleep 1; done

# 3. Recreate cluster-level roles the dump GRANTs to (pg_dump does NOT
#    include roles — without this, ON_ERROR_STOP aborts on the first GRANT;
#    found in the 2026-07-07 drill: role "jarvis_mcp" does not exist)
podman exec family_restore_drill psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'CREATE ROLE jarvis_mcp NOLOGIN;'

# 4. Restore the dump (dumps are --clean --if-exists, so a fresh DB is fine)
gunzip -c "$LATEST" | podman exec -i family_restore_drill \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# 5. Sanity query — row counts must be non-zero and look plausible
podman exec family_restore_drill psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT (SELECT count(*) FROM families) AS families,
          (SELECT count(*) FROM users) AS users,
          (SELECT count(*) FROM task_assignments) AS task_assignments,
          (SELECT max(created_at) FROM users) AS newest_user;"

# 6. Tear down
podman rm -f family_restore_drill
```

Record each drill (date, dump file, row counts, elapsed time) below:

| Date | Dump | Result |
|------|------|--------|
| 2026-07-07 | local-dev `db-20260707-182407.sql.gz` | PASS after adding step 3 (first attempt aborted: `role "jarvis_mcp" does not exist` — pg_dump omits cluster roles). 3 families / 6 users / 68 task_assignments restored in ~2 s. **Prod drill on 10.1.0.91 still pending.** |

## Legacy: GCP VM units (decommissioned 2026-07-05)

`family-backup.service` / `family-backup.timer` are the old SYSTEM-level units
for the GCP VM (`sudo docker compose`, `/etc/systemd/system/`). Kept for
rollback reference only — do not install them on 10.1.0.91. If ever used
again, run the script with
`COMPOSE_FILE=docker-compose.gcp.yml COMPOSE_CMD="sudo docker compose" SKIP_UPLOADS=1`.
