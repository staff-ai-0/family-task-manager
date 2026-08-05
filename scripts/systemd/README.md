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

## RESTORE DRILL

```bash
cd /home/jc/family-task-manager
./scripts/restore-drill.sh                 # newest scheduled dump
./scripts/restore-drill.sh <dump.sql.gz>   # a specific one
```

Restores into a **throwaway** postgres container, compares table and row
counts against live, and drops the container. The live DB is only ever read
(`SELECT count(*)`), so this is safe to run on prod at any time. Exits
non-zero — and says why — if the dump does not restore or comes back short.

Scheduled weekly by `family-onprem-restore-drill.timer` (Sun 04:30, after the
6-hourly backup so it always drills a fresh dump). Install it the same way as
the backup units above:

```bash
systemctl --user enable --now family-onprem-restore-drill.timer
systemctl --user start family-onprem-restore-drill.service   # run once now
journalctl --user -u family-onprem-restore-drill.service -n 40
```

**Why this is a script and a timer instead of a manual quarterly checklist:**
the manual version that used to live here hardcoded `CREATE ROLE jarvis_mcp`,
because that is the role the 2026-07-07 drill happened to hit. `pg_dump` emits
GRANTs to cluster roles but never the roles themselves, so the restore dies on
whichever role is missing — and under `--single-transaction` that rolls back
*everything*. When the monitoring stack later added `grafana_ro`, whose GRANT
sorts first, both this checklist and `restore-db.sh` walked straight past it.
From then until 2026-08-04 every backup completed cleanly and restored zero
tables. Nobody re-ran the quarterly drill, so nobody found out.

`restore-db.sh` now derives the role set from the dump being restored, and
`backup-db.sh` writes a `globals-<ts>.sql.gz` (`pg_dumpall --globals-only`)
alongside each dump so roles come back with their real attributes and
passwords instead of NOLOGIN placeholders. A dump restored *without* its
globals sidecar still works, but any role needing LOGIN (e.g. `grafana_ro`
for the metrics exporter) must have its password reset afterwards.

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
