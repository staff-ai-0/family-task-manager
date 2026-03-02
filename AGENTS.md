# Family Task Manager - AI Development Guide

**AI Tool**: OpenCode  
**Architecture**: Multi-tenant (Family-based isolation)  
**Tech Stack**: Python/FastAPI + Astro 5/Tailwind CSS v4  
**Phase**: 10 - Production Complete ✅  
**Status**: Live on https://family.agent-ia.mx

## Production Deployment (2026-03-01)

### Current Infrastructure
```
Frontend (Port 3003)         Backend API (Port 8002)
Astro 5 + Tailwind v4 ←→     FastAPI + SQLAlchemy
    ↓                              ↓
  Sessions                    PostgreSQL (Port 5437)
    ↓                              ↓
  Redis (Port 6380)          Test DB (Port 5435)
```

**Production Server**: 10.1.0.99 (TrueNAS)  
**Public URL**: https://family.agent-ia.mx (reverse proxy)  
**All services running and verified ✅**

### Deployment Commands

```bash
# SSH to production
ssh jc@10.1.0.99

# Navigate to project
cd /mnt/zfs-storage/home/jc/projects/family-task-manager

# View running containers
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Restart services
docker compose down
docker compose up -d backend frontend
```

## Setup Commands (Development)

### Start Development Environment
```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f frontend
```

### Run Tests
```bash
# Run all tests
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run with coverage (ensure 70%+ coverage)
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

### Budget API Operations
```bash
# View budget categories
curl -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/budget/categories

# View accounts
curl -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/budget/accounts

# View transactions
curl -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/budget/transactions

# View allocations
curl -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/budget/allocations
```

## Architecture Overview

### Multi-Tenant Architecture (Family-Based)

Every entity is scoped to a **family** for complete data isolation.

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

### Security Requirements (Production)

- **Auth Cookies**: MUST use `secure: true` and `httpOnly: true`
- **CSRF**: Middleware configured for `family.agent-ia.mx` origin
- **Backend Communication**: Frontend uses internal Docker URL `http://backend:8000` for SSR requests
- **Port Mapping**: External 3003→Internal 3000 (frontend), 8002→8000 (backend)

### Budget System (Phase 10)

**Status**: ✅ Fully migrated to PostgreSQL, Actual Budget service decommissioned

**Endpoints**:
- `/api/budget/categories` - Envelope budget categories
- `/api/budget/accounts` - Bank accounts (checking, savings, credit cards, investments)
- `/api/budget/transactions` - All financial transactions
- `/api/budget/allocations` - Monthly budget allocations
- `/api/budget/reports/*` - Spending analysis, cashflow, net worth

**Sync Service Deprecation** (Phase 10):
- All `/api/sync/*` endpoints return **410 Gone** status
- Deprecation message directs users to `/api/budget/*` endpoints
- No external Actual Budget dependency

**Components**:
- `backend/app/models/budget.py`: 7 database tables
- `backend/app/services/budget/`: Business logic services
- `backend/app/api/routes/budget/`: REST API endpoints
- `frontend/src/pages/budget/`: Budget management UI (12 pages)

## Access Points

### Production
- **Frontend**: https://family.agent-ia.mx
- **Backend API**: http://10.1.0.99:8002/docs
- **Health Check**: http://10.1.0.99:8002/health

### Development
- **Frontend**: http://localhost:3003
- **Backend API**: http://localhost:8002/docs
- **Database**: localhost:5437 (familyapp / familyapp123)
- **Redis**: localhost:6380
- **Test DB**: localhost:5435

### Demo Users
```
mom@demo.com / password123 (PARENT, 500 points)
dad@demo.com / password123 (PARENT, 300 points)
emma@demo.com / password123 (CHILD, 150 points)
lucas@demo.com / password123 (TEEN, 280 points)
```

## Development Flow

1. **Make Changes** → Edit code in `backend/app/` or `frontend/src/`
2. **Write Tests** → Add tests in `backend/tests/`
3. **Run Tests** → `docker exec family_app_backend pytest tests/` (must pass)
4. **Check Coverage** → Ensure 70%+ coverage
5. **Test Manually** → Visit http://localhost:3003
6. **Commit & Push** → Create PR with clear commit message

## Important Documentation Files

- `.github/copilot-instructions.md` - AI-specific development guidance
- `.github/instructions/05-multi-tenant-patterns.md` - Multi-tenant pattern implementations
- `.github/instructions/02-frontend-ui.instructions.md` - Frontend architecture
- `.github/instructions/04-python-type-safety.instructions.md` - Type safety standards
- `PRODUCTION_DEPLOYMENT_FINAL.md` - Complete deployment record (2026-03-01)
- `DOCKER_COMPOSE_CLEANUP.md` - Infrastructure cleanup record

## Removed / Obsolete

- ❌ Actual Budget sync service (Phase 10 decommissioned)
- ❌ `/services/actual-budget/` directory
- ❌ External Actual Budget dependencies
- ❌ `docker-compose.prod.yml` (PM2 setup)
- ❌ `docker-compose.prod.full.yml` (old port config)
- ❌ Sync-related memory-bank files

## Next Agent Should Know

1. **Production is live** - All changes should be tested locally before pushing to main
2. **Phase 10 complete** - No Actual Budget integration, use internal budget system only
3. **Multi-tenant strict** - ALL new entities must have `family_id` foreign key
4. **Port configuration** - Docker maps 3003→3000, 8002→8000 (important for debugging)
5. **Tests required** - All new code must have tests with 70%+ coverage
6. **Database migrations** - Always use alembic for schema changes, never direct SQL
7. **Clean architecture** - Follow routes→services→repositories→models pattern

