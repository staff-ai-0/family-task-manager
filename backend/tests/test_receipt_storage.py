"""Receipt-image persistence must work without Google credentials.

Receipts were uploaded to GCS only, inside the scan path's best-effort
`except`. On the canonical on-prem deployment there are no Google credentials,
so every upload raised DefaultCredentialsError and every original image was
silently discarded (verified on prod: receipt scans recorded, zero transactions
carrying an image path). These tests pin the local backend and the
path-dispatched read/delete so that cannot regress.
"""
import os
from uuid import uuid4

import pytest

from app.services.storage.local_receipt_service import (
    LOCAL_PREFIX,
    LocalReceiptStorage,
)
from app.services.storage.receipt_storage import ReceiptStorage

JPEG = b"\xff\xd8\xff\xe0 fake jpeg bytes"


@pytest.fixture
def receipts_root(tmp_path, monkeypatch):
    """Point both the storage module and its config at a temp uploads root."""
    root = tmp_path / "uploads" / "receipts"
    monkeypatch.setattr(
        "app.services.storage.local_receipt_service.RECEIPTS_DIR", str(root)
    )
    return root


def test_local_upload_writes_file_and_returns_prefixed_key(receipts_root):
    family_id, txn_id = uuid4(), uuid4()

    path = LocalReceiptStorage.upload(
        family_id=family_id,
        transaction_id=txn_id,
        image_bytes=JPEG,
        content_type="image/jpeg",
    )

    assert path == f"{LOCAL_PREFIX}{family_id}/{txn_id}.jpg"
    on_disk = receipts_root / str(family_id) / f"{txn_id}.jpg"
    assert on_disk.read_bytes() == JPEG
    # No stray temp file from the write-then-rename.
    assert not (receipts_root / str(family_id) / f"{txn_id}.jpg.tmp").exists()


def test_local_round_trip_returns_bytes_and_content_type(receipts_root):
    path = LocalReceiptStorage.upload(
        family_id=uuid4(),
        transaction_id=uuid4(),
        image_bytes=JPEG,
        content_type="image/jpeg",
    )

    data, content_type = LocalReceiptStorage.download_bytes(path)
    assert data == JPEG
    assert content_type == "image/jpeg"


def test_pdf_receipts_keep_their_content_type(receipts_root):
    path = LocalReceiptStorage.upload(
        family_id=uuid4(),
        transaction_id=uuid4(),
        image_bytes=b"%PDF-1.4 fake",
        content_type="application/pdf",
    )

    _, content_type = LocalReceiptStorage.download_bytes(path)
    assert content_type == "application/pdf"


def test_delete_removes_file_and_prunes_family_dir(receipts_root):
    family_id = uuid4()
    path = LocalReceiptStorage.upload(
        family_id=family_id,
        transaction_id=uuid4(),
        image_bytes=JPEG,
        content_type="image/jpeg",
    )

    LocalReceiptStorage.delete(path)

    assert not (receipts_root / str(family_id)).exists()
    # Deleting again is a no-op, not an error (purge runs are best-effort).
    LocalReceiptStorage.delete(path)


def test_delete_keeps_family_dir_while_other_receipts_remain(receipts_root):
    family_id = uuid4()
    keep = LocalReceiptStorage.upload(
        family_id=family_id, transaction_id=uuid4(),
        image_bytes=JPEG, content_type="image/jpeg",
    )
    drop = LocalReceiptStorage.upload(
        family_id=family_id, transaction_id=uuid4(),
        image_bytes=JPEG, content_type="image/jpeg",
    )

    LocalReceiptStorage.delete(drop)

    assert LocalReceiptStorage.download_bytes(keep)[0] == JPEG


def test_key_escaping_the_uploads_root_is_refused(receipts_root):
    with pytest.raises(ValueError):
        LocalReceiptStorage.download_bytes(f"{LOCAL_PREFIX}../../etc/passwd")


def test_missing_file_raises_filenotfound(receipts_root):
    with pytest.raises(FileNotFoundError):
        LocalReceiptStorage.download_bytes(f"{LOCAL_PREFIX}{uuid4()}/{uuid4()}.jpg")


def test_router_defaults_to_local_backend(receipts_root, monkeypatch):
    """Default config must NOT reach for GCS — that is the prod data-loss bug."""
    monkeypatch.setattr(
        "app.services.storage.receipt_storage.settings.RECEIPT_STORAGE_BACKEND",
        "local",
    )

    def _explode(*_a, **_kw):
        raise AssertionError("GCS backend must not be used when backend=local")

    monkeypatch.setattr("app.services.storage.receipt_storage._gcs", _explode)

    path = ReceiptStorage.upload(
        family_id=uuid4(),
        transaction_id=uuid4(),
        image_bytes=JPEG,
        content_type="image/jpeg",
    )
    assert path.startswith(LOCAL_PREFIX)
    assert ReceiptStorage.download_bytes(path)[0] == JPEG


def test_router_reads_legacy_gcs_paths_regardless_of_backend(
    receipts_root, monkeypatch
):
    """Bare (unprefixed) keys are legacy GCS objects and must still route there."""
    seen = {}

    class _FakeGCS:
        @staticmethod
        def download_bytes(path):
            seen["path"] = path
            return b"gcs bytes", "image/png"

    monkeypatch.setattr(
        "app.services.storage.receipt_storage.settings.RECEIPT_STORAGE_BACKEND",
        "local",
    )
    monkeypatch.setattr(
        "app.services.storage.receipt_storage._gcs", lambda: _FakeGCS
    )

    data, content_type = ReceiptStorage.download_bytes("fam-uuid/txn-uuid.png")

    assert data == b"gcs bytes"
    assert content_type == "image/png"
    assert seen["path"] == "fam-uuid/txn-uuid.png"


def test_family_deletion_removes_local_receipts(receipts_root, monkeypatch):
    """A purged family's images must leave the disk, not just the DB."""
    from app.services.family_deletion_service import FamilyDeletionService

    family_id = uuid4()
    path = LocalReceiptStorage.upload(
        family_id=family_id,
        transaction_id=uuid4(),
        image_bytes=JPEG,
        content_type="image/jpeg",
    )
    monkeypatch.setattr(
        "app.services.storage.receipt_storage.settings.RECEIPT_STORAGE_BACKEND",
        "local",
    )

    removed = FamilyDeletionService._delete_receipt_images([path])

    assert removed == 1
    assert not (receipts_root / str(family_id)).exists()


def test_family_deletion_reports_unreachable_legacy_gcs_keys(monkeypatch, caplog):
    """Legacy GCS keys with no bucket configured must be logged, not counted."""
    from app.services.family_deletion_service import FamilyDeletionService

    monkeypatch.setattr(
        "app.services.family_deletion_service.settings.GCS_RECEIPT_BUCKET", ""
    )

    with caplog.at_level("WARNING"):
        removed = FamilyDeletionService._delete_receipt_images(["fam/txn.jpg"])

    assert removed == 0
    assert "NOT deleted" in caplog.text
