#!/usr/bin/env python3
"""
Sync Service API

FastAPI wrapper around the sync.py script to provide HTTP endpoints
for triggering bidirectional synchronization.

This service runs as a separate container and can be called by the backend
or scheduled as a cron job.
"""
import os
import subprocess
import json
from pathlib import Path
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(
    title="Family Finance Sync Service",
    description="Bidirectional sync between Family Task Manager and Actual Budget",
    version="1.0.0",
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
SYNC_STATE_PATH = Path("/app/sync_state.json")

# Database configuration (from environment)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "familyapp")
DB_USER = os.getenv("DB_USER", "familyapp")
DB_PASSWORD = os.getenv("DB_PASSWORD", "familyapp_prod_2026")


def get_family_budget_config(family_id: str) -> dict:
    """
    Query database to get family's Actual Budget configuration.
    
    Returns:
        dict with 'file_id' and 'sync_enabled' keys
        
    Raises:
        HTTPException if family not found or sync not enabled
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT actual_budget_file_id, actual_budget_sync_enabled 
                FROM families 
                WHERE id = %s
                """,
                (family_id,)
            )
            family = cur.fetchone()
            
            if not family:
                raise HTTPException(
                    status_code=404,
                    detail=f"Family {family_id} not found"
                )
            
            if not family['actual_budget_sync_enabled']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Actual Budget sync is not enabled for this family"
                )
            
            if not family['actual_budget_file_id']:
                raise HTTPException(
                    status_code=400,
                    detail=f"No Actual Budget file ID configured for this family"
                )
            
            return {
                'file_id': family['actual_budget_file_id'],
                'sync_enabled': family['actual_budget_sync_enabled'],
            }
            
    except psycopg2.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    finally:
        if conn:
            conn.close()


class SyncRequest(BaseModel):
    """Request model for sync trigger."""
    direction: Literal["both", "to_actual", "from_actual"] = "both"
    dry_run: bool = False
    family_id: str  # UUID as string


class SyncResponse(BaseModel):
    """Response model for sync operations."""
    status: str
    direction: str
    dry_run: bool
    output: str
    error: str | None = None
    timestamp: str


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Family Finance Sync Service",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "status": "/status",
            "trigger": "/trigger (POST)",
        }
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Verifies that sync script exists and can be executed.
    """
    checks = {
        "sync_script_exists": SYNC_SCRIPT_PATH.exists(),
        "sync_state_exists": SYNC_STATE_PATH.exists(),
    }
    
    # Try to run sync status command
    try:
        result = subprocess.run(
            ["python3", str(SYNC_SCRIPT_PATH), "--status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        checks["can_execute_sync_script"] = result.returncode == 0
        checks["sync_output"] = result.stdout[:200] if result.stdout else None
    except Exception as e:
        checks["can_execute_sync_script"] = False
        checks["error"] = str(e)
    
    all_healthy = all([
        checks["sync_script_exists"],
        checks.get("can_execute_sync_script", False),
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
    # Validate family exists and has sync enabled
    family_config = get_family_budget_config(family_id)
    
    # Use family-specific state file
    family_state_path = Path(f"/app/sync_state_{family_id}.json")
    
    if not family_state_path.exists():
        return {
            "family_id": family_id,
            "last_sync": None,
            "synced_members": {},
            "synced_to_actual_count": 0,
            "synced_from_actual_count": 0,
            "message": "No sync has been performed yet for this family"
        }
    
    try:
        with open(family_state_path, 'r') as f:
            state = json.load(f)
        
        return {
            "family_id": family_id,
            "last_sync": state.get("last_sync"),
            "synced_members": state.get("synced_members", {}),
            "synced_to_actual_count": len(state.get("synced_to_actual", {})),
            "synced_from_actual_count": len(state.get("synced_from_actual", {})),
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read sync state: {str(e)}"
        )


@app.post("/trigger", response_model=SyncResponse)
async def trigger_sync(request: SyncRequest):
    """
    Trigger a sync operation for a specific family.
    
    **Parameters**:
    - family_id: Family UUID
    - direction: Sync direction (both, to_actual, from_actual)
    - dry_run: Preview changes without applying them
    
    **Returns**: Sync result with status and output
    """
    if not SYNC_SCRIPT_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Sync script not found at {SYNC_SCRIPT_PATH}"
        )
    
    # Get family's Actual Budget configuration from database
    family_config = get_family_budget_config(request.family_id)
    budget_file_id = family_config['file_id']
    
    # Build command
    cmd = [
        "python3",
        str(SYNC_SCRIPT_PATH),
        f"--direction={request.direction}",
        f"--family-id={request.family_id}",
        f"--budget-file-id={budget_file_id}",
    ]
    
    if request.dry_run:
        cmd.append("--dry-run")
    
    try:
        # Run sync script
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )
        
        success = result.returncode == 0
        
        return SyncResponse(
            status="success" if success else "error",
            direction=request.direction,
            dry_run=request.dry_run,
            output=result.stdout,
            error=result.stderr if not success else None,
            timestamp=datetime.utcnow().isoformat(),
        )
        
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Sync operation timed out after 2 minutes"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute sync: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5008)
