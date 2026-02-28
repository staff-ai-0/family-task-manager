# Sync Architecture - Bidirectional Points ↔ Actual Budget

## Overview

The Family Task Manager integrates with Actual Budget to provide bidirectional synchronization between the gamified points system and real financial transactions. This allows families to:

1. **Track rewards financially**: Points earned become real money in Actual Budget
2. **Manage allowances**: Manual transactions in Actual Budget update child points
3. **Maintain consistency**: Automatic syncing keeps both systems aligned

## Architecture

### Sync Service Container

**Container**: `family_sync_service` (port 5008)  
**Base**: Python 3.12 with FastAPI + Cron  
**Purpose**: Dedicated service for sync operations

**Key Components:**
```
services/actual-budget/
├── sync.py                 # Core bidirectional sync logic (600+ lines)
├── sync_api.py             # FastAPI REST wrapper
├── sync_cron.sh            # Hourly automatic sync
├── setup_budget.py         # Initial Actual Budget configuration
├── sync_state.json         # Transaction tracking state
└── Dockerfile.sync         # Container with cron + API
```

### Communication Flow

```
┌─────────────────┐
│  Frontend UI    │ (Parent clicks sync button)
│  Port 3003      │
└────────┬────────┘
         │ POST /api/sync/trigger
         ↓
┌─────────────────┐
│  Backend API    │ (Proxy with auth check)
│  Port 8002      │
└────────┬────────┘
         │ POST http://sync-service:5008/trigger
         ↓
┌─────────────────┐
│  Sync Service   │ (Execute sync script)
│  Port 5008      │
└────┬───────┬────┘
     │       │
     ↓       ↓
  Family   Actual
   API     Budget
```

## Bidirectional Sync Logic

### Direction 1: Family → Actual Budget

**When**: Child earns/spends points in Family Task Manager  
**Action**: Create transaction in Actual Budget account

**Process:**
1. Get all children from Family API
2. For each child, compare current points vs last synced points
3. Calculate delta (positive or negative)
4. Create transaction in child's Actual Budget account
5. Use `imported_id = ftm-delta-{user_id}-{date}` for deduplication
6. Update sync state with new totals

**Example:**
```
Emma: 165 points (last synced: 150)
Delta: +15 points = +$1.50 MXN
→ Create transaction in "Domingo Emma Johnson" account
```

### Direction 2: Actual Budget → Family

**When**: Parent manually adds transaction in Actual Budget  
**Action**: Create point adjustment in Family Task Manager

**Process:**
1. Get all child accounts from Actual Budget
2. For each account, get transactions not yet synced
3. Skip transactions with `imported_id` starting with `ftm-` (our own)
4. Convert money to points (amount ÷ rate)
5. Create point adjustment via Family API
6. Track transaction ID in sync state to prevent re-sync

**Example:**
```
Transaction in "Domingo Emma Johnson":
+$2.00 MXN for "Ice cream reward"
→ Create +20 points adjustment in Family Task Manager
```

## Conversion Rate

**Default**: 1 point = $0.10 MXN  
**Configurable**: Set `POINTS_TO_MONEY_RATE` environment variable

**Examples:**
- 100 points = $10.00 MXN
- 50 points = $5.00 MXN
- -30 points = -$3.00 MXN

## Deduplication Strategy

**Problem**: Prevent infinite sync loops where transactions keep bouncing between systems

**Solution**: Use unique `imported_id` patterns

### Family → Actual
```python
imported_id = f"ftm-delta-{user_id}-{date}"
# Example: ftm-delta-3d8d403b-2026-02-26
```

### Actual → Family
```python
# Skip any transaction where:
if tx.imported_id and tx.imported_id.startswith("ftm-"):
    continue  # This is our own transaction, don't sync back
```

### State Tracking
```json
{
  "synced_to_actual": {
    "ftm-delta-abc-2026-02-26": {
      "child_id": "abc",
      "actual_tx_id": "xyz",
      "points": 165,
      "amount": 16.5,
      "synced_at": "2026-02-26"
    }
  },
  "synced_from_actual": {
    "actual-tx-xyz": {
      "child_id": "abc",
      "points": 20,
      "amount": 2.0,
      "synced_at": "2026-02-26"
    }
  }
}
```

## API Endpoints

### Backend Proxy (Auth Required)

**POST `/api/sync/trigger`**
```bash
# Trigger manual sync
curl -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=false" \
  -H "Authorization: Bearer $TOKEN"

# Query Parameters:
# - direction: "both" | "to_actual" | "from_actual"
# - dry_run: true | false
```

**GET `/api/sync/status`**
```bash
# Get sync state
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/sync/status
```

**GET `/api/sync/health`**
```bash
# Check sync service health
curl http://localhost:8002/api/sync/health
```

### Sync Service Direct (Internal)

**POST `/trigger`**
```json
{
  "direction": "both",
  "dry_run": false
}
```

**GET `/status`**
```json
{
  "last_sync": "2026-02-26",
  "synced_members": {...},
  "synced_to_actual": {...},
  "synced_from_actual": {...}
}
```

**GET `/health`**
```json
{
  "healthy": true,
  "checks": {
    "sync_script_exists": true,
    "sync_state_exists": true,
    "can_execute_sync_script": true
  },
  "timestamp": "2026-02-26T..."
}
```

## Automatic Sync (Cron)

**Schedule**: Every hour (0 * * * *)  
**Script**: `/app/sync_cron.sh`  
**Logs**: `/app/sync_cron.log`

**Cron Configuration:**
```bash
# In Dockerfile.sync
RUN echo "0 * * * * /app/sync_cron.sh" | crontab -

# Start cron on container startup
CMD service cron start && uvicorn sync_api:app --host 0.0.0.0 --port 5008
```

**Check cron status:**
```bash
docker exec family_sync_service crontab -l
docker exec family_sync_service tail -f /app/sync_cron.log
```

## Environment Variables

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

### Backend API
```bash
# No additional config needed - uses httpx to call sync service
SYNC_SERVICE_URL=http://sync-service:5008  # Docker network
```

### Frontend
```bash
# Client-side needs localhost URL (not Docker network)
PUBLIC_API_BASE_URL=http://localhost:8002
```

## Account Naming Convention

**Pattern**: `Domingo {child_name}`  
**Example**: 
- Emma Johnson → "Domingo Emma Johnson"
- Lucas Johnson → "Domingo Lucas Johnson"

**Why "Domingo"**: Spanish for "allowance" - clearly identifies these as child allowance accounts in Actual Budget

## Error Handling

### Common Issues

**1. Actual Budget Not Configured**
```
Error: Could not find a file id or identifier 'My Finances'
Fix: Run setup_budget.py to create the budget
```

**2. Point Adjustment Out of Range**
```
Error: Input should be less than or equal to 1000
Fix: Family API has ±1000 point limit per adjustment
```

**3. CORS Error from Frontend**
```
Error: Failed to fetch
Fix: Ensure ALLOWED_ORIGINS includes port 3003
```

**4. Date Parsing Error**
```
Error: 'int' object has no attribute 'isoformat'
Fix: Use parse_actual_date() helper for date conversion
```

## Testing

### Manual Sync Test
```bash
# 1. Check current points
TOKEN=$(curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"mom@demo.com","password":"password123"}' | jq -r '.access_token')

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/families/me | \
  jq '.members[] | select(.role != "parent") | {name, points}'

# 2. Run sync (dry run first)
curl -s -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=true" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.output'

# 3. Run actual sync
curl -s -X POST "http://localhost:8002/api/sync/trigger?direction=both&dry_run=false" \
  -H "Authorization: Bearer $TOKEN" | jq '.status'

# 4. Verify results
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/families/me | \
  jq '.members[] | select(.role != "parent") | {name, points}'
```

### Add Test Transactions
```bash
# Add test transactions to Actual Budget
docker exec family_sync_service python3 /app/add_test_transactions.py

# Sync them to Family Task Manager
curl -X POST "http://localhost:8002/api/sync/trigger?direction=from_actual&dry_run=false" \
  -H "Authorization: Bearer $TOKEN"
```

## Security

### Parent-Only Access
```python
# backend/app/api/routes/sync.py
def get_current_parent(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "parent":
        raise HTTPException(status_code=403, detail="Only parents can trigger sync")
    return current_user
```

### No Child Access
- Children cannot trigger sync
- Children cannot see sync status
- Children cannot access Actual Budget

### Credentials Storage
- Actual Budget password in environment variables
- Family API credentials in sync service env
- No hardcoded secrets in code

## Performance Considerations

### Sync Duration
- Typical sync: 2-5 seconds
- Large transaction sets: up to 30 seconds
- Timeout: 130 seconds (2 minutes + 10s buffer)

### Rate Limiting
- No rate limiting on sync endpoints (parent-only access)
- Cron runs hourly to avoid excessive API calls
- Manual syncs can be triggered any time

### Database Impact
- Minimal - only reads points and creates adjustments
- No heavy queries or table scans
- Transactions are batched per child

## Troubleshooting

### Sync Service Not Responding
```bash
# Check container status
docker ps | grep sync-service

# Check logs
docker logs family_sync_service

# Restart service
docker-compose restart sync-service
```

### Transactions Not Syncing
```bash
# Check sync state
cat services/actual-budget/sync_state.json | jq

# Clear sync state (forces re-sync)
docker exec family_sync_service rm /app/sync_state.json

# Run sync with verbose output
docker exec family_sync_service python3 /app/sync.py --direction=both
```

### Cron Not Running
```bash
# Check cron status
docker exec family_sync_service service cron status

# Check cron log
docker exec family_sync_service tail -f /app/sync_cron.log

# Verify crontab
docker exec family_sync_service crontab -l
```

## Future Enhancements

- [ ] Sync history UI showing past sync operations
- [ ] Webhook support for real-time sync triggers
- [ ] Multi-currency support
- [ ] Configurable sync schedules per family
- [ ] Sync conflict resolution UI
- [ ] Transaction categorization in Actual Budget
- [ ] Budget vs actual spending reports
