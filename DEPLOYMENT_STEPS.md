# 🚀 Production Deployment Steps - Phase 10 & 11

## Prerequisites
- SSH access to production server
- Docker and Docker Compose installed
- Git installed on production server
- Production `.env` file with required variables

## Quick Deployment (Single Command)

```bash
cd /path/to/family-task-manager
chmod +x deploy-prod.sh
./deploy-prod.sh
```

## Manual Step-by-Step Deployment

### Step 1: Pull Latest Code
```bash
cd /path/to/family-task-manager
git fetch origin main
git reset --hard origin/main
```

### Step 2: Verify Current Commit
```bash
git log --oneline -1
# Should show: 5d933de docs: Add comprehensive Phase 10 & 11 deployment guide
```

### Step 3: Stop Old Containers
```bash
docker-compose down -v
docker stop family-app-backend family-app-frontend 2>/dev/null || true
docker rm family-app-backend family-app-frontend 2>/dev/null || true
```

### Step 4: Build Backend Container
```bash
docker build --no-cache -t family-task-manager-backend:latest ./backend
```

### Step 5: Build Frontend Container
```bash
docker build --no-cache -t family-task-manager-frontend:latest ./frontend
```

### Step 6: Start Infrastructure (DB + Redis)
```bash
docker-compose -f docker-compose.prod.yml up -d
```

### Step 7: Wait for Database Health
```bash
sleep 15
docker-compose -f docker-compose.prod.yml exec -T db pg_isready -U familyapp
```

### Step 8: Run Database Migrations
```bash
docker run --rm \
  --network family-task-manager_app_network \
  -e DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp" \
  -v $(pwd)/backend:/app \
  family-task-manager-backend:latest \
  bash -c "cd /app && alembic upgrade head"
```

### Step 9: Start Backend Service
```bash
docker run -d \
  --name family-app-backend \
  --network family-task-manager_app_network \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp" \
  -e REDIS_URL="redis://redis:6379/0" \
  -e SECRET_KEY="${SECRET_KEY}" \
  -e DEBUG=false \
  family-task-manager-backend:latest
```

### Step 10: Start Frontend Service
```bash
docker run -d \
  --name family-app-frontend \
  --network family-task-manager_app_network \
  -p 3003:3000 \
  -e API_BASE_URL="http://family-app-backend:8000" \
  family-task-manager-frontend:latest
```

### Step 11: Verify Deployment

Test backend health:
```bash
curl http://localhost:8000/docs
```

Test sync endpoint deprecation (should return 410):
```bash
curl -i http://localhost:8000/api/sync/health
# Expected: HTTP/1.1 410 Gone
```

Test frontend:
```bash
curl http://localhost:3003
```

### Step 12: Monitor Logs
```bash
# Backend logs
docker logs -f family-app-backend

# Frontend logs
docker logs -f family-app-frontend

# Database logs
docker logs -f family_app_db
```

## Verification Checklist

- [ ] Code is latest commit (5d933de)
- [ ] Database migrations completed without errors
- [ ] Backend container is running
- [ ] Frontend container is running
- [ ] Backend health endpoint responds
- [ ] Sync endpoints return 410 Gone
- [ ] No errors in container logs
- [ ] API documentation accessible

## Troubleshooting

### Backend won't start
```bash
docker logs family-app-backend
# Check for: database connection, missing migrations, env variables
```

### Database migration failed
```bash
docker logs family-app-db
# Check postgres logs for connection issues
alembic current  # Check migration status
alembic downgrade -1  # Rollback if needed
```

### Frontend won't start
```bash
docker logs family-app-frontend
# Check for: missing env variables, port conflicts
```

### Port already in use
```bash
lsof -i :8000  # Check who's using port 8000
lsof -i :3003  # Check who's using port 3003
kill -9 <PID>  # Kill the process
```

## Rollback Procedure

If deployment fails, rollback to previous version:

```bash
# 1. Revert to previous commit
git revert 5d933de
git push origin main

# 2. Pull on production
git pull origin main

# 3. Rebuild containers
docker-compose down -v
docker build --no-cache -t family-task-manager-backend:latest ./backend
docker build --no-cache -t family-task-manager-frontend:latest ./frontend

# 4. Restart services
docker-compose -f docker-compose.prod.yml up -d
docker run -d ... (use previous commands with reverted code)

# 5. Downgrade database if needed
docker run --rm \
  --network family-task-manager_app_network \
  -e DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp" \
  -v $(pwd)/backend:/app \
  family-task-manager-backend:latest \
  bash -c "cd /app && alembic downgrade -1"
```

## Deployment Completion Checklist

✅ Code pulled from GitHub  
✅ Docker containers rebuilt  
✅ Database migrations applied  
✅ Backend service running  
✅ Frontend service running  
✅ API endpoints responding  
✅ Logs show no errors  
✅ Sync endpoints return 410 Gone  
✅ Application accessible from browser  

## Post-Deployment Monitoring

Monitor these metrics for 24 hours:
- API response times
- Database query performance
- Error rates
- Memory/CPU usage
- User reports

## Support

- Check DEPLOYMENT_PHASE_10_11.md for detailed information
- Review AGENTS.md for architecture overview
- Check git log for recent changes
- Monitor docker logs continuously

