# Testing Standards Rule

## Rule ID: testing-001

## Priority: HIGH

## Trigger
This rule activates when:
- Creating new features
- Modifying existing code
- Fixing bugs
- Before committing any changes

## Requirements

### Coverage Target
- Minimum: **70%** test coverage (current: 74%)
- All tests must pass before commit
- Currently: **118 tests** passing

### Test Commands
```bash
# Run all tests
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run with coverage
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Run specific test file
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_[module].py -v

# Run specific test
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_[module].py::test_[function] -v
```

### Tenant Isolation Tests (MANDATORY)
Every feature that creates family-specific data MUST have tests that verify:

1. **Data visibility to owning family**
2. **Data NOT visible to other families**
3. **Direct access denied from other families**

```python
# MANDATORY TEST PATTERN
@pytest.mark.asyncio
async def test_[feature]_tenant_isolation(
    service,
    test_family_1: UUID,
    test_family_2: UUID
):
    # Create data for family 1
    item = await service.create(test_family_1, {...})
    
    # VERIFY: Family 1 can see it
    items_f1 = await service.list(test_family_1)
    assert len(items_f1) == 1
    
    # CRITICAL: Family 2 CANNOT see it
    items_f2 = await service.list(test_family_2)
    assert len(items_f2) == 0
    
    # CRITICAL: Direct access from family 2 fails
    item_wrong = await service.get(test_family_2, item.id)
    assert item_wrong is None
```

### Test Categories

| Category | Coverage Target | Current |
|----------|-----------------|---------|
| Authentication | 100% | 100% |
| Task Management | 100% | 100% |
| Points System | 90% | 84% |
| Rewards | 80% | 68% |
| Family Management | 100% | 100% |

### Pre-Commit Checklist
- [ ] All 118+ tests pass
- [ ] Coverage maintained at 70%+
- [ ] New feature has corresponding tests
- [ ] Tenant isolation tests included
- [ ] No `@pytest.mark.skip` without reason

## Reference
See `.github/memory-bank/opencode-practices.md` for development workflows.
