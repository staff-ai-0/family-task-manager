"""
Categorization Rule routes

CRUD endpoints for automatic transaction categorization rules.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.schemas.budget import (
    CategorizationRuleCreate,
    CategorizationRuleUpdate,
    CategorizationRuleResponse,
    CategorizationSuggestion,
)
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[CategorizationRuleResponse])
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    enabled_only: bool = Query(False, description="Only return enabled rules"),
):
    """List all categorization rules for the family"""
    family_id = to_uuid_required(current_user.family_id)
    rules = await CategorizationRuleService.list_rules(db, family_id, enabled_only=enabled_only)
    return rules


@router.post("/", response_model=CategorizationRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: CategorizationRuleCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new categorization rule (parent only)"""
    rule = await CategorizationRuleService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return rule


@router.get("/{rule_id}", response_model=CategorizationRuleResponse)
async def get_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a categorization rule by ID"""
    rule = await CategorizationRuleService.get_by_id(
        db,
        rule_id,
        to_uuid_required(current_user.family_id),
    )
    return rule


@router.put("/{rule_id}", response_model=CategorizationRuleResponse)
async def update_rule(
    rule_id: UUID,
    data: CategorizationRuleUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a categorization rule (parent only)"""
    rule = await CategorizationRuleService.update(
        db,
        rule_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a categorization rule (parent only)"""
    await CategorizationRuleService.delete_by_id(
        db,
        rule_id,
        to_uuid_required(current_user.family_id),
    )
    return None


@router.post("/suggest", response_model=Optional[CategorizationSuggestion])
async def suggest_category(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    payee: Optional[str] = Query(None, description="Payee name"),
    description: Optional[str] = Query(None, description="Transaction description"),
):
    """
    Get a suggested category for a transaction based on payee and/or description.
    
    Returns None if no rule matches.
    """
    family_id = to_uuid_required(current_user.family_id)
    category_id = await CategorizationRuleService.suggest_category(
        db,
        family_id,
        payee=payee,
        description=description,
    )
    
    if category_id is None:
        return None
    
    return CategorizationSuggestion(
        category_id=category_id,
        rule_id=None,  # We could look up the matching rule if needed
        confidence="medium",
    )
