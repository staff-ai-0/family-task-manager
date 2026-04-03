"""
Budget export/import routes

Endpoints for exporting and importing budget data as ZIP archives.
"""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.export_service import ExportService
from app.models import User

router = APIRouter()


@router.get("/export")
async def export_budget(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Export all budget data as a ZIP file (parent only).

    Returns a downloadable ZIP containing budget_data.json and metadata.json.
    """
    family_id = to_uuid_required(current_user.family_id)
    zip_bytes = await ExportService.export_budget(db, family_id)

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=budget_export.zip"},
    )


@router.post("/import-backup")
async def import_budget_backup(
    file: UploadFile = File(..., description="ZIP file from budget export"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Import budget data from a ZIP backup (parent only).

    WARNING: This clears all existing budget data for the family before importing.

    Returns import statistics with counts per entity type.
    """
    family_id = to_uuid_required(current_user.family_id)
    zip_bytes = await file.read()
    stats = await ExportService.import_budget(db, family_id, zip_bytes)
    return {"success": True, "stats": stats}
