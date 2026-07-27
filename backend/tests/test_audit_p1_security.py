"""P1 security/correctness fixes from the 2026-07-27 forensic audit.

Each class pins one finding that was verified against a live database before
being fixed. They are grouped here rather than split across files because they
share a theme: a guard that existed on the main path and was missing on every
other path that reaches the same data.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.exceptions import UnauthorizedException, ValidationError
from app.core.family_guards import assert_family_usable


class TestFamilyUsableGuard:
    """`is_active` was enforced only on the session-auth path."""

    def test_suspended_family_is_refused(self):
        class _Fam:
            deleted_at = None
            is_active = False

        with pytest.raises(HTTPException) as exc:
            assert_family_usable(_Fam())
        assert exc.value.status_code == 401
        assert "suspended" in str(exc.value.detail).lower()

    def test_closed_family_is_refused(self):
        class _Fam:
            deleted_at = "2026-07-01"
            is_active = True

        with pytest.raises(HTTPException) as exc:
            assert_family_usable(_Fam())
        assert exc.value.status_code == 401

    def test_active_family_passes(self):
        class _Fam:
            deleted_at = None
            is_active = True

        assert_family_usable(_Fam())

    def test_missing_family_is_left_to_the_caller(self):
        """Some paths treat an absent row as 404 'not registered', not 401."""
        assert_family_usable(None)

    def test_every_token_path_calls_the_guard(self):
        """Regression: each of these grew its own partial check and drifted."""
        import inspect

        from app.api.routes.budget import bank_sync
        from app.services import kiosk_service

        assert "assert_family_usable" in inspect.getsource(kiosk_service)
        assert "assert_family_usable" in inspect.getsource(bank_sync)

    def test_mcp_token_lookup_filters_on_is_active(self):
        """The /mcp bearer grants full family-scoped CRUD, incl. money tools."""
        import inspect

        from app.services import jarvis_mcp_token_service

        source = inspect.getsource(jarvis_mcp_token_service)
        assert "Family.is_active.is_(True)" in source


class TestGoogleAccountLinking:
    """Linking on an unverified email is the pre-hijacking pattern."""

    async def test_unverified_email_cannot_link_to_an_existing_account(
        self, db, test_parent_user
    ):
        from app.services.google_oauth_service import GoogleOAuthService

        info = {
            "google_id": "g-attacker",
            "email": test_parent_user.email,
            "name": "Not The Owner",
            "email_verified": False,
        }

        with pytest.raises(UnauthorizedException):
            await GoogleOAuthService.authenticate_or_create_user(db, info)

        await db.refresh(test_parent_user)
        assert test_parent_user.oauth_id != "g-attacker", (
            "an unverified Google identity was bound to an existing account"
        )


class TestSchedulerFailsClosed:
    """Failing open with --workers 2 double-fires money-moving sweeps."""

    async def test_unreachable_redis_declines_leadership_by_default(self):
        from app.core import scheduler_lock

        with patch.object(scheduler_lock.settings, "SCHEDULER_FAIL_OPEN", False), \
             patch.object(scheduler_lock, "ACQUIRE_ATTEMPTS", 2), \
             patch.object(scheduler_lock, "ACQUIRE_BACKOFF_SECONDS", 0), \
             patch.object(
                 scheduler_lock.aioredis, "from_url",
                 side_effect=OSError("connection refused"),
             ):
            is_leader, client, token = (
                await scheduler_lock.try_acquire_scheduler_leadership("redis://nope")
            )

        assert is_leader is False
        assert client is None and token is None

    async def test_fail_open_is_opt_in(self):
        from app.core import scheduler_lock

        with patch.object(scheduler_lock.settings, "SCHEDULER_FAIL_OPEN", True), \
             patch.object(scheduler_lock, "ACQUIRE_ATTEMPTS", 2), \
             patch.object(scheduler_lock, "ACQUIRE_BACKOFF_SECONDS", 0), \
             patch.object(
                 scheduler_lock.aioredis, "from_url",
                 side_effect=OSError("connection refused"),
             ):
            is_leader, _, _ = (
                await scheduler_lock.try_acquire_scheduler_leadership("redis://nope")
            )

        assert is_leader is True

    def test_default_is_fail_closed(self):
        from app.core.config import Settings

        assert Settings().SCHEDULER_FAIL_OPEN is False

    async def test_losing_the_lock_is_reported_to_the_caller(self):
        """A False return is the signal to stop running scheduled jobs."""
        from app.core import scheduler_lock

        class _Client:
            async def eval(self, *_a, **_kw):
                return 0  # token mismatch — someone else holds the lock

        still_leader = await scheduler_lock.renew_scheduler_leadership(
            _Client(), "our-token"
        )
        assert still_leader is False

    async def test_transient_redis_error_does_not_drop_leadership(self):
        from app.core import scheduler_lock

        class _Client:
            async def eval(self, *_a, **_kw):
                raise OSError("blip")

        assert await scheduler_lock.renew_scheduler_leadership(
            _Client(), "our-token"
        ) is True


class TestRecipeImportSSRF:
    """The backend can reach the LAN and metadata endpoints a browser cannot."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/admin",
            "http://localhost/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.1.0.91:5432/",
            "http://192.168.1.1/",
        ],
    )
    def test_private_and_link_local_targets_are_refused(self, url):
        from app.services.recipe_importer import _assert_public_url

        with pytest.raises(ValidationError):
            _assert_public_url(url)

    def test_dangerous_ports_are_refused(self):
        from app.services.recipe_importer import _assert_public_url

        with pytest.raises(ValidationError):
            _assert_public_url("http://example.com:6379/")

    def test_redirects_are_not_followed_blindly(self):
        """A public URL that 302s to 127.0.0.1 would defeat the check."""
        import inspect

        from app.services import recipe_importer

        source = inspect.getsource(recipe_importer.import_recipe_from_url)
        assert "follow_redirects=False" in source
        assert source.count("_assert_public_url") >= 2, (
            "each redirect hop must be validated, not just the first URL"
        )


class TestJarvisErrorCodes:
    """A spent quota is not a gateway failure."""

    def test_quota_and_upstream_are_distinct_types(self):
        from app.services.jarvis_service import (
            JarvisQuotaExceeded,
            JarvisUpstreamError,
        )

        assert issubclass(JarvisQuotaExceeded, ValidationError)
        assert issubclass(JarvisUpstreamError, ValidationError)
        assert not issubclass(JarvisQuotaExceeded, JarvisUpstreamError)

    def test_route_maps_each_condition_to_its_own_status(self):
        import inspect

        from app.api.routes import jarvis

        source = inspect.getsource(jarvis.chat)
        assert "JarvisQuotaExceeded" in source and "429" in source
        assert "JarvisUpstreamError" in source and "502" in source
        assert "400" in source, "plain validation errors must not be 5xx"

    def test_unconfigured_service_is_not_a_client_error(self):
        """'Set LITELLM_API_KEY' is OUR misconfiguration, so it stays 5xx.

        The first cut of this fix mapped every remaining ValidationError to 400,
        which turned a server-side config failure into "bad request".
        """
        import inspect

        from app.services import jarvis_service

        source = inspect.getsource(jarvis_service)
        assert "JarvisUpstreamError(\n                \"Jarvis not configured" in source \
            or 'JarvisUpstreamError("Jarvis not configured' in source


class TestReportsAreFamilyScoped:
    async def test_budget_vs_actual_subqueries_filter_on_family(self):
        import inspect

        from app.api.routes.budget import reports

        source = inspect.getsource(reports)
        assert "BudgetAllocation.family_id == family_id" in source
        assert "BudgetTransaction.family_id == family_id" in source


class TestOperatorAuditCompleteness:
    async def test_no_action_narrows_its_failure_catch(self):
        """The module promises a failed action still leaves an audit row.

        Three actions caught only HTTPException/FamilyAppException, so a plain
        DB error escaped the _record_failure path entirely.
        """
        import inspect

        from app.services.admin import admin_action_service

        source = inspect.getsource(admin_action_service)
        assert "except HTTPException as exc:" not in source
        assert "except (HTTPException, FamilyAppException) as exc:" not in source


class TestAuthlibRemoved:
    def test_authlib_is_not_a_dependency(self):
        """authlib==1.3.0 shipped in the prod image, imported nowhere, and
        predates the CVE-2024-37568 fix."""
        from pathlib import Path

        req = Path(__file__).resolve().parents[1] / "requirements.txt"
        lines = [
            line for line in req.read_text().splitlines()
            if line.strip().lower().startswith("authlib")
        ]
        assert lines == [], f"authlib is back in requirements.txt: {lines}"


class TestBudgetBackupImport:
    """The only budget path that rebuilt rows straight from an untrusted file."""

    @staticmethod
    def _zip(payload: dict) -> bytes:
        import io
        import json
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("budget_data.json", json.dumps(payload))
        return buf.getvalue()

    async def test_foreign_key_outside_the_archive_is_rejected(
        self, db, family, other_family, account_factory
    ):
        """A crafted archive could point this family's rows at another family's
        account: the FK references the global table, so it inserts cleanly."""
        from app.services.budget.export_service import ExportService

        theirs = await account_factory(other_family.id, name="Theirs")
        archive = self._zip({
            "accounts": [],
            "transactions": [{
                "id": "11111111-1111-1111-1111-111111111111",
                "account_id": str(theirs.id),
                "date": "2026-02-10",
                "amount": -5000,
            }],
        })

        with pytest.raises(ValidationError):
            await ExportService.import_budget(db, family.id, archive)
        await db.rollback()

    async def test_ids_are_reminted_rather_than_trusted(
        self, db, family, account_factory
    ):
        from sqlalchemy import select

        from app.models.budget import BudgetAccount
        from app.services.budget.export_service import ExportService

        forged = "22222222-2222-2222-2222-222222222222"
        archive = self._zip({
            "accounts": [{
                "id": forged, "name": "Imported", "type": "checking",
            }],
        })

        await ExportService.import_budget(db, family.id, archive)

        rows = (await db.execute(
            select(BudgetAccount).where(BudgetAccount.family_id == family.id)
        )).scalars().all()
        assert len(rows) == 1
        assert str(rows[0].id) != forged, "client-supplied primary key was trusted"

    async def test_internal_references_survive_the_remap(self, db, family):
        """Remapping must keep the archive's own relationships intact."""
        from sqlalchemy import select

        from app.models.budget import BudgetTransaction
        from app.services.budget.export_service import ExportService

        acct_id = "33333333-3333-3333-3333-333333333333"
        archive = self._zip({
            "accounts": [{"id": acct_id, "name": "Checking", "type": "checking"}],
            "transactions": [{
                "id": "44444444-4444-4444-4444-444444444444",
                "account_id": acct_id,
                "date": "2026-02-10",
                "amount": -5000,
            }],
        })

        await ExportService.import_budget(db, family.id, archive)

        txn = (await db.execute(
            select(BudgetTransaction).where(BudgetTransaction.family_id == family.id)
        )).scalar_one()
        assert txn.account_id is not None
        assert str(txn.account_id) != acct_id

    async def test_zip_bomb_is_refused_before_decompression(self, db, family):
        """Only the COMPRESSED upload was capped; DEFLATE reaches ~1000:1."""
        import io
        import zipfile

        from app.services.budget import export_service
        from app.services.budget.export_service import ExportService

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("budget_data.json", b"0" * (2 * 1024 * 1024))

        with patch.object(export_service, "MAX_UNCOMPRESSED_BYTES", 1024):
            with pytest.raises(ValidationError, match="too large|expands"):
                await ExportService.import_budget(db, family.id, buf.getvalue())
        await db.rollback()

    async def test_missing_member_is_a_clean_error(self, db, family):
        import io
        import zipfile

        from app.services.budget.export_service import ExportService

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("something_else.json", "{}")

        with pytest.raises(ValidationError, match="missing"):
            await ExportService.import_budget(db, family.id, buf.getvalue())
        await db.rollback()
