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
 * Note: This project uses Python/Uvicorn, not Node.js.
 * PM2 is used as a process manager for the Python applications.
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
      error_file: './logs/backend-error.log',
      out_file: './logs/backend-out.log',
      merge_logs: true,
      
      // Restart policy
      min_uptime: '10s',
      max_restarts: 10,
      restart_delay: 4000,
    },
    
    // Frontend Web (FastAPI/Uvicorn with Jinja2)
    {
      name: 'family-frontend',
      cwd: path.join(BASE_PATH, 'frontend'),
      script: path.join(BASE_PATH, 'venv/bin/uvicorn'),
      args: 'app.main:app --host 0.0.0.0 --port 3000',
      interpreter: path.join(BASE_PATH, 'venv/bin/python3'),
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '300M',
      
      // Environment variables (base)
      env: {
        NODE_ENV: 'development',
        DEBUG: 'true',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
      },
      
      // Staging environment
      env_stage: {
        NODE_ENV: 'staging',
        DEBUG: 'false',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
      },
      
      // Production environment
      env_production: {
        NODE_ENV: 'production',
        DEBUG: 'false',
        PORT: 3000,
        API_BASE_URL: 'http://localhost:8000',
      },
      
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: './logs/frontend-error.log',
      out_file: './logs/frontend-out.log',
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
      'post-deploy': 'docker compose -f docker-compose.stage.yml up -d && sleep 10 && pm2 reload ecosystem.config.cjs --env stage',
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
      'post-deploy': 'docker compose -f docker-compose.prod.yml up -d && sleep 10 && pm2 reload ecosystem.config.cjs --env production',
      env: {
        NODE_ENV: 'production',
      },
    },
  },
};
