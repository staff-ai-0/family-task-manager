# Family Task Manager - GitHub Documentation

**Repository**: Family Task Manager  
**Last Updated**: December 11, 2025

This directory contains all GitHub-specific documentation, instructions, and templates for the Family Task Manager project.

---

## 📚 Documentation Index

### Primary References

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **`copilot-instructions.md`** | Main instructions for GitHub Copilot | ⭐ **Always read first** - comprehensive project guide |
| **`instructions/01-backend-logic.instructions.md`** | Backend development guidelines | When creating services, models, or API endpoints |
| **`instructions/02-frontend-ui.instructions.md`** | Frontend/template guidelines | When building UI components or templates |

### Prompt Templates

| Template | Purpose | When to Use |
|----------|---------|-------------|
| **`prompts/new-api-endpoint.md`** | Create new FastAPI endpoints | Adding new API routes |
| **`prompts/new-model.md`** | Create new database models | Adding new tables or models |
| **`prompts/new-service.md`** | Create new service classes | Adding business logic layer |

### Memory Bank (Context Files)

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **`memory-bank/projectbrief.md`** | Project overview and requirements | Understanding project goals and features |
| **`memory-bank/techContext.md`** | Technical decisions and architecture | Understanding technology choices and patterns |

---

## 🚀 Quick Start for New Developers

### First Steps

1. **Read `copilot-instructions.md`** - Understand the project structure and standards
2. **Review `memory-bank/projectbrief.md`** - Learn about the business requirements
3. **Check `memory-bank/techContext.md`** - Understand technical architecture
4. **Follow setup instructions** in main `README.md`

### When Creating New Features

**For API Endpoints**:
1. Read `prompts/new-api-endpoint.md` template
2. Follow `instructions/01-backend-logic.instructions.md` guidelines
3. Create Pydantic schemas first
4. Implement service layer with business logic
5. Create endpoint with proper RBAC
6. Write tests

**For Database Models**:
1. Read `prompts/new-model.md` template
2. Define model structure and relationships
3. Create Alembic migration
4. Update relationships in related models
5. Write model tests

**For Frontend Components**:
1. Read `instructions/02-frontend-ui.instructions.md` guidelines
2. Use Flowbite components
3. Integrate with HTMX for dynamic updates
4. Add Alpine.js for interactivity
5. Test responsive design

---

## 📖 Documentation Structure

```
.github/
├── README.md                          # This file
├── copilot-instructions.md            # ⭐ Main Copilot instructions
├── instructions/
│   ├── 01-backend-logic.instructions.md    # Backend guidelines
│   └── 02-frontend-ui.instructions.md      # Frontend guidelines
├── prompts/
│   ├── new-api-endpoint.md            # API endpoint template
│   ├── new-model.md                   # Database model template
│   └── new-service.md                 # Service layer template
└── memory-bank/
    ├── projectbrief.md                # Project requirements
    └── techContext.md                 # Technical decisions
```

---

## 🎯 Core Concepts

### Project Overview

**Family Task Manager** is a gamified task organization application inspired by **OurHome**. It helps families manage daily tasks through:
- **Points-based rewards system**
- **Default (required) vs Extra (optional) tasks**
- **Consequence system for incomplete tasks**
- **Family-wide visibility and collaboration**

### Tech Stack

- **Backend**: FastAPI (Python 3.12+)
- **Database**: PostgreSQL + SQLAlchemy
- **Frontend**: Jinja2 + Flowbite (Tailwind CSS)
- **Interactivity**: HTMX + Alpine.js
- **Authentication**: JWT with bcrypt
- **Deployment**: Render

### Key Features

1. **Task Management**: Default and extra tasks with point values
2. **Points & Rewards**: Earn and redeem points for family-defined rewards
3. **Consequences**: Automatic restrictions for incomplete default tasks
4. **Family Management**: Multi-user with role-based access control

---

## 🏗️ Architecture Patterns

### Backend Layers

```
API Layer (routers/)
    ↓
Service Layer (services/)
    ↓
Model Layer (models/)
    ↓
Database (PostgreSQL)
```

### Frontend Pattern

```
Jinja2 Templates (templates/)
    ↓
HTMX (dynamic updates)
    ↓
Alpine.js (interactivity)
    ↓
Flowbite Components (UI)
```

### Database Design

**Core Tables**:
- `users` - Family members with roles (PARENT, CHILD, TEEN)
- `families` - Family groups
- `tasks` - Default and extra tasks
- `rewards` - Redeemable rewards catalog
- `consequences` - Active restrictions
- `point_transactions` - Audit log of all point changes

---

## 🔐 Security & Best Practices

### Always Required

1. **Authentication**: All endpoints except login/register require JWT
2. **Authorization**: Role-based access control (parents vs children)
3. **Family Isolation**: Users only access their family's data
4. **Input Validation**: Pydantic schemas for all inputs
5. **Password Security**: Bcrypt hashing, never plain text

### Code Quality Rules

**When making ANY code changes**:
- ✅ Remove unused imports and dead code
- ✅ Consolidate duplicate logic
- ✅ Update related documentation
- ✅ Add/update tests
- ✅ Run linters before committing

**When changing behavior**:
- ✅ Update `copilot-instructions.md` if needed
- ✅ Document breaking changes
- ✅ Update API documentation

---

## 🧪 Testing Guidelines

### Test Coverage Goals

- **Unit Tests**: 80%+ coverage for services and models
- **Integration Tests**: All API endpoints
- **E2E Tests**: Critical user flows (future)

### Test Patterns

```python
# Service layer tests
@pytest.mark.asyncio
async def test_service_method(db_session, test_user):
    result = await Service.method(data, db_session)
    assert result.field == expected_value

# API endpoint tests
@pytest.mark.asyncio
async def test_endpoint_success(client, auth_headers):
    response = await client.post("/api/endpoint", json=data, headers=auth_headers)
    assert response.status_code == 200
```

---

## 🚢 Deployment Workflow

### Development

```bash
# Local setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

### Production (Render)

1. Push to GitHub main branch
2. Render auto-deploys
3. Migrations run automatically
4. Monitor logs in Render dashboard

---

## 📝 Common Tasks

### Creating a New API Endpoint

```bash
# 1. Create Pydantic schemas
# app/schemas/[module].py

# 2. Implement service layer
# app/services/[module]_service.py

# 3. Create route handler
# app/api/routes/[module].py

# 4. Register router in main.py

# 5. Write tests
# tests/test_[module].py

# 6. Test with Swagger UI
# http://localhost:8000/docs
```

### Creating a New Database Model

```bash
# 1. Create model
# app/models/[name].py

# 2. Create migration
alembic revision --autogenerate -m "Add [name] table"

# 3. Review migration
# migrations/versions/[hash]_add_[name]_table.py

# 4. Apply migration
alembic upgrade head

# 5. Update relationships in related models

# 6. Write tests
# tests/test_models/test_[name].py
```

### Creating a New Frontend Component

```bash
# 1. Create Jinja2 template
# app/templates/[component].html

# 2. Use Flowbite components
# Reference: https://flowbite.com/docs/components/

# 3. Add HTMX for dynamic behavior
# hx-get, hx-post, hx-target, hx-swap

# 4. Add Alpine.js for interactivity
# x-data, x-show, x-bind, @click

# 5. Test responsive design
# Mobile, tablet, desktop breakpoints
```

---

## 🆘 Getting Help

### Resources

- **Copilot Instructions**: `.github/copilot-instructions.md`
- **Project Brief**: `.github/memory-bank/projectbrief.md`
- **Technical Context**: `.github/memory-bank/techContext.md`
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Flowbite Docs**: https://flowbite.com/docs/
- **HTMX Docs**: https://htmx.org/docs/

### Common Issues

**Database Connection Errors**:
- Check `DATABASE_URL` in `.env`
- Ensure PostgreSQL is running
- Run migrations: `alembic upgrade head`

**Authentication Issues**:
- Check `SECRET_KEY` in `.env`
- Verify JWT token in request headers
- Check token expiration (30 minutes)

**HTMX Not Working**:
- Verify endpoint returns HTML (not JSON)
- Check `hx-target` selector is correct
- Use browser DevTools Network tab to debug

---

## 📊 Project Status

**Current Phase**: MVP Development

**Completed**:
- ✅ Project structure and documentation
- ✅ GitHub Copilot instructions
- ✅ Technical architecture defined
- ✅ Prompt templates created

**In Progress**:
- 🚧 Core models and database schema
- 🚧 API endpoints implementation
- 🚧 Frontend templates

**Planned**:
- 📋 Authentication system
- 📋 Task management features
- 📋 Points and rewards system
- 📋 Consequence enforcement
- 📋 Deployment to Render

---

## 🔄 Maintaining This Documentation

### When to Update

**Update `copilot-instructions.md`** when:
- Adding new major features
- Changing core patterns
- Updating tech stack
- Discovering important lessons

**Update instruction files** when:
- Establishing new coding patterns
- Adding file-specific rules
- Changing best practices

**Update prompt templates** when:
- Refining feature creation process
- Adding new template types
- Improving code generation patterns

**Update memory bank** when:
- Project requirements change
- Technical decisions evolve
- Architecture patterns update

### Maintenance Checklist

- [ ] Review documentation monthly
- [ ] Remove outdated information
- [ ] Add new patterns and learnings
- [ ] Update examples with current code
- [ ] Verify links and references

---

**Created**: December 11, 2025  
**Maintained by**: Development Team  
**Next Review**: January 11, 2026
