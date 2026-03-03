"""
Family Invitation Routes

Handles sending, accepting, and managing family member invitations.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role, verify_family_id
from app.core.config import settings
from app.core.type_utils import to_uuid_required
from app.core.security import create_access_token
from app.services.invitation_service import InvitationService
from app.schemas.invitation import (
    SendFamilyInvitationRequest,
    InvitationResponse,
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    PendingInvitationResponse,
)
from app.models import User, FamilyInvitation

router = APIRouter()


@router.post("/send", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def send_invitation(
    request_data: SendFamilyInvitationRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a family invitation to an email address (parent only).
    
    Args:
        request_data: Email and family_id to invite to
        current_user: Current authenticated parent user
        db: Database session
        
    Returns:
        Created invitation details
    """
    # Verify family_id matches current user's family
    family_id = to_uuid_required(request_data.family_id)
    if family_id != current_user.family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to invite to this family"
        )
    
    try:
        invitation = await InvitationService.send_invitation(
            db=db,
            family_id=family_id,
            invited_email=request_data.email,
            inviting_user=current_user,
            role=request_data.role,
            base_url=settings.BASE_URL,
        )
        return invitation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{family_id}/pending", response_model=list[PendingInvitationResponse])
async def get_pending_invitations(
    family_id: UUID = Depends(verify_family_id),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all pending invitations for a family (parent only).
    
    Args:
        family_id: Family ID
        current_user: Current authenticated parent user
        db: Database session
        
    Returns:
        List of pending invitations
    """
    invitations = await InvitationService.get_pending_invitations(db, family_id)
    
    # Enrich with invited_by_user_name
    results = []
    for inv in invitations:
        from sqlalchemy import select
        invited_by = (await db.execute(
            select(User).where(User.id == inv.invited_by_user_id)
        )).scalar_one_or_none()
        
        results.append(PendingInvitationResponse(
            id=inv.id,
            invited_email=inv.invited_email,
            status=inv.status.value,
            role=inv.role.value if hasattr(inv.role, 'value') else inv.role,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            invited_by_user_name=invited_by.name if invited_by else "Unknown",
        ))
    
    return results


@router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    request_data: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a family invitation and create/login user account.
    
    Args:
        request_data: Invitation code, password, and name
        db: Database session
        
    Returns:
        Access token and user info
    """
    try:
        invitation, user = await InvitationService.accept_invitation(
            db=db,
            invitation_code=request_data.invitation_code,
            user_name=request_data.name,
            user_password=request_data.password,
        )
        
        # Create access token
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "family_id": str(user.family_id),
                "role": user.role.value,
            }
        )
        
        await db.commit()
        
        return AcceptInvitationResponse(
            success=True,
            access_token=access_token,
            token_type="bearer",
            message=f"Welcome to the family!"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{family_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    family_id: UUID = Depends(verify_family_id),
    invitation_id: UUID = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a pending invitation (parent only).
    
    Args:
        family_id: Family ID
        invitation_id: Invitation to cancel
        current_user: Current authenticated parent user
        db: Database session
    """
    if invitation_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invitation_id required"
        )
    
    try:
        await InvitationService.cancel_invitation(db, invitation_id, family_id)
        await db.commit()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
