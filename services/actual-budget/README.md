# Family Finance Manager — Actual Budget Service

Standalone Actual Budget instance for managing the family's finances (presupuestos, domingos, ahorro, servicios, entretenimiento, mandado).

## Quick Start

### Via Root Docker Compose (Recommended)

The Actual Budget server and Finance API are integrated into the root `docker-compose.yml`:

```bash
# From the project root — starts all services including finance
docker-compose up -d
```

### Standalone (Development Only)

```bash
cd services/actual-budget
docker compose up -d          # Actual Budget server on port 5006
source .venv/bin/activate
uvicorn api:app --port 5007 --reload  # Finance API on port 5007
```

Then open **http://localhost:5006** to complete the initial setup:

1. Create a new password for the server.
2. Create a budget file (recommended name: **"My Finances"**).
3. Set up your category groups:

| Grupo                | Categorias sugeridas                          |
|----------------------|-----------------------------------------------|
| Mandado              | Supermercado, Mercado, Despensa               |
| Servicios            | Luz, Agua, Internet, Gas, Telefono            |
| Entretenimiento      | Cine, Restaurantes, Salidas, Streaming        |
| Domingos / Mesada    | Domingo Emma, Domingo Lucas                   |
| Ahorro               | Fondo de emergencia, Ahorro familiar          |
| Otros                | Ropa, Transporte, Medico, Escuela             |

## Architecture

```
Actual Budget Server (5006)  -->  Finance API (5007)  -->  Astro Frontend (3003)
actualbudget/actual-server       FastAPI + actualpy        /parent/finances pages
Docker container                 Docker container          SSR fetch during render
```

### Components

| Component | Port | Description |
|-----------|------|-------------|
| Actual Server | 5006 | Official Actual Budget Docker image |
| Finance API | 5007 | FastAPI wrapper exposing budget data as JSON REST |
| Sync CLI | N/A | `sync.py` — converts children's points to allowance transactions |

### Security

- Finance API is protected with API key authentication (`X-API-Key` header)
- CORS is restricted to configured frontend origins
- Set `FINANCE_API_KEY` in environment (shared between frontend and finance-api)
- When `FINANCE_API_KEY` is empty, auth is disabled (dev mode)

## Configuration

Copy `.env.example` to `.env` and update values:

```bash
cp .env.example .env
```

See `.env.example` for all available configuration options.

## Sync Service

Bridges the Family Task Manager points system with Actual Budget allowance accounts:

```bash
python sync.py                # Full sync (points → money transactions)
python sync.py --dry-run      # Preview what would be synced
python sync.py --status       # Show last sync status
```

## Data Persistence

All budget data is stored in a Docker volume (`actual_budget_data`). Back up regularly.

## Ports

| Service         | Port  |
|-----------------|-------|
| Actual Server   | 5006  |
| Finance API     | 5007  |
