const path = require('path');
const BASE_PATH = process.env.FAMILY_APP_PATH || '/home/jc/family-task-manager';

/**
 * Family Task Manager - PM2 Ecosystem Configuration
 * ==================================================
 * 
 * PM2 process manager configuration for staging and production deployments.
 * 
 * Usage:
 *   pm2 start ecosystem.config.cjs --env stage
 *   pm2 start ecosystem.config.cjs --env production
 * 
 * Architecture:
 *   - Backend: Python/FastAPI via Uvicorn
 *   - Frontend: Astro 5 SSR via Node.js (standalone mode)
 *   - Finance API: Python/FastAPI via Uvicorn
 *   - Infrastructure (DB, Redis, Actual Budget): Docker via docker-compose.stage.yml
 */

module.exports = {
  apps: [
    // Backend API (FastAPI/Uvicorn)
    {
      name: 'family-backend',
      cwd: path.join(BASE_PATH, 'backend'),
      script: path.join(BASE_PATH, 'venv/bin/uvicorn'),
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      interpreter: path.join(BASE_PATH, 'venv/bin/python3'),
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      
      // Environment variables (base)
      env: {
        NODE_ENV: 'development',
        DEBUG: 'true',
        PORT: 8000,
      },
      
      // Staging environment
      env_stage: {
        NODE_ENV: 'staging',
        DEBUG: 'false',
        PORT: 8000,
        BASE_URL: 'https://fam-stage.a-ai4all.com',
      },
      
      // Production environment
      env_production: {
        NODE_ENV: 'production',
        DEBUG: 'false',
        PORT: 8000,
        BASE_URL: 'https://fam.a-ai4all.com',
      },
      
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: path.join(BASE_PATH, 'logs/backend-error.log'),
      out_file: path.join(BASE_PATH, 'logs/backend-out.log'),
      merge_logs: true,
      
      // Restart policy
      min_uptime: '10s',
      max_restarts: 10,
      restart_delay: 4000,
    },
    
    // Frontend Web (Astro 5 SSR - Node.js standalone)
    // Build: cd frontend && npm run build
    // Output: frontend/dist/server/entry.mjs
    {
      name: 'family-frontend',
      cwd: path.join(BASE_PATH, 'frontend'),
      script: './dist/server/entry.mjs',
      interpreter: 'node',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '300M',
      
      // Environment variables (base)
      // FINANCE_API_KEY should be set in .env, not hardcoded here
      env: {
        NODE_ENV: 'development',
        HOST: '0.0.0.0',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
        FINANCE_API_URL: 'http://localhost:5007',
        ACTUAL_BUDGET_URL: 'http://localhost:5006',
      },
      
      // Staging environment
      env_stage: {
        NODE_ENV: 'staging',
        HOST: '0.0.0.0',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
        FINANCE_API_URL: 'http://localhost:5007',
        ACTUAL_BUDGET_URL: 'http://localhost:5006',
      },
      
      // Production environment
      env_production: {
        NODE_ENV: 'production',
        HOST: '0.0.0.0',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
        FINANCE_API_URL: 'http://localhost:5007',
        ACTUAL_BUDGET_URL: 'http://localhost:5006',
      },
      
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: path.join(BASE_PATH, 'logs/frontend-error.log'),
      out_file: path.join(BASE_PATH, 'logs/frontend-out.log'),
      merge_logs: true,
      
      // Restart policy
      min_uptime: '10s',
      max_restarts: 10,
      restart_delay: 4000,
    },

    // Finance API (Actual Budget wrapper - Python/FastAPI)
    {
      name: 'family-finance-api',
      cwd: path.join(BASE_PATH, 'services/actual-budget'),
      script: path.join(BASE_PATH, 'venv/bin/uvicorn'),
      args: 'api:app --host 0.0.0.0 --port 5007',
      interpreter: path.join(BASE_PATH, 'venv/bin/python3'),
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '200M',
      
      // Environment variables (base) — loaded from .env at deploy time
      // ACTUAL_PASSWORD and FINANCE_API_KEY should be set in .env, not here
      env: {
        ACTUAL_SERVER_URL: 'http://localhost:5006',
        ACTUAL_BUDGET_NAME: 'My Finances',
        ALLOWED_ORIGINS: 'http://localhost:3000,http://localhost:3003',
      },
      
      // Staging environment
      env_stage: {
        ACTUAL_SERVER_URL: 'http://localhost:5006',
        ACTUAL_BUDGET_NAME: 'My Finances',
        ALLOWED_ORIGINS: 'https://fam-stage.a-ai4all.com,http://localhost:3000',
      },
      
      // Production environment
      env_production: {
        ACTUAL_SERVER_URL: 'http://localhost:5006',
        ACTUAL_BUDGET_NAME: 'My Finances',
        ALLOWED_ORIGINS: 'https://fam.a-ai4all.com',
      },
      
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: path.join(BASE_PATH, 'logs/finance-api-error.log'),
      out_file: path.join(BASE_PATH, 'logs/finance-api-out.log'),
      merge_logs: true,
      
      // Restart policy
      min_uptime: '10s',
      max_restarts: 10,
      restart_delay: 4000,
    },
  ],
  
  // Deployment configuration (optional, for pm2 deploy)
  deploy: {
    stage: {
      user: 'jc',
      host: '10.1.0.91',
      ref: 'origin/main',
      repo: 'git@github.com:staff-ai-0/family-task-manager.git',
      path: '/home/jc/family-task-manager',
      'pre-deploy': 'git fetch --all',
      'post-deploy': 'docker compose -f docker-compose.stage.yml up -d && sleep 10 && cd frontend && npm ci && npm run build && cd .. && pm2 reload ecosystem.config.cjs --env stage',
      env: {
        NODE_ENV: 'staging',
      },
    },
    production: {
      user: 'jc',
      host: '10.1.0.92',
      ref: 'origin/main',
      repo: 'git@github.com:staff-ai-0/family-task-manager.git',
      path: '/home/jc/family-task-manager',
      'pre-deploy': 'git fetch --all',
      'post-deploy': 'docker compose -f docker-compose.prod.yml up -d && sleep 10 && cd frontend && npm ci && npm run build && cd .. && pm2 reload ecosystem.config.cjs --env production',
      env: {
        NODE_ENV: 'production',
      },
    },
  },
};
