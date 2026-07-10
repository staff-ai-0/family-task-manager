"""Dedupe the budget category catalog + unique guards.

The lazy category seed raced (two concurrent first-loads both passed the
read-then-insert guard) and duplicated the ENTIRE default tree for real
families (24 groups / 88 categories in prod). This migration:

1. Merges duplicate category groups per (family_id, name): keeps the oldest,
   moves/merges each duplicate's categories into the kept group's same-name
   category (repointing transactions, allocations [summed per month], rules,
   goals, recurring, transaction items, payee defaults), then deletes the
   duplicate rows.
2. Adds partial unique indexes so the catalog can never silently duplicate
   again — (family_id, lower(name)) on live groups, (group_id, lower(name))
   on live categories. The seed also takes an advisory lock now; the indexes
   are the belt-and-suspenders.

Revision ID: budget_catalog_dedupe
Revises: chat_moderation
"""
from alembic import op

revision = "budget_catalog_dedupe"
down_revision = "chat_moderation"
branch_labels = None
depends_on = None


DEDUPE_SQL = """
-- ── 1. Canonical group per (family_id, name) = oldest live row ────────────
CREATE TEMP TABLE _dupe_groups AS
SELECT g.id AS dupe_id, k.keep_id
FROM budget_category_groups g
JOIN (
    SELECT family_id, name,
           (array_agg(id ORDER BY created_at, id))[1] AS keep_id
    FROM budget_category_groups
    WHERE deleted_at IS NULL
    GROUP BY family_id, name
    HAVING count(*) > 1
) k ON k.family_id = g.family_id AND k.name = g.name
WHERE g.deleted_at IS NULL AND g.id <> k.keep_id;

-- ── 2. Map each duplicate group's categories to the kept group's same-name
--       category (when one exists) ─────────────────────────────────────────
CREATE TEMP TABLE _cat_map AS
SELECT dc.id AS dupe_cat_id, kc.id AS keep_cat_id
FROM _dupe_groups dg
JOIN budget_categories dc
  ON dc.group_id = dg.dupe_id AND dc.deleted_at IS NULL
JOIN budget_categories kc
  ON kc.group_id = dg.keep_id AND kc.deleted_at IS NULL
 AND lower(kc.name) = lower(dc.name);

-- ── 3. Repoint references from dupe categories to kept categories ────────
UPDATE budget_transactions t SET category_id = m.keep_cat_id
FROM _cat_map m WHERE t.category_id = m.dupe_cat_id;

UPDATE budget_transaction_items i SET category_id = m.keep_cat_id
FROM _cat_map m WHERE i.category_id = m.dupe_cat_id;

UPDATE budget_categorization_rules r SET category_id = m.keep_cat_id
FROM _cat_map m WHERE r.category_id = m.dupe_cat_id;

UPDATE budget_goals gl SET category_id = m.keep_cat_id
FROM _cat_map m WHERE gl.category_id = m.dupe_cat_id;

UPDATE budget_recurring_transactions rt SET category_id = m.keep_cat_id
FROM _cat_map m WHERE rt.category_id = m.dupe_cat_id;

UPDATE budget_payees p SET default_category_id = m.keep_cat_id
FROM _cat_map m WHERE p.default_category_id = m.dupe_cat_id;

-- Allocations: merge into the kept category's row when the month collides
-- (unique (category_id, month)), else repoint.
UPDATE budget_allocations ka
SET budgeted_amount = ka.budgeted_amount + da.budgeted_amount
FROM budget_allocations da
JOIN _cat_map m ON da.category_id = m.dupe_cat_id
WHERE ka.category_id = m.keep_cat_id AND ka.month = da.month;

DELETE FROM budget_allocations da
USING _cat_map m, budget_allocations ka
WHERE da.category_id = m.dupe_cat_id
  AND ka.category_id = m.keep_cat_id AND ka.month = da.month;

UPDATE budget_allocations da SET category_id = m.keep_cat_id
FROM _cat_map m WHERE da.category_id = m.dupe_cat_id;

-- ── 4. Mapped dupe categories are now unreferenced → delete. Unmapped ones
--       (name only in the dupe group) survive by MOVING to the kept group. ─
DELETE FROM budget_categories c USING _cat_map m WHERE c.id = m.dupe_cat_id;

UPDATE budget_categories c SET group_id = dg.keep_id
FROM _dupe_groups dg WHERE c.group_id = dg.dupe_id;

-- ── 5. Dupe groups are empty → delete ─────────────────────────────────────
DELETE FROM budget_category_groups g USING _dupe_groups dg
WHERE g.id = dg.dupe_id;

DROP TABLE _cat_map;
DROP TABLE _dupe_groups;

-- ── 6. Same-group duplicate categories (defensive; same keep-oldest rule) ─
CREATE TEMP TABLE _dupe_cats AS
SELECT c.id AS dupe_id, k.keep_id
FROM budget_categories c
JOIN (
    SELECT group_id, lower(name) AS lname,
           (array_agg(id ORDER BY created_at, id))[1] AS keep_id
    FROM budget_categories
    WHERE deleted_at IS NULL
    GROUP BY group_id, lower(name)
    HAVING count(*) > 1
) k ON k.group_id = c.group_id AND lower(c.name) = k.lname
WHERE c.deleted_at IS NULL AND c.id <> k.keep_id;

UPDATE budget_transactions t SET category_id = m.keep_id
FROM _dupe_cats m WHERE t.category_id = m.dupe_id;
UPDATE budget_transaction_items i SET category_id = m.keep_id
FROM _dupe_cats m WHERE i.category_id = m.dupe_id;
UPDATE budget_categorization_rules r SET category_id = m.keep_id
FROM _dupe_cats m WHERE r.category_id = m.dupe_id;
UPDATE budget_goals gl SET category_id = m.keep_id
FROM _dupe_cats m WHERE gl.category_id = m.dupe_id;
UPDATE budget_recurring_transactions rt SET category_id = m.keep_id
FROM _dupe_cats m WHERE rt.category_id = m.dupe_id;
UPDATE budget_payees p SET default_category_id = m.keep_id
FROM _dupe_cats m WHERE p.default_category_id = m.dupe_id;

UPDATE budget_allocations ka
SET budgeted_amount = ka.budgeted_amount + da.budgeted_amount
FROM budget_allocations da JOIN _dupe_cats m ON da.category_id = m.dupe_id
WHERE ka.category_id = m.keep_id AND ka.month = da.month;
DELETE FROM budget_allocations da
USING _dupe_cats m, budget_allocations ka
WHERE da.category_id = m.dupe_id
  AND ka.category_id = m.keep_id AND ka.month = da.month;
UPDATE budget_allocations da SET category_id = m.keep_id
FROM _dupe_cats m WHERE da.category_id = m.dupe_id;

DELETE FROM budget_categories c USING _dupe_cats m WHERE c.id = m.dupe_id;
DROP TABLE _dupe_cats;
"""


def upgrade() -> None:
    op.execute(DEDUPE_SQL)
    op.create_index(
        "ux_budget_groups_family_name",
        "budget_category_groups",
        ["family_id", "name"],
        unique=True,
        postgresql_where="deleted_at IS NULL",
    )
    op.create_index(
        "ux_budget_categories_group_name",
        "budget_categories",
        ["group_id", "name"],
        unique=True,
        postgresql_where="deleted_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "ux_budget_categories_group_name", table_name="budget_categories"
    )
    op.drop_index(
        "ux_budget_groups_family_name", table_name="budget_category_groups"
    )
    # The merged duplicates are not restorable.
