"""
Tests for app.core.vault_bootstrap.populate_env_from_vault

The function is called once at config.py import time and folds Vault KV v2
values into os.environ so the existing pydantic Settings() picks them up
without any custom source. We verify:

1. Missing VAULT_ADDR/TOKEN → no-op
2. Vault auth failure → no-op (but logged)
3. Successful read → values land in os.environ
4. Pre-existing env vars are NOT overwritten (local dev override wins)
5. Empty string values are skipped (pre-populated .env stubs in Vault)
6. hvac exceptions are caught and logged (don't crash app startup)
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from app.core import vault_bootstrap


@pytest.fixture
def clean_env():
    """Snapshot and restore os.environ to isolate tests."""
    saved = dict(os.environ)
    # Strip anything this test family might set
    for k in [
        "VAULT_ADDR",
        "VAULT_TOKEN",
        "VAULT_PATH",
        "VAULT_MOUNT",
        "FTM_TEST_SECRET",
        "FTM_TEST_EMPTY",
        "FTM_TEST_OVERRIDE",
        "FTM_TEST_DB_URL",
    ]:
        os.environ.pop(k, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _mock_hvac_client(authenticated: bool, data: dict | None = None, raise_exc=None):
    """Build a mock hvac.Client whose KV v2 read returns `data`."""
    client = MagicMock()
    client.is_authenticated.return_value = authenticated
    if raise_exc is not None:
        client.secrets.kv.v2.read_secret_version.side_effect = raise_exc
    else:
        client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": data or {}}
        }
    return client


class TestVaultBootstrap:
    def test_missing_vault_addr_is_noop(self, clean_env):
        # No VAULT_ADDR, no VAULT_TOKEN — must not touch os.environ
        vault_bootstrap.populate_env_from_vault()
        assert "FTM_TEST_SECRET" not in os.environ

    def test_missing_vault_token_is_noop(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        vault_bootstrap.populate_env_from_vault()
        assert "FTM_TEST_SECRET" not in os.environ

    def test_auth_failure_is_noop(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "bad-token"
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(authenticated=False)
            vault_bootstrap.populate_env_from_vault()
        assert "FTM_TEST_SECRET" not in os.environ

    def test_successful_read_populates_env(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        # Use test-prefixed keys to avoid collisions with container env vars
        # (e.g. DATABASE_URL is set by docker-compose). The pre-existing-env
        # guard is covered separately by test_existing_env_not_overwritten.
        data = {"FTM_TEST_SECRET": "from-vault", "ftm_test_db_url": "postgres://x/y"}
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, data=data
            )
            vault_bootstrap.populate_env_from_vault()
        # Keys are uppercased when written to os.environ
        assert os.environ["FTM_TEST_SECRET"] == "from-vault"
        assert os.environ["FTM_TEST_DB_URL"] == "postgres://x/y"

    def test_existing_env_not_overwritten(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        os.environ["FTM_TEST_OVERRIDE"] = "from-shell"
        data = {"FTM_TEST_OVERRIDE": "from-vault"}
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, data=data
            )
            vault_bootstrap.populate_env_from_vault()
        # Pre-existing env must win over Vault — this is the local-dev escape hatch
        assert os.environ["FTM_TEST_OVERRIDE"] == "from-shell"

    def test_empty_values_are_skipped(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        data = {"FTM_TEST_EMPTY": "", "FTM_TEST_SECRET": "real"}
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, data=data
            )
            vault_bootstrap.populate_env_from_vault()
        assert "FTM_TEST_EMPTY" not in os.environ
        assert os.environ["FTM_TEST_SECRET"] == "real"

    def test_hvac_exception_is_caught(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, raise_exc=RuntimeError("vault down")
            )
            # Must not raise — startup failure here would be worse than missing secrets
            vault_bootstrap.populate_env_from_vault()
        assert "FTM_TEST_SECRET" not in os.environ

    def test_surrounding_quotes_are_stripped(self, clean_env):
        # Values in Vault sometimes come from `FOO="bar"` .env lines that
        # got rsplit as literal '"bar"'. Bootstrap must strip those quotes.
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        data = {
            "FTM_TEST_SECRET": '"double-quoted"',
            "FTM_TEST_DB_URL": "'single-quoted'",
            "FTM_TEST_OVERRIDE": "no-quotes",  # control
        }
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, data=data
            )
            vault_bootstrap.populate_env_from_vault()
        assert os.environ["FTM_TEST_SECRET"] == "double-quoted"
        assert os.environ["FTM_TEST_DB_URL"] == "single-quoted"
        assert os.environ["FTM_TEST_OVERRIDE"] == "no-quotes"

    def test_mismatched_quotes_are_preserved(self, clean_env):
        # Only strip when the quotes actually match (paranoid edge case).
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        data = {"FTM_TEST_SECRET": '"mismatched\''}
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_hvac.Client.return_value = _mock_hvac_client(
                authenticated=True, data=data
            )
            vault_bootstrap.populate_env_from_vault()
        assert os.environ["FTM_TEST_SECRET"] == '"mismatched\''

    def test_custom_vault_path_is_used(self, clean_env):
        os.environ["VAULT_ADDR"] = "http://vault.example:8200"
        os.environ["VAULT_TOKEN"] = "good-token"
        os.environ["VAULT_PATH"] = "family-task-manager/staging"
        os.environ["VAULT_MOUNT"] = "kv"
        data = {"FTM_TEST_SECRET": "ok"}
        with patch.object(vault_bootstrap, "hvac") as mock_hvac:
            mock_client = _mock_hvac_client(authenticated=True, data=data)
            mock_hvac.Client.return_value = mock_client
            vault_bootstrap.populate_env_from_vault()
            mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
                path="family-task-manager/staging", mount_point="kv"
            )
        assert os.environ["FTM_TEST_SECRET"] == "ok"
