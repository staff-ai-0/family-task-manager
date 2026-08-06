# Build context: the REPO ROOT (not ./backend). docker-compose*.yml set
# `context: .` + `dockerfile: backend/Dockerfile` so this file can COPY the
# two user guides out of docs/ — support mode (app/services/guide_context.py)
# reads docs/USER_GUIDE_{ES,EN}.md at runtime to ground its answers. Mirrors
# frontend/Dockerfile, which widened its context for the same files.
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# INSTALL_DEV=true → also installs test/lint tools (local dev only)
ARG INSTALL_DEV=false

# Copy requirements first for better caching
COPY backend/requirements.txt backend/requirements-dev.txt ./

# Install Python dependencies
RUN pip install --upgrade pip && \
    if [ "$INSTALL_DEV" = "true" ]; then \
        pip install -r requirements-dev.txt; \
    else \
        pip install -r requirements.txt; \
    fi

# Copy the backend tree, then ONLY the two user guides support mode grounds
# its answers on — NOT the rest of docs/ (internal engineering docs:
# DEPLOYMENT.md, OAUTH_PAYMENT_SETUP.md, docs/specs/, docs/superpowers/, ...)
# which must never ship inside the runtime image.
COPY backend/ .
COPY docs/USER_GUIDE_ES.md docs/USER_GUIDE_EN.md ./docs/

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/uploads/receipt-drafts && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
