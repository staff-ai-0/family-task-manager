"""budget_transactions FK columns must be indexed (audit M16).

category_id / account_id / payee_id back every activity, category, and payee
query; without indexes those are sequential scans.
"""
from app.models.budget import BudgetTransaction


def _indexed_columns(model) -> set:
    cols = set()
    for ix in model.__table__.indexes:
        for col in ix.columns:
            cols.add(col.name)
    for col in model.__table__.columns:
        if col.index:
            cols.add(col.name)
    return cols


def test_budget_transaction_fk_columns_indexed():
    indexed = _indexed_columns(BudgetTransaction)
    for col in ("account_id", "payee_id", "category_id"):
        assert col in indexed, f"budget_transactions.{col} is not indexed"
