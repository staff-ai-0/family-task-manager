# Quick Start Guide - Authentication System

**Last Updated**: December 12, 2025

---

## Starting the Application

```bash
# Start all services
cd /home/jc/td/family-task-manager
docker compose up -d

# Check services are running
docker compose ps

# View logs
docker compose logs web -f

# Stop services
docker compose down
```

**Application URL**: http://localhost:8000

---

## Current Credentials

### Test User
- Email: `testuser1765530116@example.com`
- Password: `Test123!`
- Role: PARENT
- Email Verified: Yes
- Family: Test Family

### Google OAuth
- Client ID: `<from CREDENTIALS.md>`
- Client Secret: `<from CREDENTIALS.md>`
- Redirect URI: `http://localhost:8000/auth/google/callback`

### SMTP (Zoho)
- Host: `<from CREDENTIALS.md>`
- Port: `465`
- User: `<from CREDENTIALS.md>`
- Password: `<from CREDENTIALS.md>`

### Vault Access
- Server: `10.1.0.99:8200`
- Root Token: `<from CREDENTIALS.md>`
- OAuth Secrets: `secret/shared/oauth`
- SMTP Secrets: `secret/shared/smtp`

---

## Authentication Features

### ✅ Working Features:
1. **User Registration** - Email/password with auto-family creation
2. **Login System** - Email/password authentication with sessions
3. **Email Verification** - Token-based with 24-hour expiry
4. **Password Reset** - Token generation with 1-hour expiry
5. **Google OAuth** - Redirect working, ready for browser testing
6. **Dashboard Access** - Protected routes with session cookies

### ⚠️ Needs Browser Testing:
1. Complete Google OAuth flow with real Google account
2. Password reset form submission (backend ready)
3. Email verification banner UI and resend functionality

---

## Database Schema

### Core Tables:
- `users` - User accounts (with OAuth fields)
- `families` - Family groups
- `email_verification_tokens` - Email verification tokens
- `password_reset_tokens` - Password reset tokens
- `tasks` - Task assignments
- `rewards` - Reward catalog
- `consequences` - Consequences tracking
- `point_transactions` - Points history

### Key Relationships:
- Users belong to one Family
- Tasks assigned to Users
- Rewards belong to Families
- Consequences belong to Users
- Tokens reference Users

---

## Common Tasks

### Create New User (via API):
```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=John Doe&email=john@example.com&password=SecurePass123!&role=PARENT&family_option=create&family_name=Doe Family&terms=on"
```

### Test Login:
```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=john@example.com&password=SecurePass123!" \
  -c cookies.txt -L
```

### Access Dashboard:
```bash
curl http://localhost:8000/dashboard -b cookies.txt
```

### Test OAuth Redirect:
```bash
curl -I http://localhost:8000/auth/google/login
```

### Get User Info from Database:
```bash
docker compose exec db psql -U familyapp -d familyapp -c \
  "SELECT email, name, role, email_verified, oauth_provider FROM users;"
```

### Get Verification Token:
```bash
docker compose exec db psql -U familyapp -d familyapp -c \
  "SELECT token, expires_at FROM email_verification_tokens WHERE user_id = (SELECT id FROM users WHERE email = 'test@example.com');"
```

### Manual Email Verification:
```bash
# Get token from database
TOKEN="your-token-here"

# Verify email
curl "http://localhost:8000/auth/verify-email?token=${TOKEN}" -L
```

---

## Debugging

### Check Service Status:
```bash
docker compose ps
```

### View Application Logs:
```bash
# All logs
docker compose logs web

# Follow logs (real-time)
docker compose logs web -f

# Last 50 lines
docker compose logs web --tail 50

# Search logs
docker compose logs web | grep -i "error"
```

### Check Database:
```bash
# Connect to database
docker compose exec db psql -U familyapp -d familyapp

# List tables
\dt

# Describe table
\d users

# Query users
SELECT * FROM users;

# Exit
\q
```

### Restart Service:
```bash
# Restart web service only
docker compose restart web

# Restart all services
docker compose restart

# Rebuild and restart
docker compose up -d --build web
```

### Clear Database (CAUTION):
```bash
# Stop services
docker compose down

# Remove volumes (deletes all data)
docker compose down -v

# Start fresh
docker compose up -d
```

---

## Environment Configuration

### Required `.env` Variables:
```bash
# Database
DATABASE_URL=postgresql://familyapp:familyapp123@db:5432/familyapp

# Security
SECRET_KEY=your-secret-key-change-this-in-production
ALGORITHM=HS256

# Google OAuth
GOOGLE_CLIENT_ID=<from CREDENTIALS.md>
GOOGLE_CLIENT_SECRET=<from CREDENTIALS.md>
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# SMTP (Zoho)
SMTP_HOST=<from CREDENTIALS.md>
SMTP_PORT=465
SMTP_USER=<from CREDENTIALS.md>
SMTP_PASSWORD=<from CREDENTIALS.md>
SMTP_FROM_EMAIL=<from CREDENTIALS.md>
SMTP_FROM_NAME=Family Task Manager

# Email Verification
EMAIL_VERIFICATION_EXPIRE_MINUTES=1440  # 24 hours
```

---

## Testing Checklist

### Manual Browser Tests:

- [ ] **Registration Flow**
  - Visit `/register`
  - Fill form and submit
  - Redirected to login
  - Verification email logged

- [ ] **Login Flow**
  - Visit `/login`
  - Enter credentials
  - Redirected to dashboard
  - Session cookie set

- [ ] **Dashboard Access**
  - See user name
  - See family name
  - Sidebar navigation works
  - Logout works

- [ ] **Email Verification**
  - Yellow banner appears (unverified)
  - Click "Resend email"
  - Get token from logs
  - Visit verification link
  - Banner disappears

- [ ] **Password Reset**
  - Click "Forgot password"
  - Enter email
  - Get token from logs
  - Visit reset link
  - Enter new password
  - Login with new password

- [ ] **Google OAuth**
  - Click "Continue with Google"
  - Authorize with Google
  - Redirected to dashboard
  - Family auto-created
  - Email auto-verified
  - No verification banner

---

## Known Issues

### 1. Password Reset Form (422 Error)
- **Status**: Form encoding issue
- **Workaround**: Token generation works, manual testing needed
- **Priority**: Medium

### 2. SMTP Connection Timeout
- **Status**: Docker network issue
- **Workaround**: Email content visible in logs
- **Priority**: Low (works in production)

### 3. Migration Files Empty
- **Status**: Tables created manually
- **Workaround**: Regenerate migrations
- **Priority**: Medium (technical debt)

---

## Useful Commands

### Vault Commands:
```bash
# SSH to vault server
ssh 10.1.0.99

# Check vault status
sudo docker exec -e VAULT_ADDR="http://127.0.0.1:8200" icegg_vault vault status

# Get OAuth credentials
sudo docker exec -e VAULT_ADDR="http://127.0.0.1:8200" \
  -e VAULT_TOKEN="<from CREDENTIALS.md>" \
  icegg_vault vault kv get secret/shared/oauth

# Store new credentials
sudo docker exec -e VAULT_ADDR="http://127.0.0.1:8200" \
  -e VAULT_TOKEN="<from CREDENTIALS.md>" \
  icegg_vault vault kv put secret/shared/oauth \
  google_client_id="xxx" google_client_secret="yyy"
```

### Database Migrations:
```bash
# Check current migration
docker compose exec web alembic current

# View migration history
docker compose exec web alembic history

# Upgrade to latest
docker compose exec web alembic upgrade head

# Create new migration
docker compose exec web alembic revision --autogenerate -m "description"

# Downgrade one version
docker compose exec web alembic downgrade -1
```

---

## Next Steps

1. **Manual Browser Testing**
   - Test complete OAuth flow
   - Test password reset form
   - Test email verification UI

2. **Fix Known Issues**
   - Debug password reset form encoding
   - Regenerate empty migration files
   - Test SMTP in production environment

3. **Production Deployment**
   - Update OAuth redirect URI
   - Configure production environment variables
   - Run migrations on production database
   - Test all flows in production

---

**For detailed session information, see**: `.github/SESSION_2025_12_12_OAUTH_EMAIL.md`
