# OpenCode Development Practices

**Purpose**: OpenCode-specific workflows and best practices for Family Task Manager

**Last Updated**: January 25, 2026

---

## 🔄 Standard Workflows

### Adding a New Feature

1. **Read Context**
   - Check `.github/memory-bank/activeContext.md` for current sprint
   - Review `.github/memory-bank/systemPatterns.md` for established patterns
   - Check relevant instruction file in `.github/instructions/`

2. **Plan Implementation**
   - Use OpenCode's TodoWrite tool to create task list
   - Break feature into: Model → Repository → Service → API → Tests
   - Estimate: 1 layer = 1 todo item

3. **Implement Layers (Bottom-Up)**
   ```
   1. Create/update Model (with family_id if multi-tenant)
   2. Create/update Repository methods (with family filtering)
   3. Create/update Service methods (business logic)
   4. Create/update API routes (HTTP layer)
   5. Write tests for each layer
   ```

4. **Test**
   ```bash
   # Run tests for the feature
   docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_[feature].py -v
   
   # Check coverage
   docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=term
   ```

5. **Validate Multi-Tenant Compliance**
   - Does model have `family_id`?
   - Do all repository methods accept `family_id` first parameter?
   - Do all queries filter by `family_id`?
   - Do tests verify tenant isolation?

6. **Commit**
   - Use conventional commit format
   - Example: `feat(tasks): add recurring task functionality`

---

### Fixing a Bug

1. **Reproduce**
   - Create a failing test first (TDD)
   - Document expected vs actual behavior

2. **Locate**
   - Use OpenCode's Grep tool to find relevant code
   - Check which layer has the bug (Model/Repository/Service/API)

3. **Fix**
   - Fix the bug in the appropriate layer
   - Ensure multi-tenant rules still apply
   - Update related tests

4. **Verify**
   ```bash
   # Run specific test
   docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_[module].py::test_[function] -v
   
   # Run all tests to check for regressions
   docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
   ```

5. **Commit**
   - Example: `fix(rewards): validate points before redemption`

---

### Refactoring Existing Code

1. **Document Current Behavior**
   - Write tests for existing behavior (if missing)
   - Ensure tests pass before refactoring

2. **Refactor**
   - Apply clean architecture patterns
   - Ensure multi-tenant compliance
   - Keep tests passing throughout

3. **Verify**
   - All tests still pass
   - Coverage maintained or improved
   - No behavioral changes

4. **Commit**
   - Example: `refactor(services): extract points calculation to separate method`

---

### Creating a Database Migration

1. **Make Model Changes**
   ```python
   # Update model in backend/app/models/
   class Task(Base):
       # Add new field
       priority: Mapped[str | None] = mapped_column(String(20))
   ```

2. **Generate Migration**
   ```bash
   docker exec family_app_backend alembic revision --autogenerate -m "add_priority_to_tasks"
   ```

3. **Review Migration**
   - Check `backend/migrations/versions/[timestamp]_add_priority_to_tasks.py`
   - Verify upgrade and downgrade functions
   - Ensure data integrity (defaults, nullability)

4. **Test Migration**
   ```bash
   # Apply migration
   docker exec family_app_backend alembic upgrade head
   
   # Verify schema
   docker exec -it family_app_db psql -U familyapp -d familyapp -c "\d tasks"
   
   # Test rollback
   docker exec family_app_backend alembic downgrade -1
   docker exec family_app_backend alembic upgrade head
   ```

5. **Update Tests**
   - Update test fixtures if needed
   - Update test assertions if schema changed

---

## ✅ Pre-Commit Checklist

Before committing code, verify:

- [ ] **Tests Written**: New code has corresponding tests
- [ ] **Tests Pass**: All 118+ tests passing
- [ ] **Coverage**: Maintained or improved (70%+ target)
- [ ] **Multi-Tenant Compliance**:
  - [ ] Models have `family_id` (if family-owned data)
  - [ ] Repository methods accept `family_id` first
  - [ ] All queries filter by `family_id`
  - [ ] Tests verify tenant isolation
- [ ] **Clean Architecture**:
  - [ ] API layer: HTTP concerns only
  - [ ] Service layer: Business logic only
  - [ ] Repository layer: Database queries only
- [ ] **Type Safety**:
  - [ ] Using `Mapped[]` syntax in models
  - [ ] Type hints on all methods
  - [ ] No SQLAlchemy Column type errors
- [ ] **Code Style**:
  - [ ] Follows PEP 8
  - [ ] Descriptive variable names
  - [ ] Docstrings on public methods

---

## 🚫 Common Mistakes

### 1. Forgetting Family ID in Queries

❌ **Wrong**:
```python
async def get_all_tasks(self) -> List[Task]:
    query = select(Task)  # No family filtering!
    result = await self.db.execute(query)
    return list(result.scalars().all())
```

✅ **Correct**:
```python
async def get_all_tasks(self, family_id: UUID) -> List[Task]:
    query = select(Task).where(Task.family_id == family_id)
    result = await self.db.execute(query)
    return list(result.scalars().all())
```

---

### 2. Business Logic in API Layer

❌ **Wrong**:
```python
@router.post("/{reward_id}/redeem")
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Business logic in API layer!
    reward = await db.get(Reward, reward_id)
    if current_user.points < reward.points_cost:
        raise HTTPException(status_code=400, detail="Insufficient points")
    current_user.points -= reward.points_cost
    await db.commit()
    return {"success": True}
```

✅ **Correct**:
```python
@router.post("/{reward_id}/redeem")
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    reward_service: RewardService = Depends(get_reward_service)
):
    # Delegate to service layer
    result = await reward_service.redeem_reward(
        family_id=current_user.family_id,
        user_id=current_user.id,
        reward_id=reward_id
    )
    return result
```

---

### 3. Missing Tenant Isolation Tests

❌ **Wrong**:
```python
async def test_create_task(task_service, test_family):
    task = await task_service.create_task(test_family, {"title": "Test"})
    assert task.title == "Test"
    # Missing: verification that other families can't see this task!
```

✅ **Correct**:
```python
async def test_create_task_isolated(
    task_service,
    test_family_1,
    test_family_2
):
    # Create task for family 1
    task = await task_service.create_task(test_family_1, {"title": "Test"})
    assert task.title == "Test"
    
    # Verify family 1 can see it
    tasks_f1 = await task_service.get_family_tasks(test_family_1)
    assert len(tasks_f1) == 1
    
    # CRITICAL: Verify family 2 cannot see it
    tasks_f2 = await task_service.get_family_tasks(test_family_2)
    assert len(tasks_f2) == 0
```

---

### 4. Not Using Type Hints

❌ **Wrong**:
```python
async def get_task(family_id, task_id):  # No type hints!
    query = select(Task).where(Task.id == task_id, Task.family_id == family_id)
    result = await self.db.execute(query)
    return result.scalar_one_or_none()
```

✅ **Correct**:
```python
async def get_task(self, family_id: UUID, task_id: UUID) -> Task | None:
    query = select(Task).where(
        Task.id == task_id,
        Task.family_id == family_id
    )
    result = await self.db.execute(query)
    return result.scalar_one_or_none()
```

---

## 🎯 Best Practices

### 1. Use Existing Patterns

Before writing new code, check:
- `.github/memory-bank/systemPatterns.md` for established patterns
- `backend/app/` for similar implementations
- `.github/instructions/` for detailed guides

### 2. Test-First Development

For new features:
1. Write failing test
2. Implement minimum code to pass
3. Refactor while keeping tests green

### 3. Commit Frequently

Small, focused commits are better than large commits:
- One logical change per commit
- Descriptive commit messages
- Tests passing before each commit

### 4. Document Decisions

When making architectural decisions:
- Update `.github/memory-bank/activeContext.md` (recent decisions)
- Update `.github/memory-bank/techContext.md` (technology choices)
- Add examples to `.github/memory-bank/systemPatterns.md`

### 5. Use OpenCode Tools Effectively

- **Glob**: Find files by pattern (faster than Grep for file names)
- **Grep**: Search code content (use for finding usage examples)
- **Read**: Read specific files (better than cat for long files)
- **Edit**: Make targeted edits (better than Write for existing files)
- **Task**: Delegate complex searches to exploration agent

---

## 🔗 Quick Reference

### Essential Files
- Architecture: `AGENTS.md`, `ARCHITECTURE.md`
- Current context: `.github/memory-bank/activeContext.md`
- Code patterns: `.github/memory-bank/systemPatterns.md`
- Multi-tenant guide: `.github/instructions/01-multi-tenant-patterns.md`
- Clean architecture: `.github/instructions/02-clean-architecture.md`
- Testing guide: `.github/instructions/04-testing-standards.md`

### Essential Commands
```bash
# Start services
docker-compose up -d

# Run tests
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run tests with coverage
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Database migration
docker exec family_app_backend alembic upgrade head

# Seed demo data
docker exec family_app_backend python /app/seed_data.py

# View logs
docker-compose logs -f backend
```

### Access Points
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs
- Database (prod): localhost:5433
- Database (test): localhost:5435
- Redis: localhost:6380

---

## 📊 Success Metrics

Track these metrics throughout development:

- **Test Coverage**: 70%+ (current: 74%)
- **Tests Passing**: 100% (current: 118/118)
- **Multi-Tenant Compliance**: 100% (verify with checklist)
- **Clean Architecture Violations**: 0 (verify with code review)
- **Type Hint Coverage**: 90%+ (verify with mypy)

---

**Remember**: When in doubt, follow existing patterns in the codebase. Consistency is more important than perfection.
