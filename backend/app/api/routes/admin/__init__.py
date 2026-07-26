"""Cross-tenant operator surface.

Every route here is guarded by require_superadmin and takes family_id as an
explicit path parameter. Nothing in this package may use verify_family_id or
get_family_user — both compare against the caller's own family_id and would
reject every admin request.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import require_superadmin
from app.models.user import User

router = APIRouter()


@router.get("/ping")
async def ping(_operator: User = Depends(require_superadmin)) -> dict:
    """Liveness probe for the admin surface. Exists so the authorization
    matrix has a stable, side-effect-free target."""
    return {"ok": True}
