# 🚀 Deployment Guide - Render.com

## Prerequisites

- GitHub account with this repository
- Render.com account (free tier available)
- HashiCorp Vault access (for OAuth/SMTP credentials)

---

## Step 1: Prepare the Repository

### 1.1 Create render.yaml (Infrastructure as Code)

Already created at root of project. This defines:
- Web service (FastAPI app)
- PostgreSQL database
- Environment variables

### 1.2 Update .gitignore

Ensure these are NOT committed:
```
.env
*.env
__pycache__/
*.pyc
htmlcov/
.coverage
```

### 1.3 Create Build Script

The `render-build.sh` script should:
```bash
#!/usr/bin/env bash
# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run database migrations
alembic upgrade head
```

---

## Step 2: Create Render Services

### 2.1 Create PostgreSQL Database

1. Go to https://dashboard.render.com
2. Click "New +" → "PostgreSQL"
3. Configure:
   - **Name**: `family-task-manager-db`
   - **Database**: `familyapp`
   - **User**: `familyapp`
   - **Region**: Choose closest to you
   - **Plan**: Free (or Starter $7/month for better performance)
4. Click "Create Database"
5. **Save** the Internal Database URL (starts with `postgresql://`)

### 2.2 Create Web Service

1. Click "New +" → "Web Service"
2. Connect your GitHub repository
3. Configure:

**Basic Settings:**
- **Name**: `family-task-manager`
- **Region**: Same as database
- **Branch**: `main`
- **Root Directory**: `.` (leave blank)
- **Runtime**: `Python 3`
- **Build Command**: `./render-build.sh`
- **Start Command**: `gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

**Instance Type:**
- Free tier (or Starter $7/month)

---

## Step 3: Configure Environment Variables

In the Render dashboard, add these environment variables:

### Required Variables

```bash
# Database (use Internal Database URL from Step 2.1)
DATABASE_URL=<from Render PostgreSQL>

# Security  
SECRET_KEY=<generate with: openssl rand -hex 32>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App Configuration
DEBUG=False
ALLOWED_ORIGINS=https://family-task-manager.onrender.com

# Email (from Vault: secret/shared/smtp)
SMTP_HOST=smtp.zoho.com
SMTP_PORT=465
SMTP_USER=noreply@a-ai4all.com
SMTP_PASSWORD=<from Vault>
SMTP_FROM_EMAIL=noreply@a-ai4all.com
SMTP_FROM_NAME=Family Task Manager
EMAIL_VERIFICATION_EXPIRE_MINUTES=1440

# Google OAuth (from Vault: secret/shared/oauth)
GOOGLE_CLIENT_ID=<from Vault>
GOOGLE_CLIENT_SECRET=<from Vault>
GOOGLE_REDIRECT_URI=https://family-task-manager.onrender.com/auth/google/callback

# Optional
LOG_LEVEL=INFO
```

### Get Credentials from Vault

```bash
# Connect to Vault
export VAULT_ADDR=http://10.1.0.99:8200
vault login

# Get SMTP credentials
vault kv get secret/shared/smtp

# Get OAuth credentials
vault kv get secret/shared/oauth
```

---

## Step 4: Update OAuth Redirect URI

### Google Cloud Console

1. Go to https://console.cloud.google.com/
2. Select your project
3. Navigate to: APIs & Services → Credentials
4. Click on your OAuth 2.0 Client ID
5. Add Authorized redirect URI:
   ```
   https://family-task-manager.onrender.com/auth/google/callback
   ```
6. Save changes

---

## Step 5: Deploy

### First Deployment

1. In Render dashboard, click "Manual Deploy" → "Deploy latest commit"
2. Watch the build logs
3. Wait for deployment to complete (~5-10 minutes)

### Verify Deployment

1. Click the URL: `https://family-task-manager.onrender.com`
2. You should see the app redirect to `/dashboard`
3. Try registering a new account
4. Check logs if any issues

---

## Step 6: Run Migrations (if needed)

If migrations didn't run automatically:

1. Go to your web service in Render
2. Click "Shell" tab
3. Run:
   ```bash
   alembic upgrade head
   ```

---

## Step 7: Seed Demo Data (Optional)

To add demo data to production:

1. In Render Shell:
   ```bash
   python seed_data.py
   ```

2. Demo credentials:
   - mom@demo.com / password123
   - dad@demo.com / password123
   - emma@demo.com / password123
   - lucas@demo.com / password123

---

## Continuous Deployment

### Auto-Deploy on Push

Render automatically deploys when you push to `main` branch:

```bash
git add .
git commit -m "Deploy to production"
git push origin main
```

### Manual Deploy

In Render dashboard:
1. Go to your web service
2. Click "Manual Deploy"
3. Select "Deploy latest commit"

---

## Monitoring & Maintenance

### View Logs

1. In Render dashboard → Your service
2. Click "Logs" tab
3. Real-time logs stream here

### Health Checks

Render automatically monitors:
- `/health` endpoint
- Restarts service if unhealthy

### Database Backups

**Free tier**: No automatic backups
**Paid tier**: Daily automatic backups

To backup manually:
```bash
pg_dump $DATABASE_URL > backup.sql
```

---

## Troubleshooting

### Build Fails

**Error**: `Permission denied: ./render-build.sh`
**Fix**: Make script executable
```bash
chmod +x render-build.sh
git add render-build.sh
git commit -m "Make build script executable"
git push
```

### Database Connection Error

**Error**: `could not connect to server`
**Fix**: Verify DATABASE_URL is the **Internal** URL, not External

### OAuth Not Working

**Error**: `redirect_uri_mismatch`
**Fix**: 
1. Check GOOGLE_REDIRECT_URI matches exactly in:
   - Render environment variables
   - Google Cloud Console

### Email Not Sending

**Check**:
1. SMTP credentials from Vault are correct
2. SMTP_PORT=465 (SSL) or 587 (TLS)
3. Check Render logs for SMTP errors

---

## Scaling

### Upgrade Plan

Free tier limitations:
- Spins down after 15 min inactivity
- Limited CPU/RAM

To upgrade:
1. Render dashboard → Your service
2. Click "Settings"
3. Change "Instance Type" to Starter ($7/month) or higher

### Add Worker Processes

For better performance, increase Gunicorn workers:

```bash
# In Start Command
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

Recommended workers: `(2 × CPU cores) + 1`

---

## Security Checklist

Before going live:

- [ ] DEBUG=False in production
- [ ] Strong SECRET_KEY (32+ characters)
- [ ] HTTPS only (Render provides this automatically)
- [ ] OAuth redirect URIs restricted
- [ ] Database has strong password
- [ ] SMTP credentials from Vault
- [ ] No secrets in git repository
- [ ] ALLOWED_ORIGINS set correctly

---

## Custom Domain (Optional)

### Add Custom Domain

1. Render dashboard → Your service
2. Click "Settings" → "Custom Domain"
3. Add your domain (e.g., `tasks.yourdomain.com`)
4. Update DNS records as instructed
5. Update:
   - ALLOWED_ORIGINS
   - GOOGLE_REDIRECT_URI

---

## Cost Estimate

### Free Tier
- Web Service: Free (with limitations)
- PostgreSQL: Free (25MB storage)
- **Total**: $0/month

### Recommended Starter
- Web Service: $7/month
- PostgreSQL: $7/month  
- **Total**: $14/month

### Production
- Web Service: $25/month (Standard)
- PostgreSQL: $25/month (with backups)
- **Total**: $50/month

---

## Support

- **Render Docs**: https://render.com/docs
- **Render Status**: https://status.render.com
- **Community**: https://community.render.com

---

## Rollback

If deployment fails:

1. Render dashboard → Your service
2. Click "Events" tab
3. Find last successful deployment
4. Click "Rollback to this version"

---

**Ready to Deploy!** 🚀

Follow these steps in order, and your app will be live in ~15 minutes.
