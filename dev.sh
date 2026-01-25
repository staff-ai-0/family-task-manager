#!/bin/bash
# Development startup script for Family Task Manager

echo "🏡 Family Task Manager - Development Mode"
echo "=========================================="
echo ""

# Check if database is running
if ! docker-compose ps | grep -q "family_app_db.*Up"; then
    echo "⚠️  Database not running. Starting..."
    docker-compose up -d db
    echo "⏳ Waiting for database to be ready..."
    sleep 5
fi

# Activate virtual environment
source venv/bin/activate

# Export database URL for local development
export DATABASE_URL=postgresql://familyapp:familyapp123@localhost:5433/familyapp

# Start the FastAPI application
echo "🚀 Starting FastAPI application..."
echo ""
echo "📍 Application will be available at:"
echo "   - Main app: http://localhost:8000"
echo "   - API docs: http://localhost:8000/docs"
echo "   - ReDoc:    http://localhost:8000/redoc"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
