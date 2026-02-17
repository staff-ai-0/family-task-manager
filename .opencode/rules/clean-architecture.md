# Clean Architecture Rule

## Rule ID: clean-arch-001

## Priority: HIGH

## Trigger
This rule activates when:
- Creating new code in `backend/app/`
- Modifying existing service, repository, or API code
- Refactoring business logic

## Architecture Layers

```
API Layer (backend/app/api/routes/)
    ↓ HTTP Request/Response only
Service Layer (backend/app/services/)
    ↓ Business logic, validation, orchestration
Repository Layer (backend/app/repositories/)
    ↓ Database queries only
Models Layer (backend/app/models/)
```

## Requirements

### API Layer (`backend/app/api/routes/`)
MUST only handle:
- HTTP request parsing
- Response formatting
- Authentication injection
- Exception to HTTP status mapping

MUST NOT contain:
- Business logic
- Direct database queries
- Complex validation beyond schema validation

```python
# CORRECT - Delegates to service
@router.post("/{reward_id}/redeem")
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    reward_service: RewardService = Depends(get_reward_service)
):
    return await reward_service.redeem_reward(
        family_id=current_user.family_id,
        user_id=current_user.id,
        reward_id=reward_id
    )

# WRONG - Business logic in API layer
@router.post("/{reward_id}/redeem")
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # DON'T DO THIS - business logic belongs in service
    reward = await db.get(Reward, reward_id)
    if current_user.points < reward.points_cost:
        raise HTTPException(status_code=400, detail="Insufficient points")
    current_user.points -= reward.points_cost
    await db.commit()
```

### Service Layer (`backend/app/services/`)
MUST handle:
- Business rules and validation
- Orchestration of multiple operations
- Domain logic
- Calling repositories for data

MUST NOT contain:
- Direct SQLAlchemy queries (use repository)
- HTTP-specific code (status codes, headers)

### Repository Layer (`backend/app/repositories/`)
MUST handle:
- Database queries
- Data persistence
- Query optimization

MUST NOT contain:
- Business logic
- External service calls
- Authorization checks (done in service)

## Validation Checklist
- [ ] API routes only call service methods
- [ ] Services contain all business logic
- [ ] Repositories only have database operations
- [ ] No direct `db.execute()` in API routes

## Reference
See `.github/memory-bank/systemPatterns.md` for complete examples.
