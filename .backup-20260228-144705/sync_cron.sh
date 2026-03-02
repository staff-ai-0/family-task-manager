#!/bin/sh
# Cron job to run hourly sync
# This script is executed by cron every hour

echo "[$(date)] Starting automatic sync..." >> /app/sync_cron.log

# Run the sync via the sync API
python3 -c "
import httpx
import sys
from datetime import datetime

try:
    response = httpx.post(
        'http://localhost:5008/trigger',
        json={'direction': 'both', 'dry_run': False},
        timeout=130.0
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f'[{datetime.now()}] Sync completed: {result.get(\"status\")}', file=sys.stderr)
        sys.exit(0)
    else:
        print(f'[{datetime.now()}] Sync failed: HTTP {response.status_code}', file=sys.stderr)
        sys.exit(1)
        
except Exception as e:
    print(f'[{datetime.now()}] Sync error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>> /app/sync_cron.log

echo "[$(date)] Sync completed" >> /app/sync_cron.log
