# Family Task Manager - Technical Context

**Last Updated**: December 11, 2025

## Technology Stack Decisions

### Backend Framework: FastAPI

**Why FastAPI?**
- Modern, high-performance Python web framework
- Automatic API documentation (OpenAPI/Swagger)
- Built-in Pydantic validation
- Async support for better performance
- Type hints and IDE support
- Easy to test and deploy

**Alternatives Considered**:
- Django: Too heavy for our needs, brings unnecessary features
- Flask: Lacks built-in async support and validation
- Node.js: Team expertise is Python

**Decision**: FastAPI provides the best balance of performance, developer experience, and features for our use case.

### Frontend: Server-Side Rendering with Flowbite

**Why SSR with Flowbite?**
- Fast initial page load
- Better SEO (future consideration)
- Reduced JavaScript complexity
- Flowbite provides ready-to-use Tailwind components
- HTMX enables dynamic updates without heavy JS
- Alpine.js for lightweight interactivity

**Alternatives Considered**:
- React/Vue SPA: Overkill for our needs, complex deployment
- Plain HTML/CSS: Too much manual work
- Bootstrap: Flowbite/Tailwind more modern

**Decision**: Server-side rendering with Flowbite provides a modern, fast, and maintainable solution without the complexity of a full SPA framework.

### Database: PostgreSQL

**Why PostgreSQL?**
- Robust relational database for transactional data
- Excellent data integrity (ACID compliance)
- Perfect for point transactions and task history
- Great Render support
- Free tier available
- JSON support for flexible fields

**Alternatives Considered**:
- MongoDB: Less suitable for transactional data
- MySQL: PostgreSQL has better features
- SQLite: Not suitable for production web app

**Decision**: PostgreSQL is the industry standard for transactional web applications and fits our needs perfectly.

### ORM: SQLAlchemy

**Why SQLAlchemy?**
- Most mature Python ORM
- Async support (SQLAlchemy 2.0+)
- Type hints support
- Excellent query capabilities
- Migration support via Alembic

**Alternatives Considered**:
- Django ORM: Can't use without Django
- Tortoise ORM: Less mature
- Raw SQL: Too much manual work

**Decision**: SQLAlchemy 2.0 with async support provides the best developer experience and performance.

### Deployment: Render

**Why Render?**
- Simple deployment process
- Free tier for development
- PostgreSQL hosting included
- Automatic SSL certificates
- GitHub integration for CI/CD
- Easy scaling when needed

**Alternatives Considered**:
- Heroku: More expensive, less features
- AWS: Too complex for MVP
- DigitalOcean: Requires more DevOps work
- Vercel: Better for frontend, not ideal for Python

**Decision**: Render provides the best balance of simplicity, cost, and features for a FastAPI + PostgreSQL application.

### Authentication: JWT

**Why JWT?**
- Stateless authentication
- Works well with FastAPI
- Mobile app ready (future)
- Industry standard
- Easy to implement

**Implementation Details**:
- Access tokens with 30-minute expiration
- Refresh tokens for longer sessions
- Bcrypt for password hashing
- Role-based access control (RBAC)

### Frontend Libraries

**Flowbite**: UI components built on Tailwind CSS
- Pre-built cards, modals, alerts, buttons
- Responsive by default
- Consistent design system
- Good documentation

**HTMX**: Dynamic HTML updates
- Enables SPA-like experience without JavaScript frameworks
- Progressive enhancement
- Works with server-rendered HTML
- Minimal JavaScript footprint

**Alpine.js**: Reactive interactivity
- Lightweight (15kb)
- Vue-like syntax
- Perfect for simple interactions
- No build step required

**Tailwind CSS**: Utility-first styling
- Rapid UI development
- Consistent design
- Small production bundle (with PurgeCSS)
- Mobile-first approach

## Database Schema Design

### Core Tables

**users**:
- id (UUID, PK)
- email (unique)
- password_hash
- name
- role (enum: PARENT, CHILD, TEEN)
- family_id (FK)
- points (integer)
- created_at, updated_at

**families**:
- id (UUID, PK)
- name
- created_by (FK to users)
- created_at, updated_at

**tasks**:
- id (UUID, PK)
- family_id (FK)
- assigned_to (FK to users)
- created_by (FK to users)
- title, description
- points (integer)
- is_default (boolean)
- frequency (enum)
- status (enum)
- due_date, completed_at
- consequence_id (FK, nullable)
- created_at, updated_at

**rewards**:
- id (UUID, PK)
- family_id (FK)
- created_by (FK to users)
- title, description
- points_cost (integer)
- category (enum)
- icon (string)
- is_active (boolean)
- created_at, updated_at

**consequences**:
- id (UUID, PK)
- user_id (FK)
- title, description
- severity (enum)
- restriction_type (enum)
- duration_days (integer)
- triggered_by_task (FK, nullable)
- active (boolean)
- start_date, end_date
- resolved_at, resolved_by (FK)
- created_at

**point_transactions**:
- id (UUID, PK)
- user_id (FK)
- task_id (FK, nullable)
- reward_id (FK, nullable)
- points (integer, can be negative)
- transaction_type (enum)
- approved_by (FK, nullable)
- timestamp

### Indexing Strategy

**Primary Indexes**:
- All primary keys (id)
- Foreign keys (family_id, user_id, etc.)

**Composite Indexes**:
- (family_id, status) on tasks - for filtering family tasks by status
- (assigned_to, status) on tasks - for user's task list
- (family_id, is_active) on rewards - for active rewards catalog
- (user_id, timestamp) on point_transactions - for transaction history

**Performance Considerations**:
- Use eager loading for relationships to avoid N+1 queries
- Pagination for large lists (skip/limit)
- Cache frequently accessed data (user points in Redis)

## API Design Patterns

### RESTful Endpoints

**Authentication**:
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/logout
- GET /api/auth/me

**Tasks**:
- GET /api/tasks (list with filters)
- POST /api/tasks (create - parents only)
- GET /api/tasks/{id}
- PATCH /api/tasks/{id} (update)
- DELETE /api/tasks/{id} (delete - parents only)
- PATCH /api/tasks/{id}/complete (mark complete)

**Rewards**:
- GET /api/rewards
- POST /api/rewards (create - parents only)
- GET /api/rewards/{id}
- POST /api/rewards/{id}/redeem (redeem reward)
- GET /api/rewards/history

**Points**:
- GET /api/points/balance
- GET /api/points/transactions
- POST /api/points/transfer (parents only)

**Consequences**:
- GET /api/consequences (list active)
- POST /api/consequences/{id}/resolve (parents only)

**Dashboard**:
- GET /api/dashboard/status

### Response Format

**Success**:
```json
{
  "success": true,
  "data": { ... },
  "message": "Operation completed successfully"
}
```

**Error**:
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { ... }
  }
}
```

## Security Considerations

### Authentication & Authorization

1. **Password Security**:
   - Bcrypt hashing with work factor 12
   - Minimum password requirements (8 chars, mix of types)
   - Never store plain text passwords

2. **JWT Security**:
   - Short-lived access tokens (30 minutes)
   - Secure secret key (from environment)
   - HTTPS only in production

3. **Authorization**:
   - Role-based access control (PARENT, CHILD, TEEN)
   - Family isolation (users can only access their family data)
   - Endpoint-level permission checks

### Data Protection

1. **Input Validation**:
   - Pydantic schemas for all inputs
   - Sanitize HTML in text fields
   - Validate UUIDs and foreign keys

2. **SQL Injection Prevention**:
   - Use SQLAlchemy ORM (parameterized queries)
   - Never construct raw SQL from user input

3. **XSS Prevention**:
   - Jinja2 auto-escapes HTML
   - Sanitize user-generated content
   - Content Security Policy headers

### Rate Limiting

- Limit login attempts (5 per minute)
- Limit API calls per user (100 per minute)
- Implement in middleware layer

## Performance Optimization

### Database

1. **Query Optimization**:
   - Use eager loading for relationships
   - Implement pagination
   - Add appropriate indexes

2. **Connection Pooling**:
   - SQLAlchemy async engine with pool
   - Max 20 connections per instance

### Caching Strategy

1. **Redis Cache** (optional for MVP):
   - User points (5-minute TTL)
   - Family configurations
   - Active consequences

2. **Application-Level**:
   - LRU cache for frequently accessed data
   - Cache invalidation on updates

### Frontend Performance

1. **HTMX Benefits**:
   - Partial page updates
   - Reduced JavaScript
   - Better perceived performance

2. **Asset Optimization**:
   - Minified CSS/JS
   - CDN for Flowbite/Tailwind
   - Image optimization

## Testing Strategy

### Unit Tests

- Service layer business logic
- Model methods and properties
- Utility functions
- 80%+ code coverage target

### Integration Tests

- API endpoints
- Database operations
- Authentication flows

### E2E Tests (Future)

- Critical user journeys
- Task completion flow
- Reward redemption flow

### Test Tools

- pytest for unit/integration tests
- pytest-asyncio for async tests
- httpx for API testing
- factory_boy for test fixtures

## Deployment Architecture

### Development Environment

```
Local Machine
├── FastAPI (uvicorn --reload)
├── PostgreSQL (Docker)
├── Redis (Docker, optional)
└── Browser
```

### Production Environment (Render)

```
Render Platform
├── Web Service (FastAPI with Gunicorn/Uvicorn)
├── PostgreSQL Database
├── Static Files (CDN)
└── SSL Certificate (automatic)
```

### Environment Variables

**Required**:
- DATABASE_URL
- SECRET_KEY
- ALGORITHM (HS256)
- ACCESS_TOKEN_EXPIRE_MINUTES

**Optional**:
- REDIS_URL
- SENTRY_DSN (error tracking)
- LOG_LEVEL

## Monitoring & Logging

### Application Logging

- Structured logging (JSON format)
- Log levels: DEBUG, INFO, WARNING, ERROR
- Log all authentication events
- Log business transactions (points, rewards)

### Error Tracking (Future)

- Sentry integration
- Error alerts for critical issues
- Performance monitoring

### Analytics (Future)

- User engagement metrics
- Task completion rates
- Reward redemption frequency

## Development Workflow

1. **Local Development**:
   - Run FastAPI with hot reload
   - Use Docker for PostgreSQL
   - Test with Swagger UI

2. **Git Workflow**:
   - Feature branches
   - Pull requests with reviews
   - Main branch protected

3. **Database Migrations**:
   - Alembic for schema changes
   - Review migrations before applying
   - Keep migrations reversible

4. **Deployment**:
   - Push to GitHub
   - Render auto-deploys from main
   - Run migrations in production

---

**Created**: December 11, 2025  
**Maintained by**: Development Team
