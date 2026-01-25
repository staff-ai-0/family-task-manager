# Family Task Manager - Architecture Documentation

## Overview

The Family Task Manager is built using a **decoupled microservices architecture** with separate backend and frontend services, allowing independent scaling, development, and deployment.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Docker Network                          │
│                        (app_network)                            │
│                                                                 │
│  ┌──────────────┐      ┌──────────────┐      ┌─────────────┐  │
│  │   Frontend   │────▶ │   Backend    │────▶ │ PostgreSQL  │  │
│  │   (Port 3000)│      │  (Port 8000) │      │ Production  │  │
│  │              │      │              │      │ (Port 5433) │  │
│  │  - Jinja2    │      │  - FastAPI   │      │             │  │
│  │  - Templates │      │  - REST API  │      └─────────────┘  │
│  │  - Sessions  │      │  - Business  │              │         │
│  └──────────────┘      │    Logic     │              │         │
│         │              └──────────────┘              │         │
│         │                     │                      │         │
│         │                     │                      │         │
│         │                     ▼                      │         │
│         │              ┌──────────────┐              │         │
│         │              │    Redis     │              │         │
│         │              │  (Port 6380) │              │         │
│         │              │              │              │         │
│         │              │  - Cache     │              │         │
│         │              │  - Sessions  │              │         │
│         │              └──────────────┘              │         │
│         │                                            │         │
│         │              ┌──────────────┐              │         │
│         └─────────────▶│ PostgreSQL   │◀─────────────┘         │
│                        │    Test      │                        │
│                        │ (Port 5435)  │                        │
│                        │              │                        │
│                        │ For Tests    │                        │
│                        └──────────────┘                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
         ▲                      ▲
         │                      │
    Port 3000               Port 8000
         │                      │
    ┌────┴──────────────────────┴────┐
    │         User Browser           │
    │  - http://localhost:3000       │
    │  - http://localhost:8000/docs  │
    └────────────────────────────────┘
```

---

## Service Architecture

### 1. Frontend Service (Port 3000)

**Technology Stack:**
- FastAPI (SSR - Server-Side Rendering)
- Jinja2 Templates
- Starlette Sessions
- Vanilla JavaScript (no framework)

**Responsibilities:**
- Render HTML pages using Jinja2 templates
- Handle user sessions (login state, cookies)
- Communicate with backend API via HTTP requests
- Serve static assets (CSS, JS, images)

**Key Files:**
```
frontend/
├── app/
│   ├── main.py              # FastAPI app for frontend
│   ├── views.py             # Route handlers & API communication
│   ├── config.py            # Frontend configuration
│   ├── templates/           # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   └── ...
│   └── static/
│       └── js/
│           ├── darkmode.js
│           └── translations.js
├── Dockerfile
└── requirements.txt
```

**Environment Variables:**
- `API_BASE_URL`: Backend API URL (default: `http://backend:8000`)
- `SECRET_KEY`: Session encryption key
- `DEBUG`: Enable debug mode
- `PORT`: Server port (default: 3000)

---

### 2. Backend Service (Port 8000)

**Technology Stack:**
- FastAPI (REST API)
- SQLAlchemy (async ORM)
- Alembic (database migrations)
- Pydantic (validation)
- JWT Authentication
- asyncpg (PostgreSQL driver)

**Responsibilities:**
- REST API endpoints for all business logic
- Database operations (CRUD)
- Authentication & authorization (JWT tokens)
- Business logic implementation
- Data validation
- Point transactions & calculations

**Key Files:**
```
backend/
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── api/
│   │   └── routes/                  # API endpoints
│   │       ├── auth.py              # /api/auth/*
│   │       ├── tasks.py             # /api/tasks/*
│   │       ├── rewards.py           # /api/rewards/*
│   │       ├── families.py          # /api/families/*
│   │       ├── users.py             # /api/users/*
│   │       └── consequences.py      # /api/consequences/*
│   ├── core/
│   │   ├── config.py                # App configuration
│   │   ├── database.py              # DB connection
│   │   ├── security.py              # JWT & password hashing
│   │   ├── dependencies.py          # FastAPI dependencies
│   │   ├── exceptions.py            # Custom exceptions
│   │   └── exception_handlers.py    # Error handlers
│   ├── models/                      # SQLAlchemy models
│   │   ├── user.py
│   │   ├── family.py
│   │   ├── task.py
│   │   ├── reward.py
│   │   ├── consequence.py
│   │   └── point_transaction.py
│   ├── schemas/                     # Pydantic schemas
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── reward.py
│   │   └── ...
│   └── services/                    # Business logic
│       ├── auth_service.py
│       ├── task_service.py
│       ├── reward_service.py
│       ├── family_service.py
│       ├── points_service.py
│       └── base_service.py
├── migrations/                      # Alembic migrations
├── tests/                           # Test suite (118 tests)
├── Dockerfile
└── requirements.txt
```

**Environment Variables:**
- `DATABASE_URL`: Production database URL
- `TEST_DATABASE_URL`: Test database URL
- `REDIS_URL`: Redis connection URL
- `SECRET_KEY`: App secret key
- `JWT_SECRET_KEY`: JWT signing key
- `DEBUG`: Enable debug mode
- `ALLOWED_ORIGINS`: CORS allowed origins

---

### 3. PostgreSQL Production Database (Port 5433)

**Purpose:** Store all application data

**Credentials:**
- Database: `familyapp`
- User: `familyapp`
- Password: `familyapp123`
- Host: `db` (internal) / `localhost` (external)
- Port: `5432` (internal) / `5433` (external)

**Schema:**
- `users` - User accounts and profiles
- `families` - Family groups
- `tasks` - Task definitions
- `rewards` - Available rewards
- `consequences` - Consequence rules
- `point_transactions` - Point history
- `password_reset_tokens` - Password reset tokens
- `email_verification_tokens` - Email verification tokens

**Healthcheck:**
```bash
pg_isready -U familyapp
```

---

### 4. PostgreSQL Test Database (Port 5435)

**Purpose:** Isolated database for running tests

**Credentials:**
- Database: `familyapp_test`
- User: `familyapp_test`
- Password: `familyapp_test123`
- Host: `test_db` (internal) / `localhost` (external)
- Port: `5432` (internal) / `5435` (external)

**Characteristics:**
- Separate volume from production database
- Automatically created/dropped tables per test
- Contains backup of production data for integration tests
- Isolated from production data

---

### 5. Redis Cache (Port 6380)

**Purpose:** Session storage and caching

**Host:** `redis` (internal) / `localhost` (external)
**Port:** `6379` (internal) / `6380` (external)

**Used For:**
- Session data storage
- Rate limiting (future)
- Caching frequently accessed data (future)

---

## Communication Flow

### 1. User Login Flow

```
User Browser
    │
    │ POST /login (email, password)
    ▼
Frontend Service (Port 3000)
    │
    │ POST /api/auth/login
    ▼
Backend Service (Port 8000)
    │
    │ 1. Validate credentials
    │ 2. Query database
    ▼
PostgreSQL Database
    │
    │ User found
    ▼
Backend Service
    │
    │ 3. Generate JWT token
    │ 4. Return token + user data
    ▼
Frontend Service
    │
    │ 5. Store token in session
    │ 6. Set session cookie
    │ 7. Redirect to dashboard
    ▼
User Browser
    │
    │ Cookie stored
    │ GET /dashboard
    ▼
Frontend Service
    │
    │ 1. Check session
    │ 2. GET /api/users/me (with token)
    ▼
Backend Service
    │
    │ 3. Validate JWT token
    │ 4. Return user data
    ▼
Frontend Service
    │
    │ 5. Render dashboard with data
    ▼
User Browser (Dashboard displayed)
```

### 2. Task Completion Flow

```
User clicks "Complete Task"
    │
    ▼
Frontend JavaScript
    │
    │ POST /tasks/{task_id}/complete
    ▼
Frontend Service
    │
    │ POST /api/tasks/{task_id}/complete
    │ (with JWT token from session)
    ▼
Backend Service
    │
    │ 1. Verify JWT token
    │ 2. Check user permissions
    │ 3. Update task status
    ▼
PostgreSQL Database
    │
    │ Task marked complete
    ▼
Backend Service
    │
    │ 4. Award points to user
    │ 5. Create point transaction
    ▼
PostgreSQL Database
    │
    │ Points added, transaction logged
    ▼
Backend Service
    │
    │ 6. Return updated task + points
    ▼
Frontend Service
    │
    │ 7. Return JSON response
    ▼
Frontend JavaScript
    │
    │ 8. Update UI (task state, points)
    ▼
User sees updated task and points
```

---

## Data Models

### User
- `id` (UUID, primary key)
- `email` (unique)
- `name`
- `role` (PARENT, CHILD, TEEN)
- `family_id` (foreign key)
- `points` (integer)
- `password_hash`
- `is_active` (boolean)
- Timestamps: `created_at`, `updated_at`

### Family
- `id` (UUID, primary key)
- `name`
- `created_by` (user_id, nullable)
- Timestamps: `created_at`, `updated_at`

### Task
- `id` (UUID, primary key)
- `title`
- `description`
- `points`
- `family_id` (foreign key)
- `assigned_to` (user_id, foreign key)
- `status` (PENDING, IN_PROGRESS, COMPLETED, CANCELLED)
- `is_default` (boolean)
- `frequency` (ONE_TIME, DAILY, WEEKLY, MONTHLY)
- `due_date` (datetime, nullable)
- `completed_at` (datetime, nullable)
- Timestamps: `created_at`, `updated_at`

### Reward
- `id` (UUID, primary key)
- `name`
- `description`
- `points_cost`
- `family_id` (foreign key)
- `category` (PRIVILEGE, ITEM, ACTIVITY, OTHER)
- `is_active` (boolean)
- Timestamps: `created_at`, `updated_at`

### Consequence
- `id` (UUID, primary key)
- `name`
- `description`
- `family_id` (foreign key)
- `user_id` (foreign key)
- `task_id` (foreign key, nullable)
- `severity` (LOW, MEDIUM, HIGH)
- `restriction_type` (SCREEN_TIME, PRIVILEGE, ACTIVITY, OTHER)
- `is_active` (boolean)
- `start_date`, `end_date`
- Timestamps: `created_at`, `updated_at`

### PointTransaction
- `id` (UUID, primary key)
- `user_id` (foreign key)
- `amount` (integer, can be negative)
- `transaction_type` (TASK_COMPLETION, REWARD_REDEMPTION, PARENT_ADJUSTMENT, CONSEQUENCE, TRANSFER)
- `task_id` (foreign key, nullable)
- `reward_id` (foreign key, nullable)
- `from_user_id` (foreign key, nullable)
- `reason` (text, nullable)
- Timestamp: `created_at`

---

## Authentication & Authorization

### JWT Token Structure
```json
{
  "sub": "user_uuid",
  "exp": 1234567890,
  "role": "PARENT",
  "family_id": "family_uuid"
}
```

### Session Storage
- Frontend stores JWT token in server-side session
- Session encrypted with `SECRET_KEY`
- Session cookie: `session` (httpOnly, secure in production)

### Permission Levels

**PARENT Role:**
- Full access to family data
- Create/edit/delete tasks
- Create/edit/delete rewards
- Create/edit/delete consequences
- Award/deduct points manually
- Manage family members

**TEEN Role:**
- View own tasks and family tasks
- Complete own tasks
- View and redeem rewards
- View own points history
- Limited family visibility

**CHILD Role:**
- View own tasks
- Complete own tasks
- View rewards (can't redeem without parent approval)
- View own points
- No family management

---

## Testing Strategy

### Test Database Setup
- Separate test database on port 5435
- Schema automatically created/dropped per test
- Tests run in isolated transactions
- Production data backup available for integration tests

### Test Execution
```bash
# Run all tests (118 tests)
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run specific test file
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth.py -v

# Run with coverage report
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html
```

### Test Coverage
- **Current:** 74% overall coverage
- **Target:** 70% minimum (met!)
- **Covered areas:**
  - Auth service: 100%
  - Family service: 100%
  - Task service: 100%
  - Points service: 84%
  - Reward service: 68%

### Test Structure
```
backend/tests/
├── conftest.py                    # Pytest fixtures
├── test_auth.py                   # Auth endpoints
├── test_auth_service.py           # Auth business logic
├── test_base_service.py           # Base service utilities
├── test_family_service.py         # Family CRUD
├── test_points_service.py         # Points logic
├── test_points_transfers.py       # Point transfers
├── test_rewards.py                # Reward endpoints
├── test_task_service.py           # Task business logic
└── test_tasks.py                  # Task endpoints
```

---

## Deployment with Docker

### Starting Services

```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Stop services
docker-compose down

# Rebuild and restart
docker-compose up -d --build
```

### Service Dependencies

Services start in order:
1. `db` (Production database) - waits for healthcheck
2. `test_db` (Test database) - waits for healthcheck
3. `redis` (Cache) - waits for healthcheck
4. `backend` (API) - waits for all databases + redis
5. `frontend` (Web UI) - waits for backend

### Healthchecks

All services have healthchecks configured:
- **PostgreSQL:** `pg_isready` every 10s
- **Redis:** `redis-cli ping` every 10s
- **Backend:** HTTP `/health` endpoint (future)
- **Frontend:** HTTP `/health` endpoint (implemented)

---

## Database Migrations

### Using Alembic

```bash
# Create new migration
docker exec family_app_backend alembic revision --autogenerate -m "description"

# Apply migrations
docker exec family_app_backend alembic upgrade head

# Rollback one version
docker exec family_app_backend alembic downgrade -1

# View migration history
docker exec family_app_backend alembic history

# Check current version
docker exec family_app_backend alembic current
```

### Migration Files
```
backend/migrations/versions/
├── 2025_12_12_0801-c89db4e73129_initial_schema.py
├── 2025_12_12_0803-22b45677041a_make_family_created_by_nullable.py
├── 2025_12_12_0811-079b00e9dddc_add_oauth_and_email_verification.py
├── 2025_12_12_0811-fab16872eb7e_add_email_verification_tokens_table.py
└── 2025_12_12_0815-8d23a3796561_add_password_reset_tokens_table.py
```

---

## Seeding Demo Data

```bash
# Seed production database with demo data
docker exec family_app_backend python /app/seed_data.py

# Demo users created:
# - mom@demo.com (PARENT, 500 points)
# - dad@demo.com (PARENT, 300 points)
# - emma@demo.com (CHILD, 150 points)
# - lucas@demo.com (TEEN, 280 points)
# Password for all: password123
```

---

## API Documentation

### Interactive API Docs

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### API Endpoints

**Authentication (`/api/auth`)**
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token
- `POST /api/auth/logout` - Logout (clear session)
- `GET /api/auth/me` - Get current user

**Tasks (`/api/tasks`)**
- `GET /api/tasks` - List tasks (with filters)
- `POST /api/tasks` - Create task
- `GET /api/tasks/{id}` - Get task details
- `PATCH /api/tasks/{id}` - Update task
- `DELETE /api/tasks/{id}` - Delete task
- `POST /api/tasks/{id}/complete` - Mark complete

**Rewards (`/api/rewards`)**
- `GET /api/rewards` - List rewards
- `POST /api/rewards` - Create reward
- `GET /api/rewards/{id}` - Get reward details
- `PATCH /api/rewards/{id}` - Update reward
- `DELETE /api/rewards/{id}` - Delete reward
- `POST /api/rewards/{id}/redeem` - Redeem reward

**Families (`/api/families`)**
- `GET /api/families/{id}` - Get family details
- `PATCH /api/families/{id}` - Update family
- `GET /api/families/{id}/members` - List members
- `GET /api/families/{id}/stats` - Family statistics

**Users (`/api/users`)**
- `GET /api/users/me` - Get current user
- `PATCH /api/users/me` - Update profile
- `GET /api/users/{id}` - Get user (family members only)

**Consequences (`/api/consequences`)**
- `GET /api/consequences` - List consequences
- `POST /api/consequences` - Create consequence
- `GET /api/consequences/{id}` - Get consequence
- `PATCH /api/consequences/{id}` - Update consequence
- `DELETE /api/consequences/{id}` - Delete consequence

---

## Environment Configuration

### Production (.env)

```bash
# Backend
DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp
TEST_DATABASE_URL=postgresql+asyncpg://familyapp_test:familyapp_test123@test_db:5432/familyapp_test
REDIS_URL=redis://redis:6379/0
SECRET_KEY=your-super-secret-key-change-in-production
JWT_SECRET_KEY=your-jwt-secret-key-change-in-production
DEBUG=False
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com

# Frontend
API_BASE_URL=http://backend:8000
PORT=3000
```

### Development Overrides

- `DEBUG=True` - Enable debug mode
- `DATABASE_URL=...@localhost:5433/...` - Connect from host machine
- `API_BASE_URL=http://localhost:8000` - Frontend connects to local backend

---

## Monitoring & Logs

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Database Access
```bash
# Production database
docker exec -it family_app_db psql -U familyapp -d familyapp

# Test database
docker exec -it family_app_test_db psql -U familyapp_test -d familyapp_test

# Common queries
SELECT COUNT(*) FROM users;
SELECT * FROM tasks WHERE status = 'PENDING';
SELECT * FROM point_transactions ORDER BY created_at DESC LIMIT 10;
```

### Redis Access
```bash
# Connect to Redis CLI
docker exec -it family_app_redis redis-cli

# Common commands
KEYS *
GET session:xxxxx
FLUSHDB  # Clear all data (careful!)
```

---

## Security Considerations

### Implemented
- Password hashing with bcrypt
- JWT token authentication
- CORS protection
- SQL injection prevention (SQLAlchemy parameterized queries)
- XSS prevention (Jinja2 auto-escaping)
- Session encryption
- Environment variable secrets

### Future Enhancements
- Rate limiting on authentication endpoints
- HTTPS in production (via reverse proxy)
- CSRF protection for state-changing operations
- API key authentication for external integrations
- Audit logging for sensitive operations
- Email verification for new accounts
- 2FA support

---

## Performance Optimization

### Current Optimizations
- Async database operations (asyncpg)
- Connection pooling (SQLAlchemy)
- Redis for session storage
- Indexed database columns (id, email, family_id)
- Lazy loading of relationships

### Future Optimizations
- Redis caching for frequently accessed data
- Query optimization (N+1 problem prevention)
- Background task processing (Celery)
- CDN for static assets
- Database read replicas
- Horizontal scaling of backend service

---

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Find process using port
lsof -i :8000
lsof -i :3000

# Kill process
kill -9 <PID>
```

**Database connection failed:**
```bash
# Check database is running
docker-compose ps db

# Check database logs
docker-compose logs db

# Restart database
docker-compose restart db
```

**Tests failing with connection errors:**
```bash
# Verify TEST_DATABASE_URL is set
docker exec family_app_backend env | grep TEST_DATABASE_URL

# Recreate backend container
docker-compose up -d --force-recreate backend
```

**Frontend can't connect to backend:**
```bash
# Check backend is running
curl http://localhost:8000/health

# Check API_BASE_URL
docker exec family_app_frontend env | grep API_BASE_URL

# Check Docker network
docker network inspect family-task-manager_app_network
```

---

## Future Architecture Considerations

### Potential Enhancements

1. **Message Queue (RabbitMQ/Redis Queue)**
   - Async task processing (email notifications)
   - Scheduled tasks (overdue task checks)
   - Background jobs (data exports)

2. **Microservices Split**
   - Points service → separate microservice
   - Notification service → separate microservice
   - Analytics service → separate microservice

3. **Frontend Framework**
   - Consider React/Vue/Svelte for richer interactions
   - Keep SSR for SEO and initial load performance

4. **Real-time Updates**
   - WebSocket support for live updates
   - Server-Sent Events for notifications

5. **Mobile App**
   - React Native or Flutter
   - Shared backend API

---

## Contributing

### Development Workflow

1. Create feature branch from `main`
2. Make changes in isolated branch
3. Run tests: `docker exec family_app_backend pytest tests/`
4. Ensure 70%+ test coverage
5. Commit with conventional commits format
6. Merge to `main` with `--no-ff`

### Code Standards

- **Python:** Follow PEP 8, use Black formatter
- **Async:** Use async/await for all I/O operations
- **Type Hints:** Use type annotations
- **Documentation:** Docstrings for all public functions
- **Tests:** Write tests for new features

---

## Resources

- **FastAPI Documentation:** https://fastapi.tiangolo.com/
- **SQLAlchemy Documentation:** https://docs.sqlalchemy.org/
- **Docker Compose Documentation:** https://docs.docker.com/compose/
- **Jinja2 Documentation:** https://jinja.palletsprojects.com/

---

**Last Updated:** January 25, 2026
**Version:** 2.0 (Decoupled Architecture)
