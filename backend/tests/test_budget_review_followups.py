"""Regression tests for PR #4 follow-up fixes.

Covers code-review issues B2 / H1 / H3 plus the bulk/merge/reassign and
report-batching paths that previously had no service-level tests.
"""

import pytest
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction
from app.services.budget.account_service import AccountService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.payee_service import PayeeService
from app.services.budget.transaction_service import TransactionService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.report_service import ReportService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.schemas.budget import (
    AccountCreate,
    CategoryGroupCreate,
    CategoryCreate,
    CategorizationRuleCreate,
    PayeeCreate,
    TransactionCreate,
    AllocationCreate,
)
from app.core.exceptions import NotFoundException


# ---------- Helpers ----------

async def _make_account(db, family_id, name="Checking"):
    return await AccountService.create(
        db, family_id, AccountCreate(name=name, type="checking")
    )


async def _make_category(db, family_id, group_name="Food", cat_name="Groceries"):
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name=group_name, is_income=False)
    )
    cat = await CategoryService.create(
        db, family_id, CategoryCreate(name=cat_name, group_id=group.id)
    )
    return group, cat


# ---------- bulk_delete_transactions ----------

@pytest.mark.asyncio
async def test_bulk_delete_removes_only_listed_rows(db: AsyncSession, family_id):
    account = await _make_account(db, family_id)
    keep = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-100),
    )
    a = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-200),
    )
    b = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-300),
    )

    deleted = await TransactionService.bulk_delete_transactions(
        db, family_id, [a.id, b.id]
    )
    assert deleted == 2

    remaining = await TransactionService.list_by_family(db, family_id)
    assert {t.id for t in remaining} == {keep.id}


# ---------- bulk_update_transactions: family-scoped FK validation ----------

@pytest.mark.asyncio
async def test_bulk_update_applies_valid_family_category(db: AsyncSession, family_id):
    account = await _make_account(db, family_id)
    _, cat = await _make_category(db, family_id)
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-100),
    )

    count = await TransactionService.bulk_update_transactions(
        db, family_id, [txn.id], {"category_id": cat.id, "cleared": True}
    )
    assert count == 1
    await db.refresh(txn)
    assert txn.category_id == cat.id
    assert txn.cleared is True


# ---------- finish_reconciliation: balance match + adjustment branches ----------

@pytest.mark.asyncio
async def test_finish_reconciliation_matching_balance_no_adjustment(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-5000),
    )

    result = await TransactionService.finish_reconciliation(
        db, family_id,
        account_id=account.id,
        statement_balance=-5000,
        transaction_ids=[txn.id],
    )
    assert result["reconciled_count"] == 1
    assert result["adjustment_amount"] == 0
    assert result["adjustment_transaction_id"] is None
    await db.refresh(txn)
    assert txn.cleared is True
    assert txn.reconciled is True


@pytest.mark.asyncio
async def test_finish_reconciliation_mismatch_creates_adjustment(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-5000),
    )

    result = await TransactionService.finish_reconciliation(
        db, family_id,
        account_id=account.id,
        statement_balance=-5500,
        transaction_ids=[txn.id],
    )
    assert result["reconciled_count"] == 1
    assert result["adjustment_amount"] == -500
    assert result["adjustment_transaction_id"] is not None

    adj = await TransactionService.get_by_id(
        db, result["adjustment_transaction_id"], family_id
    )
    assert adj.amount == -500
    assert adj.cleared is True
    assert adj.reconciled is True


# ---------- merge_payees ----------

@pytest.mark.asyncio
async def test_merge_payees_reassigns_transactions_and_deletes_source(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    src = await PayeeService.create(db, family_id, PayeeCreate(name="OXXO Norte"))
    tgt = await PayeeService.create(db, family_id, PayeeCreate(name="OXXO"))

    t1 = await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account.id, date=date(2026, 5, 1), amount=-100,
            payee_id=src.id,
        ),
    )
    t2 = await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account.id, date=date(2026, 5, 2), amount=-200,
            payee_id=src.id,
        ),
    )

    result = await PayeeService.merge_payees(db, family_id, src.id, tgt.id)
    assert result["merged_count"] == 2
    assert result["source_name"] == "OXXO Norte"
    assert result["target_name"] == "OXXO"

    await db.refresh(t1)
    await db.refresh(t2)
    assert t1.payee_id == tgt.id
    assert t2.payee_id == tgt.id

    with pytest.raises(NotFoundException):
        await PayeeService.get_by_id(db, src.id, family_id)


# ---------- delete_with_reassign: soft-delete + reassign ----------

@pytest.mark.asyncio
async def test_delete_with_reassign_soft_deletes_and_reassigns(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    _, src_cat = await _make_category(db, family_id, cat_name="OldCat")
    _, dest_cat = await _make_category(db, family_id, group_name="Food2", cat_name="NewCat")

    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account.id, date=date(2026, 5, 1), amount=-100,
            category_id=src_cat.id,
        ),
    )

    result = await CategoryService.delete_with_reassign(
        db, src_cat.id, family_id, reassign_to_id=dest_cat.id
    )
    assert result["deleted_name"] == "OldCat"
    assert result["reassigned_count"] == 1

    await db.refresh(txn)
    assert txn.category_id == dest_cat.id

    # Soft-deleted: get_by_id (which filters deleted_at) raises NotFound
    with pytest.raises(NotFoundException):
        await CategoryService.get_by_id(db, src_cat.id, family_id)


@pytest.mark.asyncio
async def test_delete_with_reassign_rejects_self_reassignment(
    db: AsyncSession, family_id
):
    """Reassigning a category onto itself would orphan its txns when the row
    gets soft-deleted. Service must refuse with ValidationError before
    mutating any state.
    """
    from app.core.exceptions import ValidationError

    account = await _make_account(db, family_id)
    _, cat = await _make_category(db, family_id, cat_name="LoneCat")
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account.id, date=date(2026, 5, 1), amount=-100,
            category_id=cat.id,
        ),
    )

    with pytest.raises(ValidationError):
        await CategoryService.delete_with_reassign(
            db, cat.id, family_id, reassign_to_id=cat.id
        )

    # Category and txn must be untouched
    await db.refresh(txn)
    assert txn.category_id == cat.id
    fetched = await CategoryService.get_by_id(db, cat.id, family_id)
    assert fetched.deleted_at is None


# ---------- Currency safety ----------

@pytest.mark.asyncio
async def test_account_create_rejects_mismatched_currency(
    db: AsyncSession, family_id
):
    """Family currency is implicit and singular. A second account with a
    different currency must be refused — reports sum amounts blindly across
    accounts and have no FX conversion.
    """
    from app.core.exceptions import ValidationError

    await AccountService.create(
        db, family_id, AccountCreate(name="MXN Checking", type="checking")
    )

    with pytest.raises(ValidationError):
        await AccountService.create(
            db, family_id,
            AccountCreate(name="USD Savings", type="savings", currency="USD"),
        )


@pytest.mark.asyncio
async def test_account_update_rejects_currency_change(
    db: AsyncSession, family_id
):
    """Once set, currency cannot be changed if other accounts exist on the
    family with the original currency."""
    from app.core.exceptions import ValidationError
    from app.schemas.budget import AccountUpdate

    a = await AccountService.create(
        db, family_id, AccountCreate(name="A", type="checking")
    )
    await AccountService.create(
        db, family_id, AccountCreate(name="B", type="checking")
    )

    with pytest.raises(ValidationError):
        await AccountService.update(
            db, a.id, family_id, AccountUpdate(currency="USD")
        )


# ---------- SQL-side filtering for paginated list endpoints ----------

@pytest.mark.asyncio
async def test_list_for_family_drops_closed_in_sql_not_python(
    db: AsyncSession, family_id
):
    """list_for_family must filter closed accounts in SQL so the requested
    limit reflects the count of returned (open) rows, not pre-filter rows.

    Layout: 3 closed + 2 open. limit=2, include_closed=False must return
    exactly 2 open accounts. Pre-fix python-filter would return 0 (the first
    2 in sort order are closed and stripped after pagination).
    """
    closed_a = await AccountService.create(
        db, family_id, AccountCreate(name="A_closed", type="checking", sort_order=1)
    )
    closed_b = await AccountService.create(
        db, family_id, AccountCreate(name="B_closed", type="checking", sort_order=2)
    )
    closed_c = await AccountService.create(
        db, family_id, AccountCreate(name="C_closed", type="checking", sort_order=3)
    )
    open_d = await AccountService.create(
        db, family_id, AccountCreate(name="D_open", type="checking", sort_order=4)
    )
    open_e = await AccountService.create(
        db, family_id, AccountCreate(name="E_open", type="checking", sort_order=5)
    )

    from app.schemas.budget import AccountUpdate
    for a in (closed_a, closed_b, closed_c):
        await AccountService.update(db, a.id, family_id, AccountUpdate(closed=True))

    rows = await AccountService.list_for_family(
        db, family_id, include_closed=False, limit=2, offset=0
    )
    assert len(rows) == 2
    assert {r.id for r in rows} == {open_d.id, open_e.id}


# ---------- AllocationService.copy_from_month ----------

@pytest.mark.asyncio
async def test_copy_from_month_copies_nonzero_only(db: AsyncSession, family_id):
    _, cat_a = await _make_category(db, family_id, cat_name="A")
    _, cat_b = await _make_category(db, family_id, group_name="G2", cat_name="B")

    src_month = date(2026, 4, 1)
    tgt_month = date(2026, 5, 1)

    await AllocationService.create(
        db, family_id,
        AllocationCreate(category_id=cat_a.id, month=src_month, budgeted_amount=15000),
    )
    await AllocationService.create(
        db, family_id,
        AllocationCreate(category_id=cat_b.id, month=src_month, budgeted_amount=0),
    )

    result = await AllocationService.copy_from_month(
        db, family_id, src_month, tgt_month
    )
    assert result["copied"] == 1
    assert result["skipped"] == 1


# ---------- ReportService: shape sanity for batched paths ----------

@pytest.mark.asyncio
async def test_get_budget_vs_actual_returns_expected_shape(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    _, cat = await _make_category(db, family_id)

    month = date(2026, 5, 1)
    await AllocationService.create(
        db, family_id,
        AllocationCreate(category_id=cat.id, month=month, budgeted_amount=20000),
    )
    await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account.id, date=month, amount=-7000, category_id=cat.id,
        ),
    )

    report = await ReportService.get_budget_vs_actual(db, family_id, month)
    assert report["month"] == month.isoformat()
    assert report["totals"]["budgeted"] == 20000
    assert report["totals"]["actual"] == 7000
    assert report["totals"]["variance"] == 13000
    assert len(report["groups"]) == 1
    cats = report["groups"][0]["categories"]
    assert cats[0]["budgeted"] == 20000
    assert cats[0]["actual"] == 7000
    assert cats[0]["pct_used"] == 35.0


@pytest.mark.asyncio
async def test_get_net_worth_history_series_length_matches_months(
    db: AsyncSession, family_id
):
    account = await _make_account(db, family_id)
    await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 4, 15), amount=10000),
    )

    result = await ReportService.get_net_worth_history(db, family_id, months=3)
    assert len(result["series"]) == 3
    assert result["months"] == 3
    assert result["current_net_worth"] == result["series"][-1]["net_worth"]


@pytest.mark.asyncio
async def test_get_net_worth_history_includes_closed_accounts(
    db: AsyncSession, family_id
):
    """Closing an account must not retroactively erase its historical
    contribution — net worth at month T should be the same regardless of
    whether the account is closed today.
    """
    from app.schemas.budget import AccountUpdate

    account = await _make_account(db, family_id, name="ClosedSavings")
    await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 4, 15), amount=50_000),
    )

    before = await ReportService.get_net_worth_history(db, family_id, months=3)
    before_total = before["current_net_worth"]
    assert before_total != 0, "precondition: account should contribute"

    await AccountService.update(
        db, account.id, family_id, AccountUpdate(closed=True)
    )

    after = await ReportService.get_net_worth_history(db, family_id, months=3)
    assert after["current_net_worth"] == before_total
    assert after["series"] == before["series"]


# ---------- Route ordering: /search must not be shadowed by /{transaction_id} ----------

@pytest.mark.asyncio
async def test_search_endpoint_is_not_shadowed_by_transaction_id_route(
    client, auth_headers
):
    """GET /api/budget/transactions/search must resolve to the search handler,
    not be parsed as transaction_id="search" by the /{transaction_id} route.

    Regression: prior to the fix, /search was declared after /{transaction_id},
    so FastAPI matched the literal "search" against the UUID-typed path param
    and returned 422.
    """
    response = await client.get(
        "/api/budget/transactions/search",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------- apply_all_rules pagination correctness ----------

@pytest.mark.asyncio
async def test_apply_all_rules_processes_all_rows_across_batches(
    db: AsyncSession, family_id, monkeypatch
):
    """apply_all_rules must not skip rows when matched rows leave the result set
    between batches.

    Regression: with offset += len(rows), each applied row caused an offset
    drift that left uncategorized rows behind the scan window unprocessed.
    Force a tiny batch size so multiple iterations are required.
    """
    monkeypatch.setattr(CategorizationRuleService, "APPLY_ALL_BATCH_SIZE", 2)

    account = await _make_account(db, family_id)
    _, cat = await _make_category(db, family_id)

    match_payee = await PayeeService.create(
        db, family_id, PayeeCreate(name="MatchPayee")
    )
    nomatch_payee = await PayeeService.create(
        db, family_id, PayeeCreate(name="NoMatchPayee")
    )

    # 3 matching, 2 non-matching, all uncategorized
    matching_ids = []
    for i in range(3):
        t = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id, date=date(2026, 5, 1), amount=-(100 + i),
                payee_id=match_payee.id,
            ),
        )
        matching_ids.append(t.id)

    nomatch_ids = []
    for i in range(2):
        t = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id, date=date(2026, 5, 1), amount=-(500 + i),
                payee_id=nomatch_payee.id,
            ),
        )
        nomatch_ids.append(t.id)

    await CategorizationRuleService.create(
        db, family_id,
        CategorizationRuleCreate(
            category_id=cat.id,
            rule_type="exact",
            match_field="payee",
            pattern="MatchPayee",
            enabled=True,
            priority=0,
        ),
    )

    result = await CategorizationRuleService.apply_all_rules(db, family_id)

    assert result["applied"] == 3, (
        f"Expected all 3 matching txns categorized, got {result}"
    )
    assert result["skipped"] == 2
    assert result["truncated"] is False

    for tid in matching_ids:
        txn = await TransactionService.get_by_id(db, tid, family_id)
        assert txn.category_id == cat.id

    for tid in nomatch_ids:
        txn = await TransactionService.get_by_id(db, tid, family_id)
        assert txn.category_id is None


# ---------- require_feature(units=N) gating ----------

@pytest.mark.asyncio
async def test_create_split_blocked_when_units_would_exceed_limit(
    client, auth_headers, db_session, test_family
):
    """A split request whose len(splits) would push usage past the plan limit
    must be rejected with 403, not silently accepted then over-counted.

    Free plan: max_budget_transactions_per_month = 30. Pre-seed usage=28,
    attempt 5-leg split → 28+5 > 30 → 403.
    """
    from app.models.subscription import SubscriptionPlan, UsageTracking
    from app.models.budget import BudgetAccount, BudgetCategoryGroup, BudgetCategory
    from app.core.premium import DEFAULT_FREE_LIMITS

    # Seed free plan + max-out usage near the cap
    plan = SubscriptionPlan(
        name="free", display_name="Free", display_name_es="Gratis",
        price_monthly_cents=0, price_annual_cents=0,
        limits=dict(DEFAULT_FREE_LIMITS), sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()

    account = BudgetAccount(
        family_id=test_family.id, name="Checking", type="checking",
        starting_balance=0,
    )
    group = BudgetCategoryGroup(family_id=test_family.id, name="Food")
    db_session.add_all([account, group])
    await db_session.commit()
    await db_session.refresh(account)
    await db_session.refresh(group)
    cat = BudgetCategory(
        family_id=test_family.id, group_id=group.id, name="Groceries",
    )
    db_session.add(cat)

    usage = UsageTracking(
        family_id=test_family.id, feature="budget_transaction",
        period_start=date.today().replace(day=1), count=28,
    )
    db_session.add(usage)
    await db_session.commit()
    await db_session.refresh(cat)

    body = {
        "account_id": str(account.id),
        "date": date.today().isoformat(),
        "splits": [
            {"amount": -100, "category_id": str(cat.id)} for _ in range(5)
        ],
    }
    response = await client.post(
        "/api/budget/transactions/split", headers=auth_headers, json=body,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["error"] == "upgrade_required"

    # 2-leg split fits (28 + 2 == 30) and must succeed
    body["splits"] = body["splits"][:2]
    response = await client.post(
        "/api/budget/transactions/split", headers=auth_headers, json=body,
    )
    assert response.status_code == 201, response.text


# ---------- UsageService.increment(amount=N) accumulation ----------

@pytest.mark.asyncio
async def test_usage_service_increment_amount_accumulates(
    db: AsyncSession, family_id
):
    """increment(amount=N) must add N to the counter, not reset to 1."""
    from app.services.usage_service import UsageService

    count = await UsageService.increment(db, family_id, "budget_transaction", amount=3)
    assert count == 3

    count = await UsageService.increment(db, family_id, "budget_transaction", amount=3)
    assert count == 6

    count = await UsageService.increment(db, family_id, "budget_transaction")
    assert count == 7


# ---------- CategoryService.list_for_family hidden filter ----------

@pytest.mark.asyncio
async def test_category_list_for_family_drops_hidden_in_sql(
    db: AsyncSession, family_id
):
    """Mirror of the closed-accounts test: hidden categories must be filtered
    in SQL so pagination is stable (not python post-filter after limit/offset).
    """
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Mixed", is_income=False)
    )

    hidden_ids = []
    for i, name in enumerate(["A_hidden", "B_hidden", "C_hidden"]):
        c = await CategoryService.create(
            db, family_id,
            CategoryCreate(name=name, group_id=group.id, sort_order=i),
        )
        hidden_ids.append(c.id)

    visible_d = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="D_visible", group_id=group.id, sort_order=4),
    )
    visible_e = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="E_visible", group_id=group.id, sort_order=5),
    )

    from app.schemas.budget import CategoryUpdate
    for cid in hidden_ids:
        await CategoryService.update(
            db, cid, family_id, CategoryUpdate(hidden=True)
        )

    rows = await CategoryService.list_for_family(
        db, family_id, include_hidden=False, limit=2, offset=0
    )
    assert len(rows) == 2
    assert {r.id for r in rows} == {visible_d.id, visible_e.id}


# ---------- bulk_update_transactions partial-mutation safety ----------

@pytest.mark.asyncio
async def test_bulk_update_does_not_partially_mutate_on_validation_failure(
    db: AsyncSession, family_id
):
    """If FK validation raises (cross-family category), bulk_update must not
    have applied any of the OTHER whitelisted fields (cleared/reconciled) to
    matching rows. Locks the two-phase ordering invariant: validate first,
    mutate second.
    """
    from app.models.family import Family

    account = await _make_account(db, family_id)
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-100),
    )
    assert txn.cleared is False

    other_family = Family(name="Other Family")
    db.add(other_family)
    await db.commit()
    await db.refresh(other_family)
    other_group = await CategoryGroupService.create(
        db, other_family.id, CategoryGroupCreate(name="Other", is_income=False)
    )
    other_cat = await CategoryService.create(
        db, other_family.id,
        CategoryCreate(name="Foreign", group_id=other_group.id),
    )

    with pytest.raises(NotFoundException):
        await TransactionService.bulk_update_transactions(
            db, family_id, [txn.id],
            {"cleared": True, "category_id": other_cat.id},
        )

    await db.refresh(txn)
    assert txn.cleared is False, "cleared was applied despite FK validation failure"
    assert txn.category_id is None


# ---------- Currency change permitted on the only account in the family ----------

@pytest.mark.asyncio
async def test_account_update_allows_currency_change_when_sole_account(
    db: AsyncSession, family_id
):
    """A family with a single account must be able to switch its currency.
    Pre-fix the lookup hit the same row being updated and refused the change.
    """
    from app.schemas.budget import AccountUpdate

    a = await AccountService.create(
        db, family_id, AccountCreate(name="OnlyAccount", type="checking")
    )
    assert a.currency == "MXN"

    updated = await AccountService.update(
        db, a.id, family_id, AccountUpdate(currency="USD")
    )
    assert updated.currency == "USD"
