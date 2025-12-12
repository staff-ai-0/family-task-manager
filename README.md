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
git clone https://github.com/yourusername/family-app.git
cd family-app

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env and set your SECRET_KEY
# Generate a secure key with: openssl rand -hex 32

# 4. Build and start services
docker-compose up --build

# 5. Access the application
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Local Development Setup

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment variables
cp .env.example .env
# Edit .env with your configuration

# 4. Start PostgreSQL with Docker
docker-compose up -d db

# 5. Run migrations
alembic upgrade head

# 6. Start development server
uvicorn app.main:app --reload
```

---

## 📖 Documentation

All documentation is in the `.github/` directory:

- **`.github/README.md`** - Documentation index
- **`.github/GUIA_RAPIDA.md`** - Quick start guide (Spanish)
- **`.github/copilot-instructions.md`** - Complete project guide
- **`.github/memory-bank/projectbrief.md`** - Business requirements
- **`.github/memory-bank/techContext.md`** - Technical architecture

---

## 🏗️ Project Structure

```
family-app/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   └── routes/             # API endpoints
│   ├── core/
│   │   ├── config.py           # Settings and configuration
│   │   ├── database.py         # Database connection
│   │   ├── security.py         # Authentication utilities
│   │   └── dependencies.py     # Shared dependencies
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   ├── services/               # Business logic
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS, JS, images
├── tests/                      # Test suite
├── migrations/                 # Alembic migrations
├── docker-compose.yml          # Docker services
├── Dockerfile                  # Application container
├── requirements.txt            # Python dependencies
└── .github/                    # 📚 Documentation
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

**Backend**:
- FastAPI (Python 3.12+)
- PostgreSQL
- SQLAlchemy (async)
- Alembic (migrations)
- JWT + Bcrypt (auth)

**Frontend**:
- Jinja2 (server-side rendering)
- Flowbite (Tailwind CSS components)
- HTMX (dynamic updates)
- Alpine.js (interactivity)

**Deployment**:
- Docker & Docker Compose
- Render (production)

---

## 🐳 Docker Commands

```bash
# Start all services
docker-compose up

# Build and start
docker-compose up --build

# Start in background
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f web

# Run migrations
docker-compose exec web alembic upgrade head

# Create migration
docker-compose exec web alembic revision --autogenerate -m "description"

# Access database
docker-compose exec db psql -U familyapp -d familyapp
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_tasks.py

# Verbose output
pytest -v
```

---

## 📚 API Documentation

Once the application is running, access:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

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

## 🚀 Deployment to Render

1. **Create account** on [Render](https://render.com)

2. **Create PostgreSQL database**:
   - New → PostgreSQL
   - Copy DATABASE_URL

3. **Create Web Service**:
   - New → Web Service
   - Connect GitHub repository
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

4. **Set Environment Variables**:
   - `DATABASE_URL` - From PostgreSQL instance
   - `SECRET_KEY` - Generated secure key
   - `DEBUG` - `False`
   - `ALLOWED_ORIGINS` - Your domain

5. **Run Migrations**:
   - In Render shell: `alembic upgrade head`

---

## 🤝 Contributing

1. Read `.github/copilot-instructions.md`
2. Check `.github/prompts/` for templates
3. Follow code quality rules in `.github/instructions/`
4. Write tests for new features
5. Update documentation

---

## 📝 License

This project is licensed under the MIT License.

---

## 🆘 Support

- **Documentation**: `.github/README.md`
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions

---

## 🎉 Acknowledgments

- Inspired by **OurHome** family organization app
- Built with FastAPI, Flowbite, and modern web technologies
- Designed for families to make daily tasks fun and engaging

---

**Made with ❤️ for families everywhere**
