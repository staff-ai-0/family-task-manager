# Family Task Manager - AI Development Guide

**AI Tool**: OpenCode  
**Architecture**: Multi-tenant (Family-based isolation)  
**Tech Stack**: Python/FastAPI + Astro 5/Tailwind CSS v4  
**Phase**: Active Development  

## Setup Commands

### Start Development Environment
```bash
# Start all services with Docker Compose
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f sync-service
```

### Run Tests
```bash
# Run all tests (118 tests)
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run with coverage
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html
```

### Database Operations
```bash
# Run migrations
docker exec family_app_backend alembic upgrade head

# Create new migration
docker exec family_app_backend alembic revision --autogenerate -m "description"

# Seed demo data
docker exec family_app_backend python /app/seed_data.py
```

### Sync Operations
```bash
# Check sync service health
curl http://localhost:5008/health

# Get sync status (requires family_id)
curl "http://localhost:5008/status?family_id=ce875133-1b85-4bfc-8e61-b52309381f0b"

# Trigger manual sync
curl -X POST http://localhost:5008/trigger \
  -H "Content-Type: application/json" \
  -d '{"family_id":"ce875133-1b85-4bfc-8e61-b52309381f0b","direction":"both","dry_run":false}'
```

### Budget Operations
```bash
# Migrate data from Actual Budget (one-time)
docker exec family_app_backend python /app/scripts/migrate_actual_to_postgres.py

# Test budget API
curl -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/budget/categories

# Run sync test
docker exec family_sync_service python3 /app/test_sync.py
```

## Architectural Overview

### Multi-Tenant Architecture (Family-Based)

Every entity in the system is scoped to a **family** to ensure complete data isolation between families.

```python
# CRITICAL: All models with family data MUST have family_id
class Task(Base):
    __tablename__ = "tasks"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("families.id"), nullable=False)
    title: Mapped[str]
    points: Mapped[int]
    # ... other fields
```

### Clean Architecture Layers

```
API Layer (Routes)
    ↓ HTTP Request/Response only
Service Layer (Business Logic)
    ↓ Domain rules, validations
Repository Layer (Data Access)
    ↓ Database queries
Models (Database Entities)
```

### Decoupled Services Architecture

```
Frontend (Port 3003)        Backend API (Port 8002)
Astro 5 + Tailwind v4 ←→    FastAPI + SQLAlchemy
    ↓                              ↓
  Sessions                    PostgreSQL (Port 5433)
    ↓                              ↓
  Redis (Port 6380)          Test DB (Port 5435)
    
Sync Service (Port 5008)    
PostgreSQL-based Budget Sync
    ↓                              
  Hourly Cron Job           
```

### Budget System Architecture

The **Budget System** is fully integrated with PostgreSQL:

**Components:**
- `backend/app/models/budget.py`: Budget database models (7 tables)
- `backend/app/services/budget/`: Business logic services
- `backend/app/api/routes/budget/`: REST API endpoints
- `frontend/src/pages/budget/`: Budget management UI
- `services/actual-budget/sync_postgres.py`: PostgreSQL-based sync (600+ lines)

**Key Features:**
- **Envelope Budgeting**: Monthly allocations per category
- **Multi-Account Support**: Checking, savings, credit cards, investments
- **Transaction Management**: Income, expenses, transfers
- **Reporting**: Spending analysis, cashflow, net worth
- **Reconciliation**: Match bank statements
- **Multi-Tenant**: Proper family isolation

## AI Instructions

See `.github/copilot-instructions.md` for detailed instructions.

For specific patterns:
- Multi-tenant patterns: `.github/instructions/01-multi-tenant-patterns.md`
- Clean architecture: `.github/instructions/02-clean-architecture.md`
- DDD patterns: `.github/instructions/03-domain-driven-design.md`
- Testing standards: `.github/instructions/04-testing-standards.md`
- API conventions: `.github/instructions/05-api-conventions.md`

## Quick Start

### Access Points
- **Frontend**: http://localhost:3003
- **Backend API**: http://localhost:8002/docs
- **Sync Service**: http://localhost:5008 (health check)
- **Budget UI**: http://localhost:3003/budget
- **Database**: localhost:5433 (production), localhost:5435 (test)
- **Redis**: localhost:6380

### Demo Users
```
mom@demo.com / password123 (PARENT, 500 points)
dad@demo.com / password123 (PARENT, 300 points)
emma@demo.com / password123 (CHILD, 150 points)
lucas@demo.com / password123 (TEEN, 280 points)
```

### Essential Development Flow

1. **Make Changes** → Edit code in `backend/app/` or `frontend/src/`
2. **Write Tests** → Add tests in `backend/tests/`
3. **Run Tests** → `docker exec family_app_backend pytest tests/`
4. **Check Coverage** → Ensure 70%+ coverage
5. **Test Manually** → Visit http://localhost:3000

## Current Development Focus

**Phase**: Migration Complete ✅  
**Latest**: PostgreSQL-based budget system with full CRUD

**Recently Completed:**
- ✅ Complete budget system migration to PostgreSQL
- ✅ Full CRUD API for categories, accounts, transactions, allocations
- ✅ Budget management UI under `/budget/*` (12 pages)
- ✅ Inline budget editing in month view
- ✅ Reconciliation workflow
- ✅ Reporting dashboards (spending, cashflow, net worth)
- ✅ PostgreSQL-based sync service
- ✅ Removed Actual Budget and finance-api dependencies

**Active Work:**
- Production deployment and testing
- User training and documentation
- Performance monitoring

See `MIGRATION_GUIDE.md` for complete migration details.
