# Family Task Manager - Decoupled Architecture

Gamified family task organization system with separate backend API and frontend web interface.

## 📁 Project Structure

```
family-task-manager/
├── backend/              # FastAPI REST API
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── core/        # Core functionality
│   │   ├── models/      # Database models
│   │   ├── schemas/     # Pydantic schemas
│   │   ├── services/    # Business logic
│   │   └── main.py      # FastAPI app
│   ├── migrations/      # Database migrations
│   ├── tests/           # Test suite
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md
│
├── frontend/            # SSR Web Interface
│   ├── app/
│   │   ├── templates/   # Jinja2 templates
│   │   ├── static/      # CSS, JS, images
│   │   ├── views.py     # Route handlers
│   │   ├── config.py    # Configuration
│   │   └── main.py      # FastAPI app
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md
│
├── docker-compose.yml   # Orchestration for all services
├── .env.example
└── README.md           # This file
```

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Copy environment file
cp .env.example .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Services will be available at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Database**: localhost:5433
- **Redis**: localhost:6380

### Option 2: Run Locally

#### Backend

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup database
alembic upgrade head

# Run server
uvicorn app.main:app --reload --port 8000
```

#### Frontend

```bash
cd frontend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload --port 3000
```

## 🏗️ Architecture

### Backend (Port 8000)

- **FastAPI REST API**
- PostgreSQL database
- Redis caching
- JWT authentication
- Full CRUD operations
- Business logic
- Data validation

### Frontend (Port 3000)

- **Server-Side Rendered (SSR)**
- Jinja2 templates
- Tailwind CSS + Flowbite
- Makes API calls to backend
- Session management
- User interface

### Communication Flow

```
User Browser
    ↓
Frontend Server (Port 3000)
    ↓ HTTP/REST
Backend API (Port 8000)
    ↓ SQL
PostgreSQL Database
```

## 🔧 Configuration

### Environment Variables

Create `.env` file in root directory:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5432/familyapp

# Security
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-here

# Application
DEBUG=true
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080

# Services
BACKEND_PORT=8000
FRONTEND_PORT=3000
```

## 🧪 Testing

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html
```

## 📊 Database Management

```bash
cd backend

# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Seed demo data
python seed_data.py
```

## 🎯 Demo Users

After running `seed_data.py`:

| User | Email | Password | Role | Points |
|------|-------|----------|------|--------|
| Sarah Johnson | mom@demo.com | password123 | PARENT | 500 |
| Mike Johnson | dad@demo.com | password123 | PARENT | 300 |
| Emma Johnson | emma@demo.com | password123 | CHILD | 150 |
| Lucas Johnson | lucas@demo.com | password123 | TEEN | 280 |

## 📚 API Documentation

Once backend is running:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

- `POST /api/auth/login` - User login
- `POST /api/auth/register` - User registration
- `GET /api/tasks/` - List tasks
- `POST /api/tasks/` - Create task
- `POST /api/tasks/{id}/complete` - Complete task
- `GET /api/rewards/` - List rewards
- `POST /api/rewards/{id}/redeem` - Redeem reward
- `GET /api/families/me` - Get family info

## 🎨 Frontend Pages

- `/` - Home (redirects to dashboard)
- `/login` - Login page
- `/register` - Registration
- `/dashboard` - Main dashboard
- `/tasks` - Task management
- `/rewards` - Rewards catalog
- `/consequences` - Consequences list
- `/points` - Points history
- `/family` - Family management
- `/settings` - User settings

## 🐳 Docker Commands

```bash
# Build services
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f [service_name]

# Stop services
docker-compose down

# Remove volumes (WARNING: deletes data)
docker-compose down -v

# Restart a service
docker-compose restart [service_name]

# Execute command in container
docker-compose exec backend bash
docker-compose exec frontend bash
```

## 🔍 Troubleshooting

### Backend won't start

```bash
# Check database connection
docker-compose logs db

# Check backend logs
docker-compose logs backend

# Restart backend
docker-compose restart backend
```

### Frontend can't connect to backend

```bash
# Verify backend is running
curl http://localhost:8000/health

# Check frontend logs
docker-compose logs frontend

# Verify API_BASE_URL in frontend config
```

### Database migration issues

```bash
# Check current migration status
cd backend
alembic current

# Reset database (WARNING: loses data)
docker-compose down -v
docker-compose up -d db
alembic upgrade head
```

## 📈 Development Workflow

1. **Start services**: `docker-compose up -d`
2. **Make changes** to backend or frontend code
3. **Services auto-reload** (in development mode)
4. **Run tests**: `cd backend && pytest`
5. **Commit changes**: `git add . && git commit -m "description"`
6. **Push**: `git push`

## 🚀 Deployment

### Production Considerations

1. Set `DEBUG=false`
2. Use production database (not SQLite)
3. Configure proper CORS origins
4. Use HTTPS
5. Set strong SECRET_KEY values
6. Use production WSGI server (Gunicorn)
7. Set up monitoring and logging
8. Configure backup strategy
9. Use environment-specific configs

### Example Production Docker Compose

```yaml
services:
  backend:
    image: your-registry/family-app-backend:latest
    environment:
      DEBUG: false
      DATABASE_URL: ${PROD_DATABASE_URL}
    restart: always

  frontend:
    image: your-registry/family-app-frontend:latest
    environment:
      DEBUG: false
      API_BASE_URL: https://api.yourdomain.com
    restart: always
```

## 🤝 Contributing

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes
3. Run tests: `cd backend && pytest`
4. Commit: `git commit -am "Add feature"`
5. Push: `git push origin feature/my-feature`
6. Create Pull Request

## 📄 License

Private project - All rights reserved

## 🆘 Support

- Backend README: `backend/README.md`
- Frontend README: `frontend/README.md`
- API Docs: http://localhost:8000/docs
- Health Checks:
  - Backend: http://localhost:8000/health
  - Frontend: http://localhost:3000/health
