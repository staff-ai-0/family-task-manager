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
Frontend (Port 3000)        Backend API (Port 8000)
Astro 5 + Tailwind v4 ←→    FastAPI + SQLAlchemy
    ↓                              ↓
  Sessions                    PostgreSQL (Port 5433)
    ↓                              ↓
  Redis (Port 6380)          Test DB (Port 5435)
```

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
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/docs
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

**Phase**: Active Development  
**Current Sprint**: Adding AI support and improving DDD/CQRS patterns

See `.github/memory-bank/activeContext.md` for current tasks and blockers.
