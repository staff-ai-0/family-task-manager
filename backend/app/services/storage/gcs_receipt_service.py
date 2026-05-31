"""Receipt image persistence in Google Cloud Storage.

Bucket lifecycle (set externally): 30d → Nearline, 365d → Archive.
VM service account has roles/storage.objectAdmin on the bucket; no key files.
"""

import logging
from datetime import timedelta
from typing import Optional
from uuid import UUID

from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError

from app.core.config import settings

logger = logging.getLogger(__name__)


class GCSReceiptStorage:
    """Thin wrapper around the GCS client for receipt images.

    Object key: <family_id>/<txn_id>.<ext>. The family prefix makes it
    trivial to delete all receipts for a family on account removal.
    """

    _client: Optional[storage.Client] = None

    @classmethod
    def _bucket(cls):
        if cls._client is None:
            cls._client = storage.Client()
        if not settings.GCS_RECEIPT_BUCKET:
            raise RuntimeError("GCS_RECEIPT_BUCKET is not configured")
        return cls._client.bucket(settings.GCS_RECEIPT_BUCKET)

    @staticmethod
    def _ext_for(content_type: str) -> str:
        return {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
            "application/pdf": "pdf",
        }.get(content_type, "bin")

    @classmethod
    def upload(
        cls,
        *,
        family_id: UUID,
        transaction_id: UUID,
        image_bytes: bytes,
        content_type: str,
    ) -> str:
        """Upload bytes and return the object path (key) used in the bucket."""
        ext = cls._ext_for(content_type)
        path = f"{family_id}/{transaction_id}.{ext}"
        blob = cls._bucket().blob(path)
        blob.cache_control = "private, max-age=900"
        try:
            blob.upload_from_string(image_bytes, content_type=content_type)
        except GoogleCloudError as exc:
            logger.exception("GCS upload failed for %s", path)
            raise
        return path

    @classmethod
    def signed_url(cls, path: str, *, expires_in_seconds: int = 900) -> str:
        """Generate a v4 signed URL the browser can GET directly."""
        blob = cls._bucket().blob(path)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in_seconds),
            method="GET",
        )

    @classmethod
    def delete(cls, path: str) -> None:
        try:
            cls._bucket().blob(path).delete()
        except GoogleCloudError:
            logger.warning("GCS delete failed for %s (already gone?)", path)
