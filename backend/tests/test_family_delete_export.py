"""
Tests for WS-DEL: whole-family data export + self-serve family deletion.

Covers:
- GET /api/families/export returns a ZIP with the expected members and ONLY
  the caller's family data (two families seeded, isolation asserted).
- DELETE /api/families/me removes users/tasks/budget rows, cancels the PayPal
  subscription (mocked), deletes proof files on disk, blocks wrong re-auth,
  and leaves the other family untouched.
"""

import io
import json
import os
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models import (
    Family,
    FamilyA2AWebhook,
    FamilyChatMessage,
    FamilyInvitation,
    GigClaim,
    GigOffering,
    JarvisMcpToken,
    JarvisMessage,
    JarvisPendingAction,
    JarvisSchedule,
    KioskDevice,
    Notification,
    OnboardingEvent,
    PointTransaction,
    Reward,
    RewardCategory,
    TaskAssignment,
    TaskTemplate,
    TransactionType,
    UsageTracking,
    User,
    UserRole,
)
from app.models.budget import (
    BudgetAccount,
    BudgetReceiptDraft,
    BudgetTransaction,
    BudgetTransactionItem,
)
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.task_template import AssignmentType
from app.services.family_deletion_service import GIG_PROOFS_DIR, RECEIPT_DRAFTS_DIR


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession):
    """Two families with data in every domain the tests assert on."""
    fam_a = Family(name="Alpha Family")
    fam_b = Family(name="Beta Family")
    db_session.add_all([fam_a, fam_b])
    await db_session.flush()

    parent_a = User(
        email="parent-a@del.test",
        password_hash=get_password_hash("password123"),
        name="Parent A",
        role=UserRole.PARENT,
        family_id=fam_a.id,
        email_verified=True,
    )
    child_a = User(
        email="child-a@del.test",
        password_hash=get_password_hash("password123"),
        name="Child A",
        role=UserRole.CHILD,
        family_id=fam_a.id,
        email_verified=True,
    )
    parent_b = User(
        email="parent-b@del.test",
        password_hash=get_password_hash("password123"),
        name="Parent B",
        role=UserRole.PARENT,
        family_id=fam_b.id,
        email_verified=True,
    )
    db_session.add_all([parent_a, child_a, parent_b])
    await db_session.flush()

    # Tasks
    template_a = TaskTemplate(
        title="Alpha chores", points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
        family_id=fam_a.id,
    )
    template_b = TaskTemplate(
        title="Beta chores", points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
        family_id=fam_b.id,
    )
    db_session.add_all([template_a, template_b])
    await db_session.flush()

    proof_name = f"test-proof-{uuid.uuid4().hex}.jpg"
    assignment_a = TaskAssignment(
        template_id=template_a.id,
        assigned_to=child_a.id,
        family_id=fam_a.id,
        assigned_date=date.today(),
        week_of=date.today() - timedelta(days=date.today().weekday()),
        proof_image_url=f"/uploads/gig-proofs/{proof_name}",
    )
    db_session.add(assignment_a)

    # Gigs
    offering_a = GigOffering(
        family_id=fam_a.id, title="Alpha gig", points=25, created_by=parent_a.id
    )
    db_session.add(offering_a)
    await db_session.flush()
    claim_a = GigClaim(
        gig_id=offering_a.id,
        family_id=fam_a.id,
        claimed_by=child_a.id,
        proof_image_url="/uploads/gig-proofs/claim-proof-a.jpg",
    )
    db_session.add(claim_a)

    # Points
    db_session.add(
        PointTransaction(
            type=TransactionType.BONUS, points=10, user_id=child_a.id,
            balance_before=0, balance_after=10, description="alpha points",
        )
    )

    # Rewards
    db_session.add(
        Reward(
            family_id=fam_a.id, title="Alpha reward", points_cost=50,
            category=RewardCategory.TREATS, is_active=True,
        )
    )

    # Budget
    account_a = BudgetAccount(
        family_id=fam_a.id, name="Alpha Cash", type="checking", currency="MXN"
    )
    account_b = BudgetAccount(
        family_id=fam_b.id, name="Beta Cash", type="checking", currency="MXN"
    )
    db_session.add_all([account_a, account_b])
    await db_session.flush()
    # Scanned receipts live in GCS under <family_id>/<txn_id>.<ext> keys.
    gcs_path_a = f"{fam_a.id}/receipt-a.jpg"
    gcs_path_b = f"{fam_b.id}/receipt-b.jpg"
    txn_a = BudgetTransaction(
        family_id=fam_a.id, account_id=account_a.id,
        date=date.today(), amount=-5000,
        receipt_image_path=gcs_path_a,
    )
    txn_b = BudgetTransaction(
        family_id=fam_b.id, account_id=account_b.id,
        date=date.today(), amount=-7000,
        receipt_image_path=gcs_path_b,
    )
    # Soft-deleted (recycle-bin) transaction: must appear in
    # budget/recycle_bin.json but NOT in the re-importable backup.
    txn_a_deleted = BudgetTransaction(
        family_id=fam_a.id, account_id=account_a.id,
        date=date.today(), amount=-999,
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add_all([txn_a, txn_b, txn_a_deleted])
    await db_session.flush()
    db_session.add(
        BudgetTransactionItem(
            family_id=fam_a.id, transaction_id=txn_a.id,
            name="Milk", normalized_name="milk", total_cents=2500,
        )
    )
    draft_a = BudgetReceiptDraft(
        family_id=fam_a.id, account_id=account_a.id,
        scanned_data={"total_amount": 12.5}, confidence=0.1,
    )
    db_session.add(draft_a)
    await db_session.flush()
    draft_a.image_url = f"/api/budget/receipt-drafts/{draft_a.id}/image"

    # Chat + notifications
    db_session.add_all([
        FamilyChatMessage(family_id=fam_a.id, sender_id=parent_a.id, body="hola alpha"),
        FamilyChatMessage(family_id=fam_b.id, sender_id=parent_b.id, body="hola beta"),
        Notification(
            family_id=fam_a.id, user_id=child_a.id, type="task_assigned",
            title="Alpha notification",
        ),
    ])

    # Jarvis: chat history, schedule, pending HITL action, MCP token
    db_session.add_all([
        JarvisMessage(
            family_id=fam_a.id, user_id=parent_a.id,
            role="user", content="alpha jarvis question",
        ),
        JarvisMessage(
            family_id=fam_b.id, user_id=parent_b.id,
            role="user", content="beta jarvis question",
        ),
        JarvisSchedule(
            family_id=fam_a.id, created_by=parent_a.id,
            name="Alpha digest", prompt="daily summary",
            cron_expr="0 8 * * *", channel="notification",
        ),
        JarvisPendingAction(
            family_id=fam_a.id, user_id=parent_a.id,
            tool_name="budget_account_delete", params={}, summary="Delete acct",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
        JarvisMcpToken(
            family_id=fam_a.id, created_by=parent_a.id, label="cli token",
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            token_prefix="mcp_a1b2",
        ),
    ])

    # Kiosk device (token is a credential — must be stripped from the export)
    # + a family-B device to pin isolation of the kiosk export query.
    db_session.add_all([
        KioskDevice(
            family_id=fam_a.id, name="Hallway tablet",
            token=f"kiosk-{uuid.uuid4().hex}"[:64], created_by=parent_a.id,
        ),
        KioskDevice(
            family_id=fam_b.id, name="Beta tablet",
            token=f"kiosk-{uuid.uuid4().hex}"[:64], created_by=parent_b.id,
        ),
    ])

    # Onboarding funnel events (one per family — isolation)
    db_session.add_all([
        OnboardingEvent(
            user_id=child_a.id, family_id=fam_a.id,
            event_type="tour_completed", step_index=5,
        ),
        OnboardingEvent(
            user_id=parent_b.id, family_id=fam_b.id,
            event_type="tour_skipped", step_index=0,
        ),
    ])

    # A2A webhook config (signing secret must be stripped from the export)
    db_session.add(
        FamilyA2AWebhook(
            family_id=fam_a.id, url="https://price-agent.example/hook",
            secret="a2a-signing-secret", enabled=True,
        )
    )

    # Metered usage
    db_session.add(
        UsageTracking(
            family_id=fam_a.id, feature="receipt_scan",
            period_start=date.today().replace(day=1), count=2,
        )
    )

    # Invitation (the one table with NO delete rule on its FKs)
    db_session.add(
        FamilyInvitation(
            family_id=fam_a.id,
            invited_email="invitee@del.test",
            invited_by_user_id=parent_a.id,
            invitation_code=FamilyInvitation.generate_code(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
    )

    # Subscription with a live PayPal id
    plan = SubscriptionPlan(
        name=f"test-plan-{uuid.uuid4().hex[:8]}", display_name="Test Pro",
        display_name_es="Test Pro", limits={},
    )
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        FamilySubscription(
            family_id=fam_a.id, plan_id=plan.id, billing_cycle="monthly",
            status="active", paypal_subscription_id="I-TESTSUB123",
        )
    )

    await db_session.commit()
    return {
        "fam_a": fam_a,
        "fam_b": fam_b,
        "parent_a": parent_a,
        "child_a": child_a,
        "parent_b": parent_b,
        "template_a": template_a,
        "template_b": template_b,
        "account_a": account_a,
        "account_b": account_b,
        "proof_name": proof_name,
        "draft_a_id": draft_a.id,
        "gcs_path_a": gcs_path_a,
        "gcs_path_b": gcs_path_b,
    }


async def _count(db, model, family_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(model).where(model.family_id == family_id)
        )
    ).scalar()


class TestFamilyExport:
    async def test_export_zip_members_and_isolation(
        self, client: AsyncClient, seeded
    ):
        r = await client.get("/api/families/export", headers=_auth(seeded["parent_a"]))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert "attachment" in r.headers["content-disposition"]

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        expected = {
            "README.txt",
            "metadata.json",
            "users.json",
            "tasks/task_templates.json",
            "tasks/task_assignments.json",
            "gigs/offerings.json",
            "gigs/claims.json",
            "points/point_transactions.json",
            "rewards/rewards.json",
            "chat/messages.json",
            "notifications.json",
            "invitations.json",
            "uploads_manifest.json",
            "budget/budget_data.json",
            "budget/metadata.json",
            "budget/extras.json",
        }
        assert expected <= names, f"missing: {expected - names}"

        # users.json: own family only, credentials stripped
        users = json.loads(zf.read("users.json"))
        emails = {u["email"] for u in users}
        assert emails == {"parent-a@del.test", "child-a@del.test"}
        assert all("password_hash" not in u for u in users)
        assert all("token_version" not in u for u in users)

        # templates: only family A's
        templates = json.loads(zf.read("tasks/task_templates.json"))
        titles = {t["title"] for t in templates}
        assert "Alpha chores" in titles
        assert "Beta chores" not in titles

        # budget: only family A's account; soft-deleted txn NOT in the backup
        budget = json.loads(zf.read("budget/budget_data.json"))
        acct_names = {a["name"] for a in budget["accounts"]}
        assert acct_names == {"Alpha Cash"}
        assert len(budget["transactions"]) == 1

        # recycle bin: soft-deleted rows ARE in the compliance export
        recycle = json.loads(zf.read("budget/recycle_bin.json"))
        assert [t["amount"] for t in recycle["transactions"]] == [-999]
        assert recycle["accounts"] == []

        # chat isolation
        messages = json.loads(zf.read("chat/messages.json"))
        assert {m["body"] for m in messages} == {"hola alpha"}

        # uploads manifest lists proof paths (no binaries in the zip)
        manifest = json.loads(zf.read("uploads_manifest.json"))
        paths = {m["path"] for m in manifest}
        assert f"/uploads/gig-proofs/{seeded['proof_name']}" in paths
        assert "/uploads/gig-proofs/claim-proof-a.jpg" in paths
        kinds = {m["kind"] for m in manifest}
        assert {"task_proof", "gig_proof", "receipt_draft", "receipt_image"} <= kinds
        # GCS receipt keys: own family's present, other family's absent
        assert seeded["gcs_path_a"] in paths
        assert seeded["gcs_path_b"] not in paths

        # invitations: third-party email masked AND live join code stripped
        invitations = json.loads(zf.read("invitations.json"))
        assert len(invitations) == 1
        assert all("invited_email" not in i for i in invitations)
        assert all("invitation_code" not in i for i in invitations)

        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["family_id"] == str(seeded["fam_a"].id)
        assert metadata["family_name"] == "Alpha Family"
        assert metadata["counts"]["users.json"] == 2
        # budget extras report per-key record counts, not the wrapper length
        extras_counts = metadata["counts"]["budget/extras.json"]
        assert extras_counts["receipt_drafts"] == 1
        assert extras_counts["saved_filters"] == 0

    async def test_export_forbidden_for_child(self, client: AsyncClient, seeded):
        r = await client.get("/api/families/export", headers=_auth(seeded["child_a"]))
        assert r.status_code == 403

    async def test_export_requires_auth(self, client: AsyncClient, seeded):
        r = await client.get("/api/families/export")
        assert r.status_code == 401

    async def test_export_includes_jarvis_kiosk_onboarding_and_extras(
        self, client: AsyncClient, seeded
    ):
        """Regression (whole-PR review): Jarvis history/schedules, kiosk
        devices, onboarding events, subscription/usage, A2A config and budget
        transaction items must all be in the export — with credential columns
        stripped and other-family data absent."""
        r = await client.get("/api/families/export", headers=_auth(seeded["parent_a"]))
        assert r.status_code == 200, r.text

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        expected = {
            "jarvis/messages.json",
            "jarvis/schedules.json",
            "jarvis/pending_actions.json",
            "jarvis/mcp_tokens.json",
            "kiosk/devices.json",
            "onboarding_events.json",
            "subscription/subscription.json",
            "subscription/usage_tracking.json",
            "a2a/webhook_config.json",
        }
        assert expected <= names, f"missing: {expected - names}"

        # Jarvis chat history: own family only
        msgs = json.loads(zf.read("jarvis/messages.json"))
        assert {m["content"] for m in msgs} == {"alpha jarvis question"}

        scheds = json.loads(zf.read("jarvis/schedules.json"))
        assert [s["name"] for s in scheds] == ["Alpha digest"]
        assert scheds[0]["cron_expr"] == "0 8 * * *"

        actions = json.loads(zf.read("jarvis/pending_actions.json"))
        assert [a["tool_name"] for a in actions] == ["budget_account_delete"]

        # MCP tokens: metadata only, hash stripped
        tokens = json.loads(zf.read("jarvis/mcp_tokens.json"))
        assert [t["label"] for t in tokens] == ["cli token"]
        assert all("token_hash" not in t for t in tokens)
        assert tokens[0]["token_prefix"] == "mcp_a1b2"

        # Kiosk devices: name kept, credential token stripped, family B absent
        kiosks = json.loads(zf.read("kiosk/devices.json"))
        assert [k["name"] for k in kiosks] == ["Hallway tablet"]
        assert all("token" not in k for k in kiosks)

        # Onboarding events: family B's event absent
        onboarding = json.loads(zf.read("onboarding_events.json"))
        assert [e["event_type"] for e in onboarding] == ["tour_completed"]
        assert onboarding[0]["step_index"] == 5

        subs = json.loads(zf.read("subscription/subscription.json"))
        assert len(subs) == 1
        assert subs[0]["paypal_subscription_id"] == "I-TESTSUB123"

        usage = json.loads(zf.read("subscription/usage_tracking.json"))
        assert [(u["feature"], u["count"]) for u in usage] == [("receipt_scan", 2)]

        # A2A webhook config: url kept, signing secret stripped
        hooks = json.loads(zf.read("a2a/webhook_config.json"))
        assert [h["url"] for h in hooks] == ["https://price-agent.example/hook"]
        assert all("secret" not in h for h in hooks)

        # Receipt line items ride along in budget/extras.json
        extras = json.loads(zf.read("budget/extras.json"))
        assert [i["name"] for i in extras["transaction_items"]] == ["Milk"]

        # README documents the deliberate exclusions
        readme = zf.read("README.txt").decode()
        assert "a2a_webhook_deliveries" in readme
        assert "budget_sync_state" in readme

    def test_every_family_scoped_table_is_exported_or_excluded(self):
        """Every family_id-bearing table must be covered by the export or be
        a documented exclusion — a new family-scoped model that is neither
        fails here instead of silently missing from the compliance export."""
        from app.core.database import Base
        from app.services.family_export_service import (
            EXCLUDED_FAMILY_TABLES,
            EXPORTED_FAMILY_TABLES,
        )

        family_tables = {
            table.name
            for table in Base.metadata.tables.values()
            if "family_id" in table.columns
        }
        covered = EXPORTED_FAMILY_TABLES | set(EXCLUDED_FAMILY_TABLES)
        missing = family_tables - covered
        assert not missing, (
            "family-scoped tables not covered by the family export — add them "
            "to FamilyExportService or document them in EXCLUDED_FAMILY_TABLES: "
            f"{sorted(missing)}"
        )
        stale = covered - family_tables
        assert not stale, (
            f"export coverage lists tables that do not exist: {sorted(stale)}"
        )


class TestExportRateLimit:
    @pytest.fixture(autouse=True)
    def _enable_rate_limiter(self):
        """This class needs the limiter ON (conftest disables it elsewhere)."""
        from app.core.rate_limiter import limiter

        limiter.reset()
        limiter.enabled = True
        yield
        limiter.enabled = False
        limiter.reset()

    async def test_export_burst_is_rate_limited(self, client: AsyncClient, seeded):
        """Regression (whole-PR review): the in-memory ZIP build must be
        behind a strict per-IP limit (3/hour) — the 4th call 429s."""
        statuses = []
        for _ in range(4):
            r = await client.get(
                "/api/families/export", headers=_auth(seeded["parent_a"])
            )
            statuses.append(r.status_code)
        assert statuses[:3] == [200, 200, 200], statuses
        assert statuses[3] == 429, statuses


class TestExportSizeGuard:
    async def test_row_cap_returns_413(
        self, client: AsyncClient, seeded, monkeypatch
    ):
        """When the pre-flight row estimate exceeds the cap, the export is
        refused BEFORE loading everything into memory."""
        import app.services.family_export_service as fes

        monkeypatch.setattr(fes, "EXPORT_MAX_ROWS", 0)
        r = await client.get("/api/families/export", headers=_auth(seeded["parent_a"]))
        assert r.status_code == 413, r.text
        assert "too large" in r.json()["detail"]

    async def test_byte_cap_returns_413(
        self, client: AsyncClient, seeded, monkeypatch
    ):
        """Backstop: an archive past the byte cap is never shipped."""
        import app.services.family_export_service as fes

        monkeypatch.setattr(fes, "EXPORT_MAX_BYTES", 10)
        r = await client.get("/api/families/export", headers=_auth(seeded["parent_a"]))
        assert r.status_code == 413, r.text


class TestFamilyDeletion:
    async def test_wrong_password_blocks_deletion(
        self, client: AsyncClient, db_session: AsyncSession, seeded, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda *a, **k: calls.append(a),
        )
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["parent_a"]),
            json={"password": "not-the-password"},
        )
        assert r.status_code == 403
        assert calls == []
        # Family and users untouched
        fam = (
            await db_session.execute(
                select(Family).where(Family.id == seeded["fam_a"].id)
            )
        ).scalar_one_or_none()
        assert fam is not None
        assert await _count(db_session, User, seeded["fam_a"].id) == 2

    async def test_missing_password_blocks_deletion(
        self, client: AsyncClient, db_session: AsyncSession, seeded
    ):
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["parent_a"]),
            json={"confirm_name": "Alpha Family"},  # name alone is not enough
        )
        assert r.status_code == 403
        assert await _count(db_session, User, seeded["fam_a"].id) == 2

    async def test_child_cannot_delete_family(self, client: AsyncClient, seeded):
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["child_a"]),
            json={"password": "password123"},
        )
        assert r.status_code == 403

    async def test_delete_family_removes_everything_and_cancels_paypal(
        self, client: AsyncClient, db_session: AsyncSession, seeded, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda sub_id, reason="": calls.append(sub_id),
        )
        # No GCS bucket configured (on-prem shape): blob deletion is skipped
        # and family deletion must still complete.
        monkeypatch.setattr(settings, "GCS_RECEIPT_BUCKET", "")

        # Real proof files on disk that must be removed with the family.
        os.makedirs(GIG_PROOFS_DIR, exist_ok=True)
        os.makedirs(RECEIPT_DRAFTS_DIR, exist_ok=True)
        proof_path = os.path.join(GIG_PROOFS_DIR, seeded["proof_name"])
        draft_path = os.path.join(RECEIPT_DRAFTS_DIR, f"{seeded['draft_a_id']}.jpg")
        for p in (proof_path, draft_path):
            with open(p, "wb") as f:
                f.write(b"fake-image-bytes")

        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["parent_a"]),
            json={"password": "password123"},
        )
        assert r.status_code == 204, r.text

        fam_a_id, fam_b_id = seeded["fam_a"].id, seeded["fam_b"].id

        # Family row gone
        fam = (
            await db_session.execute(select(Family).where(Family.id == fam_a_id))
        ).scalar_one_or_none()
        assert fam is None

        # All family-scoped rows gone
        assert await _count(db_session, User, fam_a_id) == 0
        assert await _count(db_session, TaskTemplate, fam_a_id) == 0
        assert await _count(db_session, TaskAssignment, fam_a_id) == 0
        assert await _count(db_session, GigOffering, fam_a_id) == 0
        assert await _count(db_session, GigClaim, fam_a_id) == 0
        assert await _count(db_session, Reward, fam_a_id) == 0
        assert await _count(db_session, BudgetAccount, fam_a_id) == 0
        assert await _count(db_session, BudgetTransaction, fam_a_id) == 0
        assert await _count(db_session, BudgetReceiptDraft, fam_a_id) == 0
        assert await _count(db_session, FamilyChatMessage, fam_a_id) == 0
        assert await _count(db_session, Notification, fam_a_id) == 0
        assert await _count(db_session, FamilyInvitation, fam_a_id) == 0
        assert await _count(db_session, FamilySubscription, fam_a_id) == 0

        # User-scoped rows gone too (point transactions have no family_id)
        pt_count = (
            await db_session.execute(
                select(func.count())
                .select_from(PointTransaction)
                .join(User, PointTransaction.user_id == User.id)
                .where(User.family_id == fam_a_id)
            )
        ).scalar()
        assert pt_count == 0

        # PayPal cancelled exactly once with the live subscription id
        assert calls == ["I-TESTSUB123"]

        # Upload files removed from disk
        assert not os.path.exists(proof_path)
        assert not os.path.exists(draft_path)

        # Other family untouched
        assert await _count(db_session, User, fam_b_id) == 1
        assert await _count(db_session, TaskTemplate, fam_b_id) == 1
        assert await _count(db_session, BudgetAccount, fam_b_id) == 1
        assert await _count(db_session, BudgetTransaction, fam_b_id) == 1
        assert await _count(db_session, FamilyChatMessage, fam_b_id) == 1

        # The deleted parent's token no longer authenticates
        r2 = await client.get("/api/families/me", headers=_auth(seeded["parent_a"]))
        assert r2.status_code == 401

    async def test_delete_family_removes_gcs_receipt_images(
        self, client: AsyncClient, db_session: AsyncSession, seeded, monkeypatch
    ):
        """Scanned receipt blobs in GCS are deleted with the family."""
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(settings, "GCS_RECEIPT_BUCKET", "test-receipts-bucket")
        deleted_blobs: list[str] = []
        monkeypatch.setattr(
            "app.services.storage.gcs_receipt_service.GCSReceiptStorage.delete",
            lambda path: deleted_blobs.append(path),
        )

        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["parent_a"]),
            json={"password": "password123"},
        )
        assert r.status_code == 204, r.text

        # Family A's blob deleted; family B's untouched.
        assert deleted_blobs == [seeded["gcs_path_a"]]

        fam = (
            await db_session.execute(
                select(Family).where(Family.id == seeded["fam_a"].id)
            )
        ).scalar_one_or_none()
        assert fam is None

    async def test_delete_family_proceeds_when_gcs_delete_fails(
        self, client: AsyncClient, db_session: AsyncSession, seeded, monkeypatch
    ):
        """A GCS error never blocks deletion (best-effort, like PayPal)."""
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(settings, "GCS_RECEIPT_BUCKET", "test-receipts-bucket")

        def _boom(path):
            raise RuntimeError("GCS unavailable")

        monkeypatch.setattr(
            "app.services.storage.gcs_receipt_service.GCSReceiptStorage.delete",
            _boom,
        )

        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(seeded["parent_a"]),
            json={"password": "password123"},
        )
        assert r.status_code == 204, r.text
        fam = (
            await db_session.execute(
                select(Family).where(Family.id == seeded["fam_a"].id)
            )
        ).scalar_one_or_none()
        assert fam is None

    async def test_google_only_account_requires_family_name(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda *a, **k: None,
        )
        fam = Family(name="Gamma Family")
        db_session.add(fam)
        await db_session.flush()
        google_parent = User(
            email="google-parent@del.test",
            password_hash=None,  # Google-only account
            name="Google Parent",
            role=UserRole.PARENT,
            family_id=fam.id,
            email_verified=True,
            oauth_provider="google",
            oauth_id="g-123",
        )
        db_session.add(google_parent)
        await db_session.commit()

        # Wrong name → 400
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(google_parent),
            json={"confirm_name": "Wrong Name"},
        )
        assert r.status_code == 400
        assert await _count(db_session, User, fam.id) == 1

        # Missing name → 400
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(google_parent),
            json={},
        )
        assert r.status_code == 400

        # Correct name (case/whitespace tolerant) → deleted
        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(google_parent),
            json={"confirm_name": "  gamma family "},
        )
        assert r.status_code == 204, r.text
        gone = (
            await db_session.execute(select(Family).where(Family.id == fam.id))
        ).scalar_one_or_none()
        assert gone is None


class TestDeletionPayPalCancel:
    """Regression (whole-PR review, MAJOR 5): deletion must cancel the PayPal
    agreement for ANY status that could still bill (grace_expired, suspended,
    ...), and a cancel failure must be reported, never block deletion."""

    async def _family_with_sub(self, db_session, *, status, paypal_id):
        fam = Family(name=f"PayPal Cancel {uuid.uuid4().hex[:6]}")
        db_session.add(fam)
        await db_session.flush()
        plan = SubscriptionPlan(
            name=f"del-plan-{uuid.uuid4().hex[:8]}", display_name="P",
            display_name_es="P", limits={},
        )
        db_session.add(plan)
        await db_session.flush()
        sub = FamilySubscription(
            family_id=fam.id, plan_id=plan.id, billing_cycle="monthly",
            status=status, paypal_subscription_id=paypal_id,
        )
        db_session.add(sub)
        await db_session.commit()
        return fam

    async def test_grace_expired_sub_is_cancelled_at_paypal(
        self, db_session: AsyncSession, monkeypatch
    ):
        from app.services.family_deletion_service import FamilyDeletionService

        fam = await self._family_with_sub(
            db_session, status="grace_expired", paypal_id="I-GRACE-DEL"
        )
        calls = []
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda sub_id, reason="": calls.append(sub_id),
        )
        failed = await FamilyDeletionService._cancel_paypal_subscriptions(
            db_session, fam.id
        )
        assert calls == ["I-GRACE-DEL"]
        assert failed == []

    async def test_suspended_sub_is_cancelled_at_paypal(
        self, db_session: AsyncSession, monkeypatch
    ):
        from app.services.family_deletion_service import FamilyDeletionService

        fam = await self._family_with_sub(
            db_session, status="suspended", paypal_id="I-SUSP-DEL"
        )
        calls = []
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda sub_id, reason="": calls.append(sub_id),
        )
        failed = await FamilyDeletionService._cancel_paypal_subscriptions(
            db_session, fam.id
        )
        assert calls == ["I-SUSP-DEL"]
        assert failed == []

    async def test_locally_cancelled_sub_is_still_cancelled_at_paypal(
        self, db_session: AsyncSession, monkeypatch
    ):
        """Regression (re-review, MINOR): local 'cancelled' can lie — /cancel
        swallows a PayPal cancel failure with a warning and the sweep later
        flips the row to 'cancelled' locally, so the agreement may still be
        billing. Deletion must attempt the PayPal cancel unconditionally for
        any row with a paypal_subscription_id (a cancel of a genuinely-dead
        sub is a harmless best-effort failure in the audit trail)."""
        from app.services.family_deletion_service import FamilyDeletionService

        fam = await self._family_with_sub(
            db_session, status="cancelled", paypal_id="I-ALREADY-CANCELLED"
        )
        calls = []
        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            lambda sub_id, reason="": calls.append(sub_id),
        )
        failed = await FamilyDeletionService._cancel_paypal_subscriptions(
            db_session, fam.id
        )
        assert calls == ["I-ALREADY-CANCELLED"]
        assert failed == []

    async def test_cancel_failure_is_reported_and_deletion_proceeds(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """A PayPal outage during deletion: family still deleted (user right),
        the failed id surfaces in the return for the operator audit line."""
        from app.services.family_deletion_service import FamilyDeletionService

        fam = await self._family_with_sub(
            db_session, status="grace_expired", paypal_id="I-BOOM-DEL"
        )

        def _boom(sub_id, reason=""):
            raise RuntimeError("paypal down")

        monkeypatch.setattr(
            "app.services.paypal_service.PayPalService.cancel_subscription",
            _boom,
        )
        failed = await FamilyDeletionService._cancel_paypal_subscriptions(
            db_session, fam.id
        )
        assert failed == ["I-BOOM-DEL"]

        # End-to-end: deletion still completes despite the cancel failure.
        parent = User(
            email=f"paypal-boom-{uuid.uuid4().hex[:6]}@del.test",
            password_hash=get_password_hash("password123"),
            name="Boom Parent",
            role=UserRole.PARENT,
            family_id=fam.id,
            email_verified=True,
        )
        db_session.add(parent)
        await db_session.commit()

        r = await client.request(
            "DELETE",
            "/api/families/me",
            headers=_auth(parent),
            json={"password": "password123"},
        )
        assert r.status_code == 204, r.text
        gone = (
            await db_session.execute(select(Family).where(Family.id == fam.id))
        ).scalar_one_or_none()
        assert gone is None
