# GitHub Copilot Instructions: Family Task Manager

## Project Overview

This is the **Family Task Manager** - a gamified family task organization application with rewards and consequences system. The project follows the **OurHome** model, providing an engaging way for families to manage daily tasks, track points, and motivate children through a reward-based system.

**Target Audience**: Families with children (primary focus: 6-14 years old)  
**Core Value**: Transform daily chores into engaging challenges with visible progress and meaningful rewards

## Tech Stack

**Languages**: Python 3.12+

**Core Frameworks**:
- **FastAPI**: Modern async web framework for REST API
- **Pydantic**: Data validation and settings management
- **Jinja2**: Server-side rendering for HTML templates
- **Flowbite**: UI component library (built on Tailwind CSS)

**Frontend**:
- **Flowbite**: Modern UI components with Tailwind CSS
- **HTMX**: Dynamic interactions without heavy JavaScript
- **Alpine.js**: Lightweight reactive framework for enhanced interactivity
- **Tailwind CSS**: Utility-first CSS framework

**Database & Persistence**:
- **PostgreSQL**: Primary relational database for transactional data
- **SQLAlchemy**: ORM for database operations
- **Alembic**: Database migrations
- **Redis**: Session management and caching (optional)

**Authentication & Security**:
- **JWT**: Token-based authentication
- **Bcrypt**: Password hashing
- **CORS**: Cross-origin resource sharing configuration

**Deployment**:
- **Render**: Cloud platform for web services and databases
- **Docker**: Containerization (optional)
- **Gunicorn/Uvicorn**: ASGI server

## Repository Structure

```
family-app/
├── app/
│   ├── main.py                    # FastAPI application entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/                # API route handlers
│   │   │   ├── auth.py           # Authentication endpoints
│   │   │   ├── users.py          # User management
│   │   │   ├── tasks.py          # Task CRUD operations
│   │   │   ├── rewards.py        # Reward system
│   │   │   ├── points.py         # Points tracking
│   │   │   └── family.py         # Family group management
│   │   └── dependencies.py       # Shared dependencies
│   ├── core/
│   │   ├── config.py             # Configuration management
│   │   ├── security.py           # Security utilities
│   │   └── database.py           # Database connection
│   ├── models/
│   │   ├── user.py               # User model
│   │   ├── family.py             # Family group model
│   │   ├── task.py               # Task model
│   │   ├── reward.py             # Reward model
│   │   ├── consequence.py        # Consequence model
│   │   └── transaction.py        # Points transaction log
│   ├── schemas/
│   │   ├── user.py               # User Pydantic schemas
│   │   ├── task.py               # Task schemas
│   │   ├── reward.py             # Reward schemas
│   │   └── points.py             # Points schemas
│   ├── services/
│   │   ├── task_service.py       # Task business logic
│   │   ├── reward_service.py     # Reward management
│   │   ├── points_service.py     # Points calculation
│   │   ├── consequence_service.py # Consequence logic
│   │   └── notification_service.py # Notifications
│   ├── templates/                # Jinja2 HTML templates
│   │   ├── base.html            # Base layout
│   │   ├── dashboard.html       # Family dashboard
│   │   ├── tasks/               # Task management views
│   │   ├── rewards/             # Reward catalog
│   │   └── profile/             # User profiles
│   └── static/
│       ├── css/                 # Custom styles
│       ├── js/                  # JavaScript/Alpine.js
│       └── images/              # Icons, avatars
├── migrations/                   # Alembic migrations
├── tests/
│   ├── test_tasks.py
│   ├── test_rewards.py
│   ├── test_points.py
│   └── test_consequences.py
├── .env.example
├── requirements.txt
├── Dockerfile
└── README.md
```

## Core Features & Business Logic

### 1. Task Management System

**Default Tasks (Obligatory)**:
- Marked with `is_default = True` flag in database
- Must be completed to avoid consequences
- Examples: homework, room cleaning, daily hygiene

**Extra Tasks (Optional)**:
- Only available when default tasks are completed
- Earn additional points for rewards
- Examples: help with dishes, organize closet, help siblings

**Task Properties**:
```python
class Task:
    id: UUID
    title: str
    description: str
    points: int                    # Points earned upon completion
    is_default: bool               # Default (required) vs extra task
    frequency: TaskFrequency       # DAILY, WEEKLY, MONTHLY
    assigned_to: UUID              # User ID
    family_id: UUID
    due_date: datetime
    completed_at: Optional[datetime]
    status: TaskStatus             # PENDING, COMPLETED, OVERDUE
    consequence_id: Optional[UUID] # Linked consequence if incomplete
```

### 2. Points & Rewards System

**Points Logic**:
- Each completed task awards predefined points
- Points accumulate in user's balance
- Points can be redeemed for rewards
- Transactions are logged for transparency

**Reward Catalog**:
```python
class Reward:
    id: UUID
    title: str
    description: str
    points_cost: int               # Points required to redeem
    category: RewardCategory       # SCREEN_TIME, TREATS, ACTIVITIES, PRIVILEGES
    family_id: UUID
    is_active: bool
    icon: str                      # Icon identifier
```

**Redemption Rules**:
- Users can only redeem rewards if they have sufficient points
- Default tasks must be up-to-date (no active consequences)
- Parents must approve high-value rewards

### 3. Consequence System

**Consequence Triggers**:
- Default task remains incomplete past deadline
- Multiple missed tasks in a week
- Parent-defined custom rules

**Consequence Types**:
```python
class Consequence:
    id: UUID
    title: str
    description: str
    severity: ConsequenceSeverity  # LOW, MEDIUM, HIGH
    restriction_type: RestrictionType # SCREEN_TIME, REWARDS, EXTRA_TASKS
    duration_days: int
    triggered_by_task: UUID
    active: bool
    start_date: datetime
    end_date: datetime
```

**Enforcement**:
- UI displays active consequences prominently
- Restricted features are disabled in the interface
- Parents receive notifications about triggered consequences

### 4. Family Group Management

**Family Structure**:
- One family = multiple members (parents + children)
- Parents have admin privileges
- Children have limited access
- Shared task board and reward catalog

**Roles & Permissions**:
```python
class UserRole(str, Enum):
    PARENT = "parent"      # Can create/edit tasks, approve rewards
    CHILD = "child"        # Can complete tasks, request rewards
    TEEN = "teen"          # Extended privileges (self-assign extra tasks)
```

## Code Standards & Development Flow

**Development Commands**:
```bash
# Local development
uvicorn app.main:app --reload

# Run tests
pytest

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Lint & Format
black .
flake8 .
mypy .
```

**Code Style**:
- **MUST** use Python 3.12+ features and type hints
- Follow PEP 8 standards
- Use async/await patterns for database operations
- Proper error handling with custom exceptions

**Commit Standards**:
- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`
- Clear, descriptive messages
- Reference issue numbers when applicable

## API Design Patterns

### RESTful Endpoints

**Authentication**:
- `POST /api/auth/register` - Create new user account
- `POST /api/auth/login` - Get JWT token
- `POST /api/auth/logout` - Invalidate token
- `GET /api/auth/me` - Get current user

**Tasks**:
- `GET /api/tasks` - List all tasks (filtered by user/family)
- `POST /api/tasks` - Create new task (parents only)
- `PATCH /api/tasks/{id}/complete` - Mark task as completed
- `PUT /api/tasks/{id}` - Update task details
- `DELETE /api/tasks/{id}` - Delete task

**Rewards**:
- `GET /api/rewards` - List available rewards
- `POST /api/rewards` - Create reward (parents only)
- `POST /api/rewards/{id}/redeem` - Redeem reward with points
- `GET /api/rewards/history` - Redemption history

**Points**:
- `GET /api/points/balance` - Get user's point balance
- `GET /api/points/transactions` - Point transaction history
- `POST /api/points/transfer` - Transfer points (parents only)

**Consequences**:
- `GET /api/consequences` - List active consequences
- `POST /api/consequences/{id}/resolve` - Mark consequence as resolved
- `GET /api/dashboard/status` - Overall completion status

### Response Patterns

**Success Response**:
```json
{
  "success": true,
  "data": { ... },
  "message": "Task completed successfully"
}
```

**Error Response**:
```json
{
  "success": false,
  "error": {
    "code": "INSUFFICIENT_POINTS",
    "message": "Not enough points to redeem this reward",
    "details": { "required": 100, "current": 75 }
  }
}
```

## Database Schema Guidelines

### Key Relationships

```python
# One Family -> Many Users
family = relationship("Family", back_populates="members")

# One User -> Many Tasks
tasks = relationship("Task", back_populates="assigned_user")

# One Task -> Many Point Transactions
transactions = relationship("PointTransaction", back_populates="task")

# One Family -> Many Rewards
rewards = relationship("Reward", back_populates="family")
```

### Migration Strategy

- Use Alembic for all schema changes
- Never modify models without creating migration
- Test migrations in development before production
- Keep migrations reversible when possible

## Frontend Guidelines (Server-Side Rendering)

### Jinja2 Template Patterns

**Base Layout** (`templates/base.html`):
```html
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Family Task Manager{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/flowbite@2.5.1/dist/flowbite.min.css" rel="stylesheet" />
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50">
    {% include 'partials/navbar.html' %}
    
    <main class="container mx-auto px-4 py-8">
        {% block content %}{% endblock %}
    </main>
    
    <script src="https://cdn.jsdelivr.net/npm/flowbite@2.5.1/dist/flowbite.min.js"></script>
    <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
</body>
</html>
```

**HTMX Integration** (Dynamic Updates):
```html
<!-- Task completion button -->
<button 
    hx-patch="/api/tasks/{{ task.id }}/complete"
    hx-trigger="click"
    hx-target="#task-{{ task.id }}"
    hx-swap="outerHTML"
    class="btn btn-success">
    Completar
</button>
```

**Alpine.js for Interactivity**:
```html
<div x-data="{ points: {{ user.points }} }">
    <span x-text="points"></span> puntos
</div>
```

### Flowbite Components

**Recommended Components**:
- **Cards**: Task cards, reward cards
- **Badges**: Status indicators, point displays
- **Modals**: Task creation, reward redemption confirmations
- **Progress bars**: Task completion percentage
- **Avatars**: User profiles
- **Alerts**: Success/error messages
- **Dropdowns**: Filter menus

## Security Best Practices

### Authentication & Authorization

**JWT Token Management**:
```python
# Token creation
def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

**Permission Checks**:
```python
def require_parent_role(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.PARENT:
        raise HTTPException(status_code=403, detail="Parent access required")
    return current_user
```

### Data Protection

- **NEVER** store passwords in plain text (use bcrypt)
- **ALWAYS** validate and sanitize user inputs
- **ALWAYS** use parameterized queries (SQLAlchemy ORM)
- **LIMIT** API rate limiting for public endpoints
- **VALIDATE** file uploads if avatar feature is added

## Testing Strategy

### Test Coverage Goals

- **Unit Tests**: Models, schemas, services (80%+ coverage)
- **Integration Tests**: API endpoints, database operations
- **E2E Tests**: Critical user flows (task completion, reward redemption)

### Test Patterns

```python
# Service test example
def test_complete_task_awards_points():
    task = create_test_task(points=50)
    user = create_test_user(points=0)
    
    task_service.complete_task(task.id, user.id)
    
    assert task.status == TaskStatus.COMPLETED
    assert user.points == 50
    assert len(user.point_transactions) == 1
```

## Deployment Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/familyapp

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Application
DEBUG=False
ALLOWED_ORIGINS=https://yourdomain.com

# Optional: Redis
REDIS_URL=redis://localhost:6379/0
```

### Render Deployment

**Build Command**: `pip install -r requirements.txt`  
**Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Database**: PostgreSQL instance on Render  
**Static Files**: Served via Render's CDN

## Global Policies

### 🚨 Security Rules

- **NEVER** hardcode secrets, API keys, or credentials
- **ALWAYS** load secrets from environment variables
- **ALWAYS** validate user permissions before state-changing operations
- **ALWAYS** sanitize inputs to prevent SQL injection and XSS

### 🧹 Code Maintenance

**WHEN making ANY code changes**:
1. Remove unused imports and dead code
2. Consolidate duplicate logic
3. Update related documentation
4. Add/update tests for changed functionality
5. Run linters before committing

### 📖 Documentation Standards

- **ALWAYS** include docstrings for public functions and classes
- **ALWAYS** update API documentation when endpoints change
- **ALWAYS** document business logic decisions in code comments
- **ALWAYS** keep README.md current with setup instructions

### 🧪 Testing Requirements

- **ALWAYS** test new features before pushing
- **ALWAYS** ensure tests pass before merging
- **PREFER** integration tests for business-critical flows
- **VALIDATE** edge cases (insufficient points, overdue tasks, etc.)

## Development Workflow

1. **Feature Planning**: Create issue/task with requirements
2. **Database First**: Design models and create migration
3. **Service Layer**: Implement business logic with tests
4. **API Endpoints**: Create RESTful routes
5. **Frontend Templates**: Build UI with Flowbite components
6. **Integration Testing**: Test complete user flows
7. **Documentation**: Update API docs and instructions
8. **Review & Deploy**: Code review, then deploy to Render

## Key Reference Documents

**Location**: `.github/` directory

- **`copilot-instructions.md`** - This file (main instructions)
- **`instructions/01-backend-logic.instructions.md`** - Backend development guidelines
- **`instructions/02-frontend-ui.instructions.md`** - Frontend/template guidelines
- **`prompts/new-api-endpoint.md`** - Template for creating new endpoints
- **`prompts/new-model.md`** - Template for database models
- **`prompts/new-service.md`** - Template for service layer
- **`memory-bank/projectbrief.md`** - Original project requirements
- **`memory-bank/techContext.md`** - Technical decisions and architecture

**Update these documents** when you discover new patterns or architectural decisions.

---

## Quick Start for Developers

### First Time Setup

```bash
# Clone repository
git clone https://github.com/yourusername/family-app.git
cd family-app

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup database
cp .env.example .env  # Edit with your database URL
alembic upgrade head

# Run development server
uvicorn app.main:app --reload
```

### Creating a New Feature

1. Check `prompts/` directory for relevant templates
2. Create database models if needed (with migration)
3. Implement service layer with business logic
4. Create API endpoints
5. Build frontend templates
6. Write tests
7. Update documentation

---

**Last Updated**: December 11, 2025  
**Maintained by**: Family App Development Team
