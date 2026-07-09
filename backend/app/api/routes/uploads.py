"""Authenticated, family-scoped serving of uploaded proof images.

Replaces the previous ``app.mount("/uploads", StaticFiles(...))`` which served
every gig-proof / receipt image to anyone over the public Cloudflare tunnel with
no authentication. An image is only returned if the caller is authenticated AND
their family owns a record (gig claim or task assignment) referencing it.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.thumbnails import thumb_filename
from app.models import User
from app.models.gig import GigClaim
from app.models.task_assignment import TaskAssignment

router = APIRouter()

UPLOADS_ROOT = settings.UPLOADS_ROOT
GIG_PROOFS_DIR = os.path.join(UPLOADS_ROOT, "gig-proofs")

# UUID-named files are content-immutable — cache them for a year. Kept `private`
# because the bytes are family-scoped behind auth (must not land in shared caches).
_IMMUTABLE_CACHE = "private, max-age=31536000, immutable"


def _safe_filename(filename: str) -> str:
    """Reject anything that isn't a single path segment (no traversal)."""
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or filename.startswith(".")
        or filename in (".", "..")
    ):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return filename


@router.get("/uploads/gig-proofs/{filename}")
async def serve_gig_proof(
    filename: str,
    size: Optional[str] = Query(
        None,
        description="Pass `thumb` to serve the ~200px WebP thumbnail instead of "
        "the full image. Falls back to the full image if no thumb exists.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve a gig/task proof image, scoped to the caller's family.

    Family scoping is keyed off the ORIGINAL filename (the thumbnail is a
    server-side sibling that is never referenced by any DB row), so `?size=thumb`
    is exactly as authorized as the full image.
    """
    filename = _safe_filename(filename)
    url = f"/uploads/gig-proofs/{filename}"

    owned = (
        await db.execute(
            select(GigClaim.id)
            .where(
                GigClaim.proof_image_url == url,
                GigClaim.family_id == current_user.family_id,
            )
            .limit(1)
        )
    ).first()
    if owned is None:
        owned = (
            await db.execute(
                select(TaskAssignment.id)
                .where(
                    TaskAssignment.proof_image_url == url,
                    TaskAssignment.family_id == current_user.family_id,
                )
                .limit(1)
            )
        ).first()

    # 404 (not 403) when the file isn't owned — don't leak existence cross-family.
    if owned is None:
        raise HTTPException(status_code=404, detail="Not found")

    # When ?size=thumb is requested, serve the generated WebP sibling. Older
    # uploads (pre-thumbnail) or images whose thumb generation failed simply
    # have no thumb — fall back to the full original so nothing 404s.
    if size == "thumb":
        thumb_path = os.path.join(GIG_PROOFS_DIR, thumb_filename(filename))
        if os.path.isfile(thumb_path):
            return FileResponse(
                thumb_path,
                media_type="image/webp",
                headers={
                    "Cache-Control": _IMMUTABLE_CACHE,
                    "X-Content-Type-Options": "nosniff",
                },
            )

    path = os.path.join(GIG_PROOFS_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(
        path,
        headers={
            "Cache-Control": _IMMUTABLE_CACHE,
            # User-uploaded bytes: never let the browser sniff a different
            # (potentially active) content type out of an image response.
            "X-Content-Type-Options": "nosniff",
        },
    )
