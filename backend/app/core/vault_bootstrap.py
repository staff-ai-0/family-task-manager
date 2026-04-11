"""
Vault bootstrap: fold KV v2 secrets into os.environ before pydantic Settings
is instantiated. Called once at import time of app.core.config.

Design choice — why bootstrap into os.environ instead of a runtime get() API
(like medical-omnichannel does via vault_config.py):

- Zero changes to the existing pydantic BaseSettings model: every field just
  picks its value from the environment the way it always did.
- Shell-env and .env still work unchanged for local development — any value
  already in os.environ is NOT overwritten, so `EXPORT FOO=bar && uvicorn ...`
  still beats whatever is in Vault. That's the local-dev escape hatch.
- Vault becomes optional: if VAULT_ADDR / VAULT_TOKEN are missing, or hvac
  isn't installed, or Vault is unreachable, we log and continue. .env is
  still the fallback.

Vault path + mount can be overridden via VAULT_PATH and VAULT_MOUNT env vars,
defaulting to `secret/family-task-manager/prod`.
"""

from __future__ import annotations

import logging
import os

try:
    import hvac  # type: ignore
except ImportError:  # pragma: no cover — covered by the missing-hvac path
    hvac = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def populate_env_from_vault() -> None:
    """Load Vault KV v2 data into os.environ, without overwriting existing keys."""
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    vault_path = os.getenv("VAULT_PATH", "family-task-manager/prod")
    vault_mount = os.getenv("VAULT_MOUNT", "secret")

    if not vault_addr or not vault_token:
        logger.info(
            "Vault not configured (VAULT_ADDR/VAULT_TOKEN missing), using .env only"
        )
        return

    if hvac is None:
        logger.warning("hvac not installed — cannot read from Vault, using .env only")
        return

    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            logger.warning(
                f"Vault authentication failed at {vault_addr}, using .env fallback"
            )
            return

        response = client.secrets.kv.v2.read_secret_version(
            path=vault_path, mount_point=vault_mount
        )
        data = response["data"]["data"]
    except Exception as e:
        logger.warning(
            f"Failed to load secrets from Vault ({vault_mount}/{vault_path}): {e} "
            "— using .env fallback"
        )
        return

    loaded = 0
    skipped_existing = 0
    skipped_empty = 0
    for key, value in data.items():
        upper_key = key.upper()
        if upper_key in os.environ:
            skipped_existing += 1
            continue
        if value is None or value == "":
            skipped_empty += 1
            continue
        os.environ[upper_key] = str(value)
        loaded += 1

    logger.info(
        f"Vault loaded: {loaded} secrets from {vault_mount}/{vault_path} "
        f"(skipped {skipped_existing} pre-existing, {skipped_empty} empty)"
    )
