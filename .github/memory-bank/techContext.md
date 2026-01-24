# Family Task Manager - Technical Context

**Last Updated**: December 12, 2025

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

**Type Safety Guidelines**:
- Use `Mapped[]` syntax for proper type hints (SQLAlchemy 2.0+)
- Convert Column types to Python types when passing to service methods
- See `.github/instructions/04-python-type-safety.instructions.md` for details
- Avoid direct Column comparisons; use explicit type conversion
- Use `UUID(as_uuid=True)` for proper UUID handling

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

### Authentication: Session-Based with OAuth Support

**Why Session-Based Authentication?**
- Server-side rendering requires session cookies
- Better security for SSR applications
- HTTP-only cookies prevent XSS attacks
- Works seamlessly with Jinja2 templates
- Industry standard for traditional web apps

**Implementation Details**:
- Session cookies with 30-minute expiration
- Bcrypt for password hashing (work factor 12)
- HTTP-only, SameSite=Lax cookies
- SessionMiddleware for OAuth state management
- Role-based access control (RBAC)

**OAuth 2.0 Integration**:
- Google OAuth for social login
- Auto-creates family for new OAuth users
- Email automatically verified for OAuth users
- OAuth users assigned PARENT role by default
- Credentials stored in HashiCorp Vault

**Password Recovery**:
- Secure token-based password reset
- Tokens expire after 1 hour
- One-time use tokens (marked as used)
- Tokens stored in database with user reference
- Email delivery via SMTP (Zoho)

**Email Verification**:
- Tokens generated on registration
- 24-hour expiration window
- One-time use with used_at timestamp
- Verification banner shown on dashboard
- Resend functionality available

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
- password_hash (nullable for OAuth users)
- name
- role (enum: PARENT, CHILD, TEEN)
- family_id (FK)
- points (integer)
- email_verified (boolean)
- email_verified_at (timestamp)
- oauth_provider (varchar 50, nullable)
- oauth_id (varchar 255, nullable)
- created_at, updated_at

**email_verification_tokens**:
- id (UUID, PK)
- token (varchar, unique)
- user_id (FK)
- expires_at (timestamp with timezone)
- is_used (boolean)
- used_at (timestamp with timezone)
- created_at (timestamp with timezone)

**password_reset_tokens**:
- token (varchar 64, PK)
- user_id (FK)
- expires_at (timestamp)
- is_used (boolean)
- created_at (timestamp)

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
- POST /register - Create new user account
- POST /login - Authenticate with email/password
- GET /auth/google/login - Initiate Google OAuth flow
- GET /auth/google/callback - OAuth callback handler
- GET /auth/forgot-password - Show password reset request page
- POST /auth/forgot-password - Send password reset email
- GET /auth/reset-password?token= - Show password reset form
- POST /auth/reset-password - Complete password reset
- GET /auth/verify-email?token= - Verify email address
- POST /auth/resend-verification - Resend verification email
- POST /logout - End user session
- GET /dashboard - Protected dashboard (requires auth)

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
- DATABASE_URL - PostgreSQL connection string
- SECRET_KEY - Session encryption key
- ALGORITHM - Hashing algorithm (HS256)
- GOOGLE_CLIENT_ID - OAuth client ID
- GOOGLE_CLIENT_SECRET - OAuth client secret
- GOOGLE_REDIRECT_URI - OAuth callback URL
- SMTP_HOST - Email server host
- SMTP_PORT - Email server port
- SMTP_USER - Email sender username
- SMTP_PASSWORD - Email sender password
- SMTP_FROM_EMAIL - From email address
- SMTP_FROM_NAME - From display name

**Optional**:
- REDIS_URL - Cache server (optional)
- SENTRY_DSN - Error tracking (optional)
- LOG_LEVEL - Logging verbosity (default: INFO)
- EMAIL_VERIFICATION_EXPIRE_MINUTES - Token expiry (default: 1440 = 24 hours)

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

### OAuth Configuration

**Google Cloud Console Setup**:
1. Create OAuth 2.0 Client ID at https://console.cloud.google.com/
2. Application type: Web application
3. Authorized redirect URIs:
   - Development: `http://localhost:8000/auth/google/callback`
   - Production: `https://yourdomain.com/auth/google/callback`
4. Store credentials in `.env` and HashiCorp Vault

**Current OAuth Credentials**:
- Client ID: `302073118386-pvn9h3d0ccbnu31jr0ipkatc8n0rgm5f.apps.googleusercontent.com`
- Stored in Vault: `secret/shared/oauth`
- Updated: December 12, 2025

**OAuth Flow**:
1. User clicks "Continue with Google"
2. Redirected to Google authorization page
3. User authorizes application
4. Google redirects to callback with auth code
5. Backend exchanges code for user info
6. Create or login user
7. Auto-create family for new users
8. Mark email as verified
9. Redirect to dashboard

### Email Configuration

**SMTP Provider**: Zoho Mail

**Current Configuration**:
- Host: `smtp.zoho.com`
- Port: `465` (SSL)
- From: `noreply@a-ai4all.com`
- From Name: "Family Task Manager"
- Stored in Vault: `secret/shared/smtp`

**Email Types**:
1. **Email Verification**: Sent on registration, 24-hour expiry
2. **Password Reset**: Sent on forgot password, 1-hour expiry
3. **Welcome Email**: (Future) Sent after email verification

**Email Templates**:
- HTML templates with inline CSS
- Responsive design for mobile
- Branded with application colors
- Clear call-to-action buttons

### HashiCorp Vault Integration

**Vault Server**: `10.1.0.99:8200`

**Stored Secrets**:
- `secret/shared/oauth` - Google OAuth credentials (Client ID, Secret)
- `secret/shared/smtp` - SMTP configuration (Host, Port, User, Password)
- `secret/icegg-app/*` - Other application secrets

**Access Pattern**:
```bash
# Unseal Vault (requires 3 of 5 keys)
vault operator unseal

# Get OAuth credentials
vault kv get secret/shared/oauth

# Get SMTP credentials
vault kv get secret/shared/smtp

# Store new secret
vault kv put secret/shared/oauth google_client_id="xxx" google_client_secret="yyy"
```

**Security**:
- Vault tokens expire after use
- Root token only for emergency access
- Backend token for application access
- Secrets versioned (can rollback if needed)

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
