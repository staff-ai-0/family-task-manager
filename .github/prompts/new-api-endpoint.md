# Prompt Template: New FastAPI Endpoint

Use this template when creating new API endpoints for the Family Task Manager.

## Checklist

- [ ] Define clear endpoint purpose and HTTP method
- [ ] Create Pydantic request/response schemas
- [ ] Implement role-based access control (RBAC)
- [ ] Add input validation
- [ ] Implement business logic in service layer
- [ ] Add database transaction handling
- [ ] Include proper error handling
- [ ] Write unit and integration tests
- [ ] Update API documentation
- [ ] Test with HTMX if frontend integration is needed

## Template Structure

### 1. Define Route in `app/api/routes/[module].py`

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.dependencies import get_current_user, get_db, require_parent_role
from app.models.user import User
from app.schemas.[module] import [RequestSchema], [ResponseSchema]
from app.services.[module]_service import [ServiceClass]

router = APIRouter(prefix="/api/[resource]", tags=["[Resource]"])

@router.[method]("/[endpoint]")
async def [endpoint_name](
    # Path parameters
    resource_id: UUID,
    
    # Request body (for POST/PUT/PATCH)
    request: [RequestSchema],
    
    # Dependencies
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> [ResponseSchema]:
    """
    [Endpoint description]
    
    Args:
        resource_id: UUID of the resource
        request: Request payload
        current_user: Authenticated user
        db: Database session
    
    Returns:
        [ResponseSchema]: Response data
    
    Raises:
        HTTPException: [Error conditions]
    """
    try:
        # Business logic
        result = await [ServiceClass].[method_name](
            resource_id=resource_id,
            data=request,
            user_id=current_user.id,
            db=db
        )
        
        return [ResponseSchema](
            success=True,
            data=result,
            message="[Success message]"
        )
    
    except [CustomException] as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
```

### 2. Create Schemas in `app/schemas/[module].py`

```python
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from uuid import UUID

class [Resource]CreateRequest(BaseModel):
    """Request schema for creating a [resource]"""
    field1: str = Field(..., min_length=3, max_length=100)
    field2: int = Field(..., ge=1)
    
    @validator('field1')
    def validate_field1(cls, v):
        # Custom validation logic
        return v

class [Resource]UpdateRequest(BaseModel):
    """Request schema for updating a [resource]"""
    field1: Optional[str] = Field(None, max_length=100)
    field2: Optional[int] = Field(None, ge=1)

class [Resource]Response(BaseModel):
    """Response schema for [resource]"""
    id: UUID
    field1: str
    field2: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class [Resource]ListResponse(BaseModel):
    """Response schema for list of [resources]"""
    success: bool = True
    data: List[[Resource]Response]
    total: int
    message: Optional[str] = None
```

### 3. Implement Service in `app/services/[module]_service.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List

from app.models.[module] import [Model]
from app.schemas.[module] import [RequestSchema]
from app.core.exceptions import [CustomException]

class [ServiceClass]:
    """Service for [resource] business logic"""
    
    @staticmethod
    async def [method_name](
        resource_id: UUID,
        data: [RequestSchema],
        user_id: UUID,
        db: AsyncSession
    ) -> [Model]:
        """
        [Method description]
        
        Args:
            resource_id: Resource UUID
            data: Request data
            user_id: Current user ID
            db: Database session
        
        Returns:
            [Model]: Created/updated resource
        
        Raises:
            [CustomException]: [Error conditions]
        """
        # Validate permissions
        await validate_user_access(user_id, resource_id, db)
        
        # Business logic
        async with db.begin():
            # Database operations
            instance = [Model](**data.dict(), user_id=user_id)
            db.add(instance)
            await db.flush()
            await db.refresh(instance)
        
        return instance
```

### 4. Add Tests in `tests/test_[module].py`

```python
import pytest
from httpx import AsyncClient
from uuid import uuid4

@pytest.mark.asyncio
async def test_[endpoint_name]_success(client: AsyncClient, test_user, test_db):
    """Test successful [operation]"""
    # Setup
    payload = {
        "field1": "test value",
        "field2": 42
    }
    
    # Execute
    response = await client.[method](
        "/api/[resource]/[endpoint]",
        json=payload,
        headers={"Authorization": f"Bearer {test_user.token}"}
    )
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["field1"] == "test value"

@pytest.mark.asyncio
async def test_[endpoint_name]_unauthorized(client: AsyncClient):
    """Test endpoint requires authentication"""
    response = await client.[method]("/api/[resource]/[endpoint]")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_[endpoint_name]_validation_error(client: AsyncClient, test_user):
    """Test validation error handling"""
    payload = {"field1": ""}  # Invalid: too short
    
    response = await client.[method](
        "/api/[resource]/[endpoint]",
        json=payload,
        headers={"Authorization": f"Bearer {test_user.token}"}
    )
    
    assert response.status_code == 422
```

## Common Endpoint Patterns

### List Resources (GET)

```python
@router.get("/")
async def list_resources(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ResourceListResponse:
    """List all resources for current user's family"""
    resources = await ResourceService.list_by_family(
        family_id=current_user.family_id,
        skip=skip,
        limit=limit,
        db=db
    )
    
    return ResourceListResponse(
        success=True,
        data=resources,
        total=len(resources)
    )
```

### Get Single Resource (GET)

```python
@router.get("/{resource_id}")
async def get_resource(
    resource_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ResourceResponse:
    """Get a specific resource by ID"""
    resource = await ResourceService.get_by_id(resource_id, db)
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    # Verify user has access
    if resource.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return ResourceResponse(success=True, data=resource)
```

### Create Resource (POST)

```python
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_resource(
    request: ResourceCreateRequest,
    current_user: User = Depends(require_parent_role),  # Parents only
    db: AsyncSession = Depends(get_db)
) -> ResourceResponse:
    """Create a new resource (parents only)"""
    resource = await ResourceService.create(
        data=request,
        family_id=current_user.family_id,
        created_by=current_user.id,
        db=db
    )
    
    return ResourceResponse(
        success=True,
        data=resource,
        message="Resource created successfully"
    )
```

### Update Resource (PUT/PATCH)

```python
@router.patch("/{resource_id}")
async def update_resource(
    resource_id: UUID,
    request: ResourceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ResourceResponse:
    """Update a resource"""
    resource = await ResourceService.update(
        resource_id=resource_id,
        data=request,
        user_id=current_user.id,
        db=db
    )
    
    return ResourceResponse(
        success=True,
        data=resource,
        message="Resource updated successfully"
    )
```

### Delete Resource (DELETE)

```python
@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: UUID,
    current_user: User = Depends(require_parent_role),  # Parents only
    db: AsyncSession = Depends(get_db)
):
    """Delete a resource (parents only)"""
    await ResourceService.delete(
        resource_id=resource_id,
        user_id=current_user.id,
        db=db
    )
```

## HTMX Response Pattern

For endpoints that return HTML for HTMX:

```python
from fastapi.templating import Jinja2Templates
from fastapi import Request

templates = Jinja2Templates(directory="app/templates")

@router.patch("/{resource_id}/complete")
async def complete_resource(
    request: Request,
    resource_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Complete a resource (returns HTML for HTMX)"""
    resource = await ResourceService.complete(resource_id, current_user.id, db)
    
    # Return partial HTML template
    return templates.TemplateResponse(
        "partials/resource_card.html",
        {
            "request": request,
            "resource": resource,
            "user": current_user
        }
    )
```

---

**Created**: December 11, 2025
