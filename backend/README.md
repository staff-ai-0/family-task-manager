# Family Task Manager - Backend API

RESTful API built with FastAPI for gamified family task organization.

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- Redis 7+ (for caching)

### Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Edit .env with your configuration
```

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5432/familyapp

# Security
SECRET_KEY=your-secret-key-here
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080

# JWT
JWT_SECRET_KEY=your-jwt-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# OAuth (optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

### Database Setup

```bash
# Run migrations
alembic upgrade head

# Seed demo data (optional)
python seed_data.py
```

### Run Development Server

```bash
# With uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python
python -m app.main
```

### Run with Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

## 📚 API Documentation

Once the server is running:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth_service.py -v
```

## 📁 Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── routes/          # API endpoints
│   │       ├── auth.py
│   │       ├── tasks.py
│   │       ├── rewards.py
│   │       ├── users.py
│   │       ├── families.py
│   │       └── consequences.py
│   ├── core/
│   │   ├── config.py        # Configuration
│   │   ├── database.py      # Database connection
│   │   ├── security.py      # Security utilities
│   │   └── dependencies.py  # Dependency injection
│   ├── models/              # SQLAlchemy models
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── reward.py
│   │   ├── family.py
│   │   └── ...
│   ├── schemas/             # Pydantic schemas
│   │   ├── user.py
│   │   ├── task.py
│   │   └── ...
│   ├── services/            # Business logic
│   │   ├── auth_service.py
│   │   ├── task_service.py
│   │   ├── points_service.py
│   │   └── ...
│   └── main.py             # FastAPI app
├── migrations/             # Alembic migrations
├── tests/                  # Test suite
├── requirements.txt
├── alembic.ini
├── pytest.ini
└── README.md
```

## 🔌 API Endpoints

### Authentication

- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `GET /api/auth/me` - Get current user
- `GET /api/auth/google/login` - Google OAuth login
- `GET /api/auth/google/callback` - Google OAuth callback

### Tasks

- `GET /api/tasks/` - List tasks
- `POST /api/tasks/` - Create task
- `GET /api/tasks/{task_id}` - Get task details
- `PUT /api/tasks/{task_id}` - Update task
- `DELETE /api/tasks/{task_id}` - Delete task
- `POST /api/tasks/{task_id}/complete` - Mark task complete

### Rewards

- `GET /api/rewards/` - List rewards
- `POST /api/rewards/` - Create reward
- `GET /api/rewards/{reward_id}` - Get reward details
- `PUT /api/rewards/{reward_id}` - Update reward
- `DELETE /api/rewards/{reward_id}` - Delete reward
- `POST /api/rewards/{reward_id}/redeem` - Redeem reward

### Users

- `GET /api/users/me/points` - Get user points
- `GET /api/users/{user_id}` - Get user details
- `GET /api/users/{user_id}/points` - Get user points summary

### Families

- `GET /api/families/me` - Get current user's family
- `POST /api/families/` - Create family
- `GET /api/families/{family_id}` - Get family details
- `GET /api/families/{family_id}/members` - List family members
- `GET /api/families/{family_id}/stats` - Get family statistics

### Consequences

- `GET /api/consequences/` - List consequences
- `POST /api/consequences/` - Create consequence
- `GET /api/consequences/me/active` - Get active consequences for user

## 🏗️ Architecture

### Technology Stack

- **Framework**: FastAPI 0.104+
- **Database**: PostgreSQL 15 with SQLAlchemy 2.0 (async)
- **Cache**: Redis 7
- **Authentication**: JWT tokens + Google OAuth
- **Validation**: Pydantic v2
- **Migrations**: Alembic
- **Testing**: pytest + pytest-asyncio

### Key Features

- ✅ Async/await throughout
- ✅ Type hints everywhere
- ✅ Dependency injection
- ✅ Comprehensive error handling
- ✅ JWT authentication
- ✅ Google OAuth integration
- ✅ Email verification
- ✅ Password reset
- ✅ Points system
- ✅ Role-based access control (Parent/Child/Teen)
- ✅ Family isolation (multi-tenant)

## 🔒 Security

- Password hashing with bcrypt
- JWT token authentication
- CORS protection
- SQL injection prevention (SQLAlchemy ORM)
- Input validation (Pydantic)
- Rate limiting (TODO)
- HTTPS in production

## 📊 Database Schema

### Core Models

- **User**: Authentication, roles, points balance
- **Family**: Family groups for isolation
- **Task**: Tasks with points and frequencies
- **Reward**: Redeemable rewards
- **Consequence**: Auto-triggered penalties
- **PointTransaction**: Audit log for points

### Relationships

- User → Family (many-to-one)
- Task → User (assigned_to, many-to-one)
- Task → Family (many-to-one)
- Reward → Family (many-to-one)
- PointTransaction → User, Task, Reward

## 🧪 Test Coverage

Current coverage: **71%**

- `AuthService`: 100%
- `FamilyService`: 100%
- `TaskService`: 100%
- `PointsService`: 84%
- `RewardService`: 75%

Run tests:
```bash
pytest --cov=app --cov-report=term-missing
```

## 📝 Development

### Code Style

```bash
# Format code
black app tests

# Lint
ruff check app tests

# Type checking
mypy app
```

### Adding New Endpoints

1. Create route in `app/api/routes/`
2. Define schemas in `app/schemas/`
3. Add business logic in `app/services/`
4. Add tests in `tests/`
5. Update this README

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migration
alembic upgrade head

# Rollback
alembic downgrade -1
```

## 🐛 Troubleshooting

### Database connection errors

```bash
# Check PostgreSQL is running
docker-compose ps db

# Check connection
psql -h localhost -p 5432 -U familyapp -d familyapp
```

### Import errors

```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

### Migration errors

```bash
# Reset database (WARNING: deletes all data)
alembic downgrade base
alembic upgrade head
```

## 📞 Support

For issues and questions, please check:

- API Documentation: http://localhost:8000/docs
- Health endpoint: http://localhost:8000/health

## 📄 License

Private project - All rights reserved
