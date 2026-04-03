"""
Tests for Wave 3 Budget Gap Closure features:
- Feature 7: OFX/QIF/CAMT Import
- Feature 8: Budget Templates & Auto-Fill
- Feature 9: Budget Export
- Feature 10: Custom Reports
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetGoal,
    BudgetPayee,
    BudgetTransaction,
    BudgetCustomReport,
)
from app.services.budget.allocation_service import AllocationService
from app.services.budget.export_service import ExportService
from app.services.budget.custom_report_service import CustomReportService
from app.services.budget.file_import_service import (
    detect_format,
    parse_ofx,
    parse_qif,
    parse_camt,
    import_file_transactions,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def budget_group(db_session: AsyncSession, test_family):
    group = BudgetCategoryGroup(
        family_id=test_family.id,
        name="Wave3 Group",
        sort_order=0,
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest_asyncio.fixture
async def budget_category(db_session: AsyncSession, test_family, budget_group):
    cat = BudgetCategory(
        family_id=test_family.id,
        group_id=budget_group.id,
        name="Groceries",
        sort_order=0,
        goal_amount=50000,  # $500 goal
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


@pytest_asyncio.fixture
async def budget_category_2(db_session: AsyncSession, test_family, budget_group):
    cat = BudgetCategory(
        family_id=test_family.id,
        group_id=budget_group.id,
        name="Transport",
        sort_order=1,
        goal_amount=20000,  # $200 goal
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


@pytest_asyncio.fixture
async def budget_account(db_session: AsyncSession, test_family):
    acct = BudgetAccount(
        family_id=test_family.id,
        name="Checking",
        type="checking",
        offbudget=False,
    )
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)
    return acct


@pytest_asyncio.fixture
async def budget_payee(db_session: AsyncSession, test_family):
    payee = BudgetPayee(
        family_id=test_family.id,
        name="Walmart",
    )
    db_session.add(payee)
    await db_session.commit()
    await db_session.refresh(payee)
    return payee


# =============================================================================
# FEATURE 7: FILE IMPORT TESTS
# =============================================================================

class TestFileFormatDetection:
    """Test format detection logic."""

    def test_detect_ofx_by_extension(self):
        assert detect_format("statement.ofx", b"") == "ofx"

    def test_detect_qfx_by_extension(self):
        assert detect_format("statement.qfx", b"") == "ofx"

    def test_detect_qif_by_extension(self):
        assert detect_format("export.qif", b"") == "qif"

    def test_detect_camt_by_extension(self):
        assert detect_format("bank.xml", b"") == "camt"

    def test_detect_ofx_by_content(self):
        content = b"OFXHEADER:100\nDATA:OFXSGML\n<OFX>"
        assert detect_format("unknown.dat", content) == "ofx"

    def test_detect_qif_by_content(self):
        content = b"!Type:Bank\nD01/15/2026\nT-50.00\n^"
        assert detect_format("unknown.dat", content) == "qif"

    def test_detect_csv_fallback(self):
        content = b"date,amount,payee\n2026-01-01,-50,Store"
        assert detect_format("data.dat", content) == "csv"


class TestOFXParser:
    """Test OFX file parsing."""

    def test_parse_basic_ofx(self):
        ofx_data = b"""OFXHEADER:100
DATA:OFXSGML
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKTRANLIST>
<STMTTRN>
<DTPOSTED>20260115
<TRNAMT>-42.50
<NAME>GROCERY STORE
<MEMO>Weekly groceries
<FITID>TXN001
</STMTTRN>
<STMTTRN>
<DTPOSTED>20260116
<TRNAMT>1500.00
<NAME>PAYROLL DEPOSIT
<FITID>TXN002
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>"""
        txns = parse_ofx(ofx_data)
        assert len(txns) == 2

        assert txns[0].date == date(2026, 1, 15)
        assert txns[0].amount == -4250
        assert txns[0].payee_name == "GROCERY STORE"
        assert txns[0].imported_id == "TXN001"

        assert txns[1].amount == 150000
        assert txns[1].payee_name == "PAYROLL DEPOSIT"

    def test_parse_ofx_with_timezone(self):
        ofx_data = b"""<OFX>
<STMTTRN>
<DTPOSTED>20260120120000[0:GMT]
<TRNAMT>-10.00
<NAME>COFFEE
<FITID>TXN003
</STMTTRN>
</OFX>"""
        txns = parse_ofx(ofx_data)
        assert len(txns) == 1
        assert txns[0].date == date(2026, 1, 20)
        assert txns[0].amount == -1000


class TestQIFParser:
    """Test QIF file parsing."""

    def test_parse_basic_qif(self):
        qif_data = b"""!Type:Bank
D01/15/2026
T-42.50
PGrocery Store
MWeekly groceries
^
D01/16/2026
T1500.00
PPayroll
^"""
        txns = parse_qif(qif_data)
        assert len(txns) == 2

        assert txns[0].date == date(2026, 1, 15)
        assert txns[0].amount == -4250
        assert txns[0].payee_name == "Grocery Store"
        assert txns[0].notes == "Weekly groceries"

        assert txns[1].amount == 150000
        assert txns[1].payee_name == "Payroll"

    def test_parse_qif_two_digit_year(self):
        qif_data = b"""!Type:Bank
D3/5'26
T-10.00
PCoffee
^"""
        txns = parse_qif(qif_data)
        assert len(txns) == 1
        assert txns[0].date == date(2026, 3, 5)


class TestCAMTParser:
    """Test CAMT.053 XML parsing."""

    def test_parse_basic_camt(self):
        camt_data = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Ntry>
        <Amt Ccy="USD">42.50</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <BookgDt><Dt>2026-01-15</Dt></BookgDt>
        <NtryDtls><TxDtls><RmtInf><Ustrd>Grocery Store</Ustrd></RmtInf></TxDtls></NtryDtls>
      </Ntry>
      <Ntry>
        <Amt Ccy="USD">1500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-01-16</Dt></BookgDt>
        <NtryDtls><TxDtls><RmtInf><Ustrd>Salary</Ustrd></RmtInf></TxDtls></NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        txns = parse_camt(camt_data)
        assert len(txns) == 2

        assert txns[0].date == date(2026, 1, 15)
        assert txns[0].amount == -4250  # DBIT = negative
        assert txns[0].payee_name == "Grocery Store"

        assert txns[1].amount == 150000  # CRDT = positive
        assert txns[1].payee_name == "Salary"


class TestFileImport:
    """Test full import flow with database."""

    @pytest.mark.asyncio
    async def test_import_ofx_creates_transactions(
        self, db_session, test_family, budget_account
    ):
        ofx_data = b"""<OFX>
<STMTTRN>
<DTPOSTED>20260201
<TRNAMT>-25.00
<NAME>Test Store
<FITID>IMPORT001
</STMTTRN>
</OFX>"""
        result = await import_file_transactions(
            db=db_session,
            family_id=test_family.id,
            account_id=budget_account.id,
            filename="test.ofx",
            file_bytes=ofx_data,
        )
        assert result["imported"] == 1
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_import_deduplicates_by_imported_id(
        self, db_session, test_family, budget_account
    ):
        ofx_data = b"""<OFX>
<STMTTRN>
<DTPOSTED>20260201
<TRNAMT>-25.00
<NAME>Test Store
<FITID>DEDUP001
</STMTTRN>
</OFX>"""
        # Import once
        await import_file_transactions(
            db=db_session,
            family_id=test_family.id,
            account_id=budget_account.id,
            filename="test.ofx",
            file_bytes=ofx_data,
        )
        # Import again - should skip
        result = await import_file_transactions(
            db=db_session,
            family_id=test_family.id,
            account_id=budget_account.id,
            filename="test.ofx",
            file_bytes=ofx_data,
        )
        assert result["skipped"] == 1
        assert result["imported"] == 0


# =============================================================================
# FEATURE 8: AUTO-FILL TESTS
# =============================================================================

class TestAutoFill:
    """Test budget auto-fill strategies."""

    @pytest.mark.asyncio
    async def test_copy_previous_month(
        self, db_session, test_family, budget_category
    ):
        prev_month = date(2026, 2, 1)
        target_month = date(2026, 3, 1)

        # Create allocation for previous month
        alloc = BudgetAllocation(
            family_id=test_family.id,
            category_id=budget_category.id,
            month=prev_month,
            budgeted_amount=50000,
        )
        db_session.add(alloc)
        await db_session.commit()

        result = await AllocationService.auto_fill(
            db_session,
            family_id=test_family.id,
            target_month=target_month,
            strategy="copy_previous",
        )
        assert result["filled_count"] == 1
        assert result["skipped_count"] == 0

    @pytest.mark.asyncio
    async def test_copy_previous_skips_existing(
        self, db_session, test_family, budget_category
    ):
        prev_month = date(2026, 4, 1)
        target_month = date(2026, 5, 1)

        # Create allocations for both months
        for month in [prev_month, target_month]:
            alloc = BudgetAllocation(
                family_id=test_family.id,
                category_id=budget_category.id,
                month=month,
                budgeted_amount=50000,
            )
            db_session.add(alloc)
        await db_session.commit()

        result = await AllocationService.auto_fill(
            db_session,
            family_id=test_family.id,
            target_month=target_month,
            strategy="copy_previous",
            overwrite_existing=False,
        )
        assert result["skipped_count"] == 1

    @pytest.mark.asyncio
    async def test_copy_previous_overwrites_when_requested(
        self, db_session, test_family, budget_category
    ):
        prev_month = date(2026, 6, 1)
        target_month = date(2026, 7, 1)

        # Prev month has $500
        alloc_prev = BudgetAllocation(
            family_id=test_family.id,
            category_id=budget_category.id,
            month=prev_month,
            budgeted_amount=50000,
        )
        # Target has $100
        alloc_target = BudgetAllocation(
            family_id=test_family.id,
            category_id=budget_category.id,
            month=target_month,
            budgeted_amount=10000,
        )
        db_session.add_all([alloc_prev, alloc_target])
        await db_session.commit()

        result = await AllocationService.auto_fill(
            db_session,
            family_id=test_family.id,
            target_month=target_month,
            strategy="copy_previous",
            overwrite_existing=True,
        )
        assert result["filled_count"] == 1

    @pytest.mark.asyncio
    async def test_fill_from_goals(
        self, db_session, test_family, budget_category, budget_category_2
    ):
        target_month = date(2026, 8, 1)

        result = await AllocationService.auto_fill(
            db_session,
            family_id=test_family.id,
            target_month=target_month,
            strategy="from_goals",
        )
        # Both categories have goal_amount > 0
        assert result["filled_count"] == 2

    @pytest.mark.asyncio
    async def test_average_strategy(
        self, db_session, test_family, budget_account, budget_category
    ):
        target_month = date(2026, 9, 1)

        # Create transactions for 3 prior months
        for i in range(1, 4):
            month_start = target_month - relativedelta(months=i)
            txn = BudgetTransaction(
                family_id=test_family.id,
                account_id=budget_account.id,
                category_id=budget_category.id,
                date=month_start + timedelta(days=5),
                amount=-30000,  # -$300 each month
                cleared=False,
                reconciled=False,
            )
            db_session.add(txn)
        await db_session.commit()

        result = await AllocationService.auto_fill(
            db_session,
            family_id=test_family.id,
            target_month=target_month,
            strategy="average_3",
        )
        assert result["filled_count"] == 1


# =============================================================================
# FEATURE 9: EXPORT/IMPORT TESTS
# =============================================================================

class TestBudgetExport:
    """Test budget export and import."""

    @pytest.mark.asyncio
    async def test_export_creates_valid_zip(
        self, db_session, test_family, budget_account, budget_category
    ):
        import zipfile
        import io
        import json

        zip_bytes = await ExportService.export_budget(db_session, test_family.id)
        assert len(zip_bytes) > 0

        # Verify ZIP structure
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
            assert "budget_data.json" in names
            assert "metadata.json" in names

            # Verify data structure
            data = json.loads(zf.read("budget_data.json"))
            assert "accounts" in data
            assert "categories" in data
            assert "transactions" in data

            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["family_id"] == str(test_family.id)

    @pytest.mark.asyncio
    async def test_export_includes_all_entities(
        self, db_session, test_family, budget_account, budget_payee, budget_category
    ):
        import zipfile
        import io
        import json

        # Create a transaction
        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            category_id=budget_category.id,
            payee_id=budget_payee.id,
            date=date(2026, 1, 15),
            amount=-5000,
            cleared=True,
            reconciled=False,
        )
        db_session.add(txn)
        await db_session.commit()

        zip_bytes = await ExportService.export_budget(db_session, test_family.id)
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            data = json.loads(zf.read("budget_data.json"))
            assert len(data["accounts"]) >= 1
            assert len(data["payees"]) >= 1
            assert len(data["transactions"]) >= 1


# =============================================================================
# FEATURE 10: CUSTOM REPORTS TESTS
# =============================================================================

class TestCustomReports:
    """Test custom report CRUD and data generation."""

    @pytest.mark.asyncio
    async def test_create_custom_report(
        self, db_session, test_family, test_parent_user
    ):
        from app.schemas.budget import CustomReportCreate

        data = CustomReportCreate(
            name="Monthly Spending",
            config={
                "group_by": "category",
                "date_range": "last_30",
            },
        )
        report = await CustomReportService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            data=data,
        )
        assert report.name == "Monthly Spending"
        assert report.config["group_by"] == "category"
        assert report.family_id == test_family.id

    @pytest.mark.asyncio
    async def test_update_custom_report(
        self, db_session, test_family, test_parent_user
    ):
        from app.schemas.budget import CustomReportCreate, CustomReportUpdate

        # Create
        data = CustomReportCreate(
            name="Old Name",
            config={"group_by": "category"},
        )
        report = await CustomReportService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            data=data,
        )

        # Update
        update = CustomReportUpdate(name="New Name")
        updated = await CustomReportService.update(
            db_session,
            report_id=report.id,
            family_id=test_family.id,
            data=update,
        )
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_delete_custom_report(
        self, db_session, test_family, test_parent_user
    ):
        from app.schemas.budget import CustomReportCreate

        data = CustomReportCreate(
            name="To Delete",
            config={"group_by": "category"},
        )
        report = await CustomReportService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            data=data,
        )

        await CustomReportService.delete_by_id(
            db_session, report.id, test_family.id
        )

        from app.core.exceptions import NotFoundException
        with pytest.raises(NotFoundException):
            await CustomReportService.get_by_id(
                db_session, report.id, test_family.id
            )

    @pytest.mark.asyncio
    async def test_generate_report_data(
        self, db_session, test_family, test_parent_user, budget_account, budget_category
    ):
        from app.schemas.budget import CustomReportCreate

        # Create some transactions
        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            category_id=budget_category.id,
            date=date.today() - timedelta(days=5),
            amount=-5000,
            cleared=True,
            reconciled=False,
        )
        db_session.add(txn)
        await db_session.commit()

        data = CustomReportCreate(
            name="Spending Report",
            config={
                "group_by": "category",
                "date_range": "last_30",
            },
        )
        report = await CustomReportService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            data=data,
        )

        result = await CustomReportService.generate_data(
            db_session, report, test_family.id
        )
        assert result is not None


# =============================================================================
# API ENDPOINT TESTS
# =============================================================================

class TestAutoFillAPI:
    """Test auto-fill endpoint via API."""

    @pytest.mark.asyncio
    async def test_auto_fill_endpoint(
        self, client, auth_headers, budget_category
    ):
        # Create allocation for March
        response = await client.post(
            "/api/budget/allocations/",
            headers=auth_headers,
            json={
                "category_id": str(budget_category.id),
                "month": "2026-10-01",
                "budgeted_amount": 40000,
            },
        )

        # Auto-fill November from October
        response = await client.post(
            "/api/budget/allocations/auto-fill",
            headers=auth_headers,
            json={
                "target_month": "2026-11-01",
                "strategy": "copy_previous",
                "overwrite_existing": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filled_count"] >= 0

    @pytest.mark.asyncio
    async def test_auto_fill_invalid_strategy(
        self, client, auth_headers
    ):
        response = await client.post(
            "/api/budget/allocations/auto-fill",
            headers=auth_headers,
            json={
                "target_month": "2026-11-01",
                "strategy": "invalid_strategy",
            },
        )
        assert response.status_code == 422


class TestCustomReportAPI:
    """Test custom report endpoints via API."""

    @pytest.mark.asyncio
    async def test_create_and_list_reports(self, client, auth_headers):
        # Create
        response = await client.post(
            "/api/budget/custom-reports/",
            headers=auth_headers,
            json={
                "name": "API Test Report",
                "config": {"group_by": "category", "date_range": "last_30"},
            },
        )
        assert response.status_code == 201
        report_id = response.json()["id"]

        # List
        response = await client.get(
            "/api/budget/custom-reports/",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert any(r["id"] == report_id for r in response.json())

    @pytest.mark.asyncio
    async def test_delete_report(self, client, auth_headers):
        # Create
        response = await client.post(
            "/api/budget/custom-reports/",
            headers=auth_headers,
            json={
                "name": "To Delete via API",
                "config": {"group_by": "month"},
            },
        )
        report_id = response.json()["id"]

        # Delete
        response = await client.delete(
            f"/api/budget/custom-reports/{report_id}",
            headers=auth_headers,
        )
        assert response.status_code == 204


class TestExportAPI:
    """Test export/import endpoints via API."""

    @pytest.mark.asyncio
    async def test_export_endpoint(self, client, auth_headers):
        response = await client.get(
            "/api/budget/export",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/zip"
