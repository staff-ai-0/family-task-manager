"""Receipt image persistence on the local uploads volume.

Mirrors the GCSReceiptStorage interface so the two are interchangeable behind
`ReceiptStorage`. Files live under ``<UPLOADS_ROOT>/receipts/<family_id>/`` —
the same volume as gig proofs and receipt drafts, which `scripts/backup-db.sh`
already archives.
"""

import glob
import logging
import os
import tempfile
from typing import Optional
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

RECEIPTS_DIR = os.path.join(settings.UPLOADS_ROOT, "receipts")

# Stored in BudgetTransaction.receipt_image_path so the read path can tell a
# local object from a legacy GCS object key (which carries no prefix).
LOCAL_PREFIX = "local:"

_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
}
_TYPE_BY_EXT = {v: k for k, v in _EXT_BY_TYPE.items()}


class LocalReceiptStorage:
    """Filesystem-backed receipt images, keyed ``<family_id>/<txn_id>.<ext>``."""

    @staticmethod
    def _ext_for(content_type: str) -> str:
        return _EXT_BY_TYPE.get(content_type, "bin")

    @staticmethod
    def _resolve(key: str) -> str:
        """Absolute path for a storage key, refusing anything outside RECEIPTS_DIR.

        The key is derived from UUIDs we generate, never from user input, but
        this stays defensive because the value round-trips through the DB.
        """
        root = os.path.realpath(RECEIPTS_DIR)
        path = os.path.realpath(os.path.join(root, key))
        if path != root and not path.startswith(root + os.sep):
            raise ValueError(f"receipt key escapes the uploads root: {key!r}")
        return path

    @classmethod
    def upload(
        cls,
        *,
        family_id: UUID,
        transaction_id: UUID,
        image_bytes: bytes,
        content_type: str,
    ) -> str:
        """Write bytes and return the prefixed path stored on the transaction."""
        key = f"{family_id}/{transaction_id}.{cls._ext_for(content_type)}"
        dest = cls._resolve(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a truncated image
        # that later reads would serve as a valid (but corrupt) receipt. The
        # temp name is unique (two scans can target the same transaction id via
        # the dedup upgrade path) and is unlinked on failure, so a failed write
        # cannot strand receipt bytes that would then survive a family purge.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(image_bytes)
            os.replace(tmp, dest)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return f"{LOCAL_PREFIX}{key}"

    @classmethod
    def download_bytes(cls, path: str) -> tuple[bytes, str]:
        """Return (data, content_type) for a stored receipt."""
        key = path[len(LOCAL_PREFIX):] if path.startswith(LOCAL_PREFIX) else path
        src = cls._resolve(key)
        with open(src, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(src)[1].lstrip(".").lower()
        return data, _TYPE_BY_EXT.get(ext, "application/octet-stream")

    @classmethod
    def delete(cls, path: str) -> None:
        key = path[len(LOCAL_PREFIX):] if path.startswith(LOCAL_PREFIX) else path
        try:
            target = cls._resolve(key)
        except ValueError:
            logger.warning("refusing to delete out-of-root receipt key %s", path)
            return
        try:
            os.remove(target)
        except FileNotFoundError:
            pass
        # Any other OSError propagates: the purge caller counts only what it
        # could actually delete, and a receipt it failed to remove must not be
        # reported as gone.

        # Drop the family directory once its last receipt is gone. Reap stray
        # .tmp files first — an interrupted write could otherwise keep the
        # directory (and real receipt bytes) alive past a family purge.
        parent: Optional[str] = os.path.dirname(target)
        if parent and os.path.realpath(parent) != os.path.realpath(RECEIPTS_DIR):
            for stray in glob.glob(os.path.join(parent, "*.tmp")):
                try:
                    os.unlink(stray)
                except OSError:
                    pass
            try:
                os.rmdir(parent)
            except OSError:
                pass
