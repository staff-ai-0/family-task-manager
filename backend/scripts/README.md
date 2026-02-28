# Backend Scripts

## Migration Scripts

### migrate_actual_to_postgres.py

Migrates data from Actual Budget SQLite database to PostgreSQL budget tables.

**Prerequisites:**
- PostgreSQL database with budget schema applied (alembic migration `budget_phase1`)
- Access to Actual Budget SQLite file
- Family ID to migrate data for

**Usage:**

```bash
# Dry run (preview what will be migrated)
python migrate_actual_to_postgres.py \
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
    --actual-file /path/to/actual-budget.sqlite \
    --dry-run

# Actual migration
python migrate_actual_to_postgres.py \
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
    --actual-file /path/to/actual-budget.sqlite
```

**On Production Server:**

```bash
# Copy Actual Budget file from container
docker cp family_prod_actual_budget:/data/server-files/53884ee5-edfe-493c-9430-a50d1de7ec21.sqlite ./actual_backup.sqlite

# Run migration inside backend container
docker exec -it family_prod_backend python /app/scripts/migrate_actual_to_postgres.py \
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
    --actual-file /app/scripts/actual_backup.sqlite \
    --dry-run

# If dry run looks good, run actual migration
docker exec -it family_prod_backend python /app/scripts/migrate_actual_to_postgres.py \
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
    --actual-file /app/scripts/actual_backup.sqlite
```

**What Gets Migrated:**

1. **Category Groups** - Budget category groups (Mandado, Servicios, etc.)
2. **Categories** - Individual categories within groups
3. **Accounts** - Bank accounts, credit cards, etc.
4. **Payees** - People/companies you pay
5. **Transactions** - All transaction history
6. **Budget Allocations** - Monthly budget amounts (if available)

**Important Notes:**

- Migration is idempotent - can be run multiple times safely
- Existing data is skipped (based on name matching)
- Transactions use `imported_id` field for deduplication
- Reconciled status is NOT preserved (all transactions start unreconciled)
- Split transactions are preserved via `parent_id`

**Verification:**

After migration, verify data:

```sql
-- Check counts
SELECT 'category_groups' as table_name, COUNT(*) FROM budget_category_groups WHERE family_id = 'YOUR_FAMILY_ID'
UNION ALL
SELECT 'categories', COUNT(*) FROM budget_categories WHERE family_id = 'YOUR_FAMILY_ID'
UNION ALL
SELECT 'accounts', COUNT(*) FROM budget_accounts WHERE family_id = 'YOUR_FAMILY_ID'
UNION ALL
SELECT 'payees', COUNT(*) FROM budget_payees WHERE family_id = 'YOUR_FAMILY_ID'
UNION ALL
SELECT 'transactions', COUNT(*) FROM budget_transactions WHERE family_id = 'YOUR_FAMILY_ID';

-- Check account balances
SELECT 
    a.name,
    SUM(t.amount) / 100.0 as balance_dollars
FROM budget_accounts a
LEFT JOIN budget_transactions t ON t.account_id = a.id
WHERE a.family_id = 'YOUR_FAMILY_ID'
GROUP BY a.id, a.name
ORDER BY a.name;
```
