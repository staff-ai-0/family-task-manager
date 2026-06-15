# Scheduled DB backups (GCP VM)

Daily PostgreSQL backups for the `family-app` GCP VM. Closes audit gap M7
(previously: backups only ran at deploy time, no schedule, no restore script).

## What it does

`scripts/backup-db.sh` (run by the timer) `pg_dump`s the postgres container to
`backups/scheduled/db-<timestamp>.sql.gz` and prunes dumps older than
`RETENTION_DAYS` (default 14). Restore with `scripts/restore-db.sh <file>`.

## Install (one-time, on the VM, as a sudoer)

```bash
cd /home/jc/family-task-manager
chmod +x scripts/backup-db.sh scripts/restore-db.sh

sudo cp scripts/systemd/family-backup.service /etc/systemd/system/
sudo cp scripts/systemd/family-backup.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-backup.timer

# Verify
systemctl list-timers family-backup.timer
sudo systemctl start family-backup.service   # run once now
ls -lh backups/scheduled/
```

## Restore

```bash
cd /home/jc/family-task-manager
./scripts/restore-db.sh backups/scheduled/db-YYYYMMDD-HHMMSS.sql.gz
# (prompts for a typed 'restore' confirmation — it overwrites current data)
```

## Off-VM durability (TODO)

These dumps live on the same boot disk as the DB — a disk loss takes both. To
get off-VM durability, uncomment the `gsutil cp` block at the bottom of
`backup-db.sh` and grant the VM service account `roles/storage.objectCreator`
on a backups bucket. (school-admin uses `gs://icegg-db-backups-prod/` with the
same pattern.)
