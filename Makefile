.PHONY: help build up down restart logs clean test migrate shell db

# Variables
DOCKER_COMPOSE = docker-compose
APP_CONTAINER = family_app_web
DB_CONTAINER = family_app_db

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build Docker images
	$(DOCKER_COMPOSE) build

up: ## Start all services
	$(DOCKER_COMPOSE) up -d
	@echo "✅ Services started"
	@echo "📝 API: http://localhost:8000"
	@echo "📚 Docs: http://localhost:8000/docs"

up-build: ## Build and start all services
	$(DOCKER_COMPOSE) up --build -d
	@echo "✅ Services built and started"

down: ## Stop all services
	$(DOCKER_COMPOSE) down
	@echo "✅ Services stopped"

restart: ## Restart all services
	$(DOCKER_COMPOSE) restart
	@echo "✅ Services restarted"

logs: ## Show logs (use: make logs or make logs-web)
	$(DOCKER_COMPOSE) logs -f

logs-web: ## Show web service logs
	$(DOCKER_COMPOSE) logs -f web

logs-db: ## Show database logs
	$(DOCKER_COMPOSE) logs -f db

clean: ## Stop and remove all containers, volumes, and images
	$(DOCKER_COMPOSE) down -v --remove-orphans
	@echo "✅ Cleaned up containers and volumes"

test: ## Run tests
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) pytest

test-cov: ## Run tests with coverage
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) pytest --cov=app --cov-report=html

migrate: ## Run database migrations
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) alembic upgrade head
	@echo "✅ Migrations applied"

migrate-create: ## Create new migration (use: make migrate-create msg="description")
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) alembic revision --autogenerate -m "$(msg)"
	@echo "✅ Migration created"

shell: ## Access application shell
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) /bin/bash

shell-db: ## Access database shell
	$(DOCKER_COMPOSE) exec $(DB_CONTAINER) psql -U familyapp -d familyapp

db: ## Access database shell (alias)
	@make shell-db

format: ## Format code with black and isort
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) black app/ tests/
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) isort app/ tests/
	@echo "✅ Code formatted"

lint: ## Run linters
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) flake8 app/ tests/
	$(DOCKER_COMPOSE) exec $(APP_CONTAINER) mypy app/
	@echo "✅ Linting complete"

dev: ## Start development environment
	@make up
	@echo ""
	@echo "🚀 Development environment ready!"
	@echo "📝 API: http://localhost:8000"
	@echo "📚 API Docs: http://localhost:8000/docs"
	@echo "📊 ReDoc: http://localhost:8000/redoc"
	@echo ""
	@echo "💡 Useful commands:"
	@echo "  make logs     - View all logs"
	@echo "  make shell    - Access container shell"
	@echo "  make db       - Access database"
	@echo "  make migrate  - Run migrations"

init: ## Initialize project (first time setup)
	@echo "📦 Initializing Family Task Manager..."
	@cp .env.example .env
	@echo "📝 Created .env file - PLEASE EDIT IT!"
	@echo "🔑 Generate SECRET_KEY with: openssl rand -hex 32"
	@echo ""
	@make build
	@make up
	@sleep 5
	@make migrate
	@echo ""
	@echo "✅ Project initialized!"
	@echo "📝 Edit .env file with your configuration"
	@echo "🚀 Run 'make dev' to start development"

reset: ## Reset database and migrations
	@make down
	@make clean
	@make up
	@sleep 5
	@make migrate
	@echo "✅ Database reset complete"

status: ## Show status of all services
	$(DOCKER_COMPOSE) ps

install: ## Install Python dependencies locally
	pip install -r requirements.txt

install-dev: ## Install development dependencies
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov black flake8 mypy isort
