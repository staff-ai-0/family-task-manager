"""Backend-agnostic entry point for receipt-image persistence.

Historically receipts went to GCS only. That was correct on the decommissioned
GCP deployment and silently broken everywhere else: on the canonical on-prem
host there are no Google credentials, so `storage.Client()` raises
`DefaultCredentialsError` inside the scan path's best-effort `except` and every
original image is discarded (verified on prod: 15 receipt scans recorded, zero
transactions with a stored image path).

Selection rule — `RECEIPT_STORAGE_BACKEND`:

* ``local`` (the default): write to the uploads volume, which is already
  mounted and already covered by `scripts/backup-db.sh`.
* ``gcs``: use the bucket in ``GCS_RECEIPT_BUCKET``. Opt-in on purpose — a
  leftover bucket name in a `.env` must not be enough to route writes at a
  credential-less deployment.

Reads dispatch on the stored path itself, not on config, so objects written by
either backend stay readable after a backend switch: local paths carry a
``local:`` prefix, bare keys are legacy GCS objects.
"""

import logging
from uuid import UUID

from app.core.config import settings
from app.services.storage.local_receipt_service import (
    LOCAL_PREFIX,
    LocalReceiptStorage,
)

logger = logging.getLogger(__name__)


def _use_gcs() -> bool:
    return (settings.RECEIPT_STORAGE_BACKEND or "local").strip().lower() == "gcs"


def _gcs():
    from app.services.storage.gcs_receipt_service import GCSReceiptStorage

    return GCSReceiptStorage


class ReceiptStorage:
    """Routes receipt reads/writes to the configured backend."""

    @staticmethod
    def upload(
        *,
        family_id: UUID,
        transaction_id: UUID,
        image_bytes: bytes,
        content_type: str,
    ) -> str:
        backend = _gcs() if _use_gcs() else LocalReceiptStorage
        return backend.upload(
            family_id=family_id,
            transaction_id=transaction_id,
            image_bytes=image_bytes,
            content_type=content_type,
        )

    @staticmethod
    def download_bytes(path: str) -> tuple[bytes, str]:
        if path.startswith(LOCAL_PREFIX):
            return LocalReceiptStorage.download_bytes(path)
        return _gcs().download_bytes(path)

    @staticmethod
    def delete(path: str) -> None:
        if path.startswith(LOCAL_PREFIX):
            LocalReceiptStorage.delete(path)
            return
        _gcs().delete(path)
