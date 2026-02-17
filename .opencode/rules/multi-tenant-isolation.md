# Multi-Tenant Isolation Rule

## Rule ID: multi-tenant-001

## Priority: CRITICAL

## Trigger
This rule activates when:
- Creating or modifying models in `backend/app/models/`
- Creating or modifying repositories in `backend/app/repositories/`
- Creating or modifying services in `backend/app/services/`
- Creating or modifying API routes in `backend/app/api/`

## Requirements

### For Models
Every model that stores family-specific data MUST:
1. Have a `family_id: Mapped[UUID]` column
2. `family_id` must be NOT NULL
3. `family_id` must have an index for performance
4. `family_id` must have a foreign key to `families.id`

```python
# CORRECT
class Task(Base):
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
```

### For Repositories
Every repository method that queries family data MUST:
1. Accept `family_id: UUID` as the FIRST parameter
2. Filter ALL queries by `family_id`
3. Include `family_id` check even in `get_by_id` methods

```python
# CORRECT
async def get_by_id(self, family_id: UUID, task_id: UUID) -> Task | None:
    query = select(Task).where(
        Task.id == task_id,
        Task.family_id == family_id  # Security check
    )
```

### For Services
Every service method that handles family data MUST:
1. Accept `family_id: UUID` as the first parameter
2. Pass `family_id` to repository methods
3. Validate family context in business logic

### For API Routes
Every API endpoint MUST:
1. Extract `family_id` from `current_user.family_id`
2. NEVER accept `family_id` as a path or query parameter
3. Pass extracted `family_id` to service layer

```python
# CORRECT
@router.get("/")
async def get_tasks(
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    return await task_service.get_family_tasks(
        family_id=current_user.family_id  # From auth, not request
    )
```

## Validation
Before committing, verify:
- [ ] New models have `family_id` (if family-owned data)
- [ ] Repository methods filter by `family_id`
- [ ] Service methods accept `family_id` first
- [ ] API routes never accept `family_id` from client
- [ ] Tests verify tenant isolation

## Reference
See `.github/instructions/05-multi-tenant-patterns.md` for complete patterns.
