# Sync System - Bidirectional Points ↔ Actual Budget

## Status: ✅ OPERATIONAL

**Completed**: February 26, 2026  
**Version**: 1.0.0  
**Services**: Backend API, Sync Service, Frontend UI

## What It Does

Provides bidirectional synchronization between the Family Task Manager gamified points system and Actual Budget personal finance software.

**Family → Actual Budget:**
- When children earn/spend points, transactions are created in their Actual Budget accounts
- Conversion: 1 point = $0.10 MXN (configurable)
- Account naming: "Domingo {child_name}"

**Actual Budget → Family:**
- Manual transactions in Actual Budget create point adjustments
- Enables parents to give rewards/consequences via Actual Budget UI
- Skips our own transactions to prevent loops

## Architecture

### Services
1. **Sync Service** (port 5008): Dedicated FastAPI container with cron
2. **Backend API** (port 8002): Proxy with parent authentication
3. **Frontend UI** (port 3003): Manual sync button in parent finances page
4. **Actual Budget** (port 5006): Personal finance server

### Key Files
```
services/actual-budget/
├── sync.py                 # Core logic (600+ lines)
├── sync_api.py             # REST API wrapper
├── sync_cron.sh            # Hourly auto-sync
├── setup_budget.py         # Initial setup
├── sync_state.json         # Transaction tracking
└── Dockerfile.sync         # Container with cron
```

### Deduplication
- Uses `imported_id` patterns: `ftm-delta-{user_id}-{date}`
- Skips transactions with `imported_id` starting with "ftm-"
- Tracks synced transactions in `sync_state.json`

## How to Use

### Initial Setup
```bash
# 1. Start all services
docker-compose up -d

# 2. Setup Actual Budget
docker exec family_sync_service python3 /app/setup_budget.py

# 3. Visit Actual Budget UI and set password
open http://localhost:5006
```

### Manual Sync (UI)
1. Login as parent: http://localhost:3003
2. Go to "Finanzas" tab
3. Click "Sincronizar Ahora" button
4. Wait 2-5 seconds for completion

### Manual Sync (API)
```bash
# Get auth token
TOKEN=$(curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"mom@demo.com","password":"password123"}' | \
  jq -r '.access_token')

# Trigger sync
curl -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=false" \
  -H "Authorization: Bearer $TOKEN"

# Check status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/sync/status | jq
```

### Automatic Sync
- **Schedule**: Every hour (0 * * * *)
- **Method**: Cron job in sync service container
- **Logs**: `/app/sync_cron.log` in container

```bash
# Check cron status
docker exec family_sync_service crontab -l

# View logs
docker exec family_sync_service tail -f /app/sync_cron.log
```

## Implementation Details

### Sync Flow
1. **Backend receives request** → Checks parent role
2. **Backend proxies to sync service** → Via Docker network
3. **Sync service executes sync.py** → As subprocess
4. **Family → Actual sync** → Creates transactions for point deltas
5. **Actual → Family sync** → Creates point adjustments for manual transactions
6. **State saved** → Updates sync_state.json
7. **Response returned** → Via chain back to frontend

### Conversion Logic
```python
# Points to Money
amount_dollars = points * POINTS_TO_MONEY_RATE
amount_cents = int(amount_dollars * 100)

# Money to Points
amount_dollars = amount_cents / 100
points = round(amount_dollars / POINTS_TO_MONEY_RATE)
```

### Date Handling
Actual Budget stores dates as integers (YYYYMMDD):
```python
def parse_actual_date(date_int: int) -> str:
    date_str = str(date_int)  # e.g., "20260226"
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    return datetime.date(year, month, day).isoformat()
```

## Issues Resolved

### 1. Frontend "Unexpected token '<'" Error
**Problem**: Frontend JavaScript receiving HTML instead of JSON  
**Root Cause**: Using relative URL `/api/sync/trigger` which hit Astro server  
**Solution**: Pass `PUBLIC_API_BASE_URL` to client-side JavaScript

### 2. CORS "Failed to fetch" Error  
**Problem**: Browser blocking cross-origin request from port 3003 to 8002  
**Root Cause**: Port 3003 not in ALLOWED_ORIGINS  
**Solution**: Added port 3003 to CORS middleware

### 3. Date Parsing "AttributeError: 'int' object has no attribute 'isoformat'"
**Problem**: Trying to call .isoformat() on integer date  
**Root Cause**: Actual Budget uses YYYYMMDD integer format  
**Solution**: Created `parse_actual_date()` helper function

### 4. Docker Network vs Localhost URLs
**Problem**: Server-side using `http://backend:8000`, client-side needs `http://localhost:8002`  
**Root Cause**: Two different contexts (server SSR vs browser)  
**Solution**: Separate env vars: `API_BASE_URL` (server) and `PUBLIC_API_BASE_URL` (client)

## Environment Configuration

### Sync Service
```bash
ACTUAL_SERVER_URL=http://actual-server:5006
ACTUAL_PASSWORD=changeme
ACTUAL_BUDGET_NAME=My Finances
FAMILY_API_URL=http://backend:8000
FAMILY_API_EMAIL=mom@demo.com
FAMILY_API_PASSWORD=password123
POINTS_TO_MONEY_RATE=0.10
POINTS_TO_MONEY_CURRENCY=MXN
```

### Frontend
```bash
API_BASE_URL=http://backend:8000           # Server-side SSR
PUBLIC_API_BASE_URL=http://localhost:8002  # Client-side browser
```

### Backend
```bash
ALLOWED_ORIGINS=http://localhost:3003,http://localhost:8080
```

## Testing

### Test Sync
```bash
# 1. Check current points
TOKEN=$(curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"mom@demo.com","password":"password123"}' | jq -r '.access_token')

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/families/me | \
  jq '.members[] | select(.role != "parent") | {name, points}'

# 2. Dry run
curl -s -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=true" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.output'

# 3. Actual sync
curl -s -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=false" \
  -H "Authorization: Bearer $TOKEN" | jq '.status'
```

### Add Test Transactions
```bash
docker exec family_sync_service python3 /app/add_test_transactions.py
```

## Known Limitations

1. **Point Adjustment Limits**: Family API has ±1000 point limit per adjustment
2. **Timeout**: 130-second timeout on sync operations
3. **Single Currency**: Currently only supports MXN
4. **No Conflict Resolution**: Last sync wins, no merge strategy
5. **No Sync History UI**: Can't view past sync operations (yet)

## Monitoring

### Health Checks
```bash
# Sync service health
curl http://localhost:5008/health | jq

# Backend proxy health
curl http://localhost:8002/api/sync/health | jq

# Sync status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/sync/status | jq
```

### Logs
```bash
# Sync service
docker logs -f family_sync_service

# Backend sync routes
docker logs -f family_app_backend | grep sync

# Cron job
docker exec family_sync_service tail -f /app/sync_cron.log
```

### State File
```bash
# View current sync state
cat services/actual-budget/sync_state.json | jq

# Check synced members
jq '.synced_members' services/actual-budget/sync_state.json

# Check synced transactions
jq '.synced_to_actual | length' services/actual-budget/sync_state.json
jq '.synced_from_actual | length' services/actual-budget/sync_state.json
```

## Security

- **Parent-only access**: Only users with role="parent" can trigger sync
- **No child access**: Children cannot see sync status or trigger syncs
- **Credentials in env vars**: No hardcoded passwords
- **CORS protection**: Only allowed origins can call API
- **JWT authentication**: All sync endpoints require valid token

## Future Work

- [ ] Sync history/logs UI
- [ ] Webhook triggers for real-time sync
- [ ] Multi-currency support
- [ ] Per-family sync schedules
- [ ] Conflict resolution UI
- [ ] Transaction categorization
- [ ] Budget vs spending reports
- [ ] Email notifications on sync failures
- [ ] Retry logic for failed syncs
- [ ] Sync performance metrics

## References

- Architecture: `.github/instructions/06-sync-architecture.md`
- Setup guide: `AGENTS.md`
- Code: `services/actual-budget/`
- API docs: http://localhost:8002/docs (search "sync")
