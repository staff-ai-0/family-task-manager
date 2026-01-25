# Family Task Manager 🏡

**Gamified family task organization with rewards and consequences**

Inspired by **OurHome**, this application helps families organize daily tasks through a points-based reward system, making chores engaging for children while giving parents oversight and control.

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- PostgreSQL (handled by Docker)

### Setup with Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/family-task-manager.git
cd family-task-manager

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env and set your SECRET_KEY
# Generate a secure key with: openssl rand -hex 32

# 4. Build and start services
docker-compose up -d

# 5. Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### Local Development Setup

```bash
# 1. Create virtual environment (in backend/)
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment variables
cp ../.env.example ../.env
# Edit .env with your configuration

# 4. Start PostgreSQL with Docker
cd ..
docker-compose up -d db test_db

# 5. Run migrations
cd backend
alembic upgrade head

# 6. Seed demo data (optional)
python seed_data.py

# 7. Start development server
uvicorn app.main:app --reload --port 8000
```

---

## 📖 Documentation

- **[AGENTS.md](./AGENTS.md)** - AI Development Guide (OpenCode)
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Multi-tenant architecture & patterns
- **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Deployment procedures
- **`.github/copilot-instructions.md`** - Complete project guide
- **`.github/instructions/`** - Development patterns & standards
- **`.github/memory-bank/`** - Project context & active development

---

## 🏗️ Project Structure

```
family-task-manager/
├── backend/                    # Backend API service
│   ├── app/
│   │   ├── main.py            # FastAPI application entry point
│   │   ├── api/               # API endpoints
│   │   ├── core/              # Configuration, database, security
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   └── services/          # Business logic layer
│   ├── tests/                 # Comprehensive test suite (118 tests)
│   ├── migrations/            # Alembic database migrations
│   ├── seed_data.py           # Demo data seeder
│   └── requirements.txt       # Python dependencies
├── frontend/                  # Frontend web service
│   ├── app/
│   │   ├── main.py            # Frontend server
│   │   ├── templates/         # Jinja2 HTML templates
│   │   └── static/            # CSS, JS, images (Flowbite)
│   └── requirements.txt       # Frontend dependencies
├── docker-compose.yml         # Multi-service orchestration
├── .github/                   # Documentation & instructions
│   ├── instructions/          # Development patterns
│   └── memory-bank/           # Project context
└── README.md                  # This file
```

---

## 🎯 Core Features

### Task Management
- **Default Tasks** (obligatory) - Must be completed to avoid consequences
- **Extra Tasks** (optional) - Only available after default tasks are done
- Points awarded upon completion

### Rewards System
- Family-defined reward catalog
- Redeem points for rewards
- Parent approval for high-value rewards

### Consequences
- Automatic consequences for incomplete default tasks
- Temporary restrictions (screen time, rewards, extra tasks)
- Parent-controlled resolution

### Family Management
- Role-based access (PARENT, CHILD, TEEN)
- Family data isolation
- Shared task board and rewards

---

## 🛠️ Tech Stack

**Backend** (FastAPI):
- Python 3.12+
- FastAPI (async web framework)
- PostgreSQL (production DB - port 5433)
- PostgreSQL (test DB - port 5435)
- SQLAlchemy 2.0 (async ORM)
- Alembic (migrations)
- Redis (sessions - port 6380)
- JWT + Bcrypt (authentication)

**Frontend** (Jinja2):
- Jinja2 (server-side rendering)
- Flowbite (Tailwind CSS components)
- HTMX (dynamic updates)
- Alpine.js (interactivity)

**Architecture**:
- Multi-tenant (family-based isolation)
- Clean Architecture (API → Service → Repository → Models)
- Domain-Driven Design patterns
- CQRS for complex operations
- Docker Compose orchestration

---

## 🐳 Docker Commands

```bash
# Start all services (backend, frontend, databases, redis)
docker-compose up -d

# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Stop services
docker-compose down

# Run tests
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run migrations
docker exec family_app_backend alembic upgrade head

# Create new migration
docker exec family_app_backend alembic revision --autogenerate -m "description"

# Seed demo data
docker exec family_app_backend python /app/seed_data.py

# Access production database
docker exec -it family_app_db psql -U familyapp -d familyapp

# Access test database
docker exec -it family_app_test_db psql -U familyapp_test -d familyapp_test

# Check service status
docker-compose ps
```

---

## 🧪 Testing

The project has **118 comprehensive tests** with 70%+ coverage.

```bash
# Run all tests (in Docker)
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v

# Run with coverage report
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Run specific test file
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/api/test_tasks.py -v

# Run tests locally (from backend/)
cd backend
pytest tests/ -v
pytest tests/ --cov=app --cov-report=html
```

**Test Structure**:
- `tests/api/` - API endpoint tests
- `tests/services/` - Business logic tests
- `tests/models/` - Database model tests
- Multi-tenant isolation tests
- Role-based access control tests

---

## 📚 API Documentation

Once the application is running, access:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Demo Users

After seeding demo data, you can login with:

```
mom@demo.com / password123 (PARENT, 500 points)
dad@demo.com / password123 (PARENT, 300 points)
emma@demo.com / password123 (CHILD, 150 points)
lucas@demo.com / password123 (TEEN, 280 points)
```

### Key Endpoints

**Authentication**:
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token
- `GET /api/auth/me` - Get current user info

**Tasks**:
- `GET /api/tasks` - List all tasks
- `POST /api/tasks` - Create task (parents only)
- `PATCH /api/tasks/{id}/complete` - Complete task

**Rewards**:
- `GET /api/rewards` - List rewards
- `POST /api/rewards/{id}/redeem` - Redeem reward

**Points**:
- `GET /api/points/balance` - Get point balance
- `GET /api/points/transactions` - Transaction history

---

## 🔐 Security

### Environment Variables (IMPORTANT!)

**NEVER commit `.env` file to git!**

Required environment variables:

```bash
# Generate secure secret key
openssl rand -hex 32

# Set in .env
SECRET_KEY=your-generated-secret-key
DATABASE_URL=postgresql://user:pass@db:5432/familyapp
```

### Security Features

- JWT token-based authentication
- Bcrypt password hashing
- Role-based access control (RBAC)
- Family data isolation
- Input validation with Pydantic
- SQL injection prevention (ORM)
- XSS prevention (Jinja2 auto-escape)

---

## 🚀 Deployment

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for detailed deployment instructions.

### Quick Deploy with Render

The application is configured for easy deployment on Render with the included `docker-compose.yml`.

**Service URLs**:
- Frontend (Port 3000)
- Backend API (Port 8000)
- PostgreSQL Production DB (Port 5433)
- PostgreSQL Test DB (Port 5435)
- Redis (Port 6380)

---

## 🤝 Contributing

1. Read **[AGENTS.md](./AGENTS.md)** for AI development guide
2. Read **[ARCHITECTURE.md](./ARCHITECTURE.md)** for architecture patterns
3. Check `.github/instructions/` for coding standards
4. Follow multi-tenant patterns (family-based isolation)
5. Write tests for new features (maintain 70%+ coverage)
6. Update documentation as needed

**Key Principles**:
- All models must have `family_id` for multi-tenant isolation
- Follow Clean Architecture (API → Service → Repository → Models)
- Use Domain-Driven Design patterns
- Write comprehensive tests
- Document architectural decisions

---

## 📝 License

This project is licensed under the MIT License.

---

## 🆘 Support

- **Quick Start**: See [AGENTS.md](./AGENTS.md) Setup Commands
- **Architecture**: See [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Deployment**: See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)
- **AI Instructions**: See `.github/copilot-instructions.md`
- **Issues**: GitHub Issues
- **Documentation**: `.github/memory-bank/`

---

## 🎉 Acknowledgments

- Inspired by **OurHome** family organization app
- Built with FastAPI, Flowbite, and modern web technologies
- Designed for families to make daily tasks fun and engaging

---

**Made with ❤️ for families everywhere**

