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
from datetime import date, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models import (
    Family,
    FamilyChatMessage,
    FamilyInvitation,
    GigClaim,
    GigOffering,
    Notification,
    PointTransaction,
    Reward,
    RewardCategory,
    TaskAssignment,
    TaskTemplate,
    TransactionType,
    User,
    UserRole,
)
from app.models.budget import BudgetAccount, BudgetReceiptDraft, BudgetTransaction
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
    db_session.add_all([
        BudgetTransaction(
            family_id=fam_a.id, account_id=account_a.id,
            date=date.today(), amount=-5000,
            receipt_image_path=gcs_path_a,
        ),
        BudgetTransaction(
            family_id=fam_b.id, account_id=account_b.id,
            date=date.today(), amount=-7000,
            receipt_image_path=gcs_path_b,
        ),
    ])
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

        # budget: only family A's account
        budget = json.loads(zf.read("budget/budget_data.json"))
        acct_names = {a["name"] for a in budget["accounts"]}
        assert acct_names == {"Alpha Cash"}
        assert len(budget["transactions"]) == 1

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

        # invitations: third-party email addresses are masked out
        invitations = json.loads(zf.read("invitations.json"))
        assert len(invitations) == 1
        assert all("invited_email" not in i for i in invitations)

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
