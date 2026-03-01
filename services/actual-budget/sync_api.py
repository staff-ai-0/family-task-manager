#!/usr/bin/env python3
"""
Sync Service API - PostgreSQL Integration

FastAPI wrapper around the PostgreSQL sync.py script to provide HTTP endpoints
for triggering bidirectional synchronization.

This service runs as a separate container and can be called by the backend
or scheduled as a cron job.
"""
import os
import subprocess
from pathlib import Path
from typing import Literal, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import the PostgreSQL sync module
from sync_postgres import run_sync, get_sync_status

app = FastAPI(
    title="Family Finance Sync Service",
    description="PostgreSQL-based bidirectional sync between Family Task Manager and Budget",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
SYNC_SCRIPT_PATH = Path("/app/sync.py")


class SyncRequest(BaseModel):
    """Request model for sync trigger."""
    direction: Literal["both", "to_budget", "from_budget"] = "both"
    dry_run: bool = False
    family_id: str  # UUID as string


class SyncResponse(BaseModel):
    """Response model for sync operations."""
    status: str
    direction: str
    dry_run: bool
    results: dict
    error: str | None = None
    timestamp: str


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Family Finance Sync Service (PostgreSQL)",
        "version": "2.0.0",
        "backend": "PostgreSQL",
        "endpoints": {
            "health": "/health",
            "status": "/status?family_id=<uuid>",
            "trigger": "/trigger (POST)",
        }
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Verifies that sync module can be imported and executed.
    """
    checks = {
        "sync_script_exists": SYNC_SCRIPT_PATH.exists(),
        "postgres_sync_module": False,
    }
    
    # Try to import the sync module
    try:
        from sync_postgres import get_sync_status as test_import
        checks["postgres_sync_module"] = True
        checks["import_error"] = None
    except Exception as e:
        checks["import_error"] = str(e)
        checks["postgres_sync_module"] = False
    
    all_healthy = all([
        checks["sync_script_exists"],
        checks.get("postgres_sync_module", False),
    ])
    
    return {
        "healthy": all_healthy,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/status")
async def get_status(family_id: str = Query(..., description="Family UUID")):
    """
    Get current sync status for a specific family.
    
    Returns sync state including last sync time and transaction counts.
    """
    try:
        status = get_sync_status(family_id)
        return status
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sync status: {str(e)}"
        )


@app.post("/trigger", response_model=SyncResponse)
async def trigger_sync(request: SyncRequest):
    """
    Trigger a sync operation for a specific family.
    
    **Parameters**:
    - family_id: Family UUID
    - direction: Sync direction (both, to_budget, from_budget)
    - dry_run: Preview changes without applying them
    
    **Returns**: Sync result with status and statistics
    """
    try:
        # Run sync using the PostgreSQL module
        results = run_sync(
            family_id=request.family_id,
            direction=request.direction,
            dry_run=request.dry_run
        )
        
        return SyncResponse(
            status="success",
            direction=request.direction,
            dry_run=request.dry_run,
            results=results,
            timestamp=datetime.utcnow().isoformat(),
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}\n{error_detail}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5008)
