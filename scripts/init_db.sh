#!/bin/bash

# Family Task Manager - Database Initialization Script
# This script creates the initial database migration

set -e  # Exit on error

echo "🏗️  Family Task Manager - Database Initialization"
echo "=================================================="
echo ""

# Check if we're in the correct directory
if [ ! -f "alembic.ini" ]; then
    echo "❌ Error: alembic.ini not found. Please run this script from the project root."
    exit 1
fi

# Check if Docker Compose is running
echo "📡 Checking Docker Compose services..."
if ! docker-compose ps | grep -q "Up"; then
    echo "🐳 Starting Docker Compose services..."
    docker-compose up -d
    echo "⏳ Waiting for PostgreSQL to be ready..."
    sleep 10
else
    echo "✅ Docker Compose services are running"
fi

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to accept connections..."
for i in {1..30}; do
    if docker-compose exec -T db pg_isready -U familyapp > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ PostgreSQL did not become ready in time"
        exit 1
    fi
    sleep 1
done

# Check if migrations/versions directory exists and has files
if [ -d "migrations/versions" ] && [ "$(ls -A migrations/versions)" ]; then
    echo "⚠️  Warning: migrations/versions directory already contains migration files"
    echo "   Skipping migration generation. If you want to regenerate, delete the files first."
else
    # Generate initial migration
    echo "🔨 Generating initial database migration..."
    docker-compose exec -T web alembic revision --autogenerate -m "initial_schema"
    
    if [ $? -eq 0 ]; then
        echo "✅ Initial migration generated successfully"
    else
        echo "❌ Failed to generate migration"
        exit 1
    fi
fi

# Apply migrations
echo "🚀 Applying database migrations..."
docker-compose exec -T web alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✅ Migrations applied successfully"
else
    echo "❌ Failed to apply migrations"
    exit 1
fi

# Check database tables
echo "📊 Verifying database tables..."
docker-compose exec -T db psql -U familyapp -d familyapp -c "\dt" | grep -E "families|users|tasks|rewards|consequences|point_transactions"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Database initialization complete!"
    echo ""
    echo "📋 Next steps:"
    echo "   1. Access the API: http://localhost:8000"
    echo "   2. View API docs: http://localhost:8000/docs"
    echo "   3. Create a family and users via the API"
    echo ""
else
    echo "⚠️  Tables verification failed. Check the database manually."
fi
