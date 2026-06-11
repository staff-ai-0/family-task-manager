"""Authenticated, family-scoped serving of uploaded proof images.

Replaces the previous ``app.mount("/uploads", StaticFiles(...))`` which served
every gig-proof / receipt image to anyone over the public Cloudflare tunnel with
no authentication. An image is only returned if the caller is authenticated AND
their family owns a record (gig claim or task assignment) referencing it.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.models.gig import GigClaim
from app.models.task_assignment import TaskAssignment

router = APIRouter()

UPLOADS_ROOT = "/app/uploads"
GIG_PROOFS_DIR = os.path.join(UPLOADS_ROOT, "gig-proofs")


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve a gig/task proof image, scoped to the caller's family."""
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

    path = os.path.join(GIG_PROOFS_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})
