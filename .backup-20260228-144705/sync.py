"""
Sync API Routes

Endpoints for manually triggering bidirectional sync between
Family Task Manager and Actual Budget.

This is a proxy to the dedicated sync service.
"""
import httpx
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

from app.models.user import User
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/sync", tags=["Sync"])

# Sync service URL (docker network)
SYNC_SERVICE_URL = "http://sync-service:5008"


def get_current_parent(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure user is a parent."""
    if current_user.role != "parent":
        raise HTTPException(status_code=403, detail="Only parents can trigger sync")
    return current_user


@router.post("/trigger")
async def trigger_sync(
    direction: Literal["both", "to_actual", "from_actual"] = "both",
    dry_run: bool = False,
    current_user: User = Depends(get_current_parent),
):
    """
    Manually trigger bidirectional sync.
    
    **Requires**: Parent role
    
    **Parameters**:
    - direction: Sync direction (both, to_actual, from_actual)
    - dry_run: Preview changes without applying them
    
    **Returns**: Sync result with status and output
    """
    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            response = await client.post(
                f"{SYNC_SERVICE_URL}/trigger",
                json={
                    "direction": direction,
                    "dry_run": dry_run,
                    "family_id": str(current_user.family_id),
                }
            )
            
            if response.status_code == 504:
                raise HTTPException(
                    status_code=504,
                    detail="Sync operation timed out"
                )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Sync service error: {response.text}"
                )
            
            result = response.json()
            result["triggered_by"] = current_user.email
            
            return result
            
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Sync service is unavailable"
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Sync operation timed out after 2 minutes"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger sync: {str(e)}"
        )


@router.get("/status")
async def get_sync_status(current_user: User = Depends(get_current_user)):
    """
    Get current sync status.
    
    **Returns**: Sync state including last sync time and transaction counts
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SYNC_SERVICE_URL}/status",
                params={"family_id": str(current_user.family_id)}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Sync service error: {response.text}"
                )
            
            return response.json()
            
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Sync service is unavailable"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sync status: {str(e)}"
        )


@router.get("/health")
async def check_sync_health():
    """
    Health check for sync service.
    
    Verifies that sync service is accessible and healthy.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{SYNC_SERVICE_URL}/health")
            
            if response.status_code != 200:
                return {
                    "healthy": False,
                    "error": f"Sync service returned status {response.status_code}",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            
            result = response.json()
            result["sync_service_url"] = SYNC_SERVICE_URL
            
            return result
            
    except httpx.ConnectError:
        return {
            "healthy": False,
            "error": "Cannot connect to sync service",
            "sync_service_url": SYNC_SERVICE_URL,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
