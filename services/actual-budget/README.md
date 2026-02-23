# Family Finance Manager — Actual Budget Service

Standalone Actual Budget instance for managing the family's finances (presupuestos, domingos, ahorro, servicios, entretenimiento, mandado).

## Quick Start

```bash
cd services/actual-budget
docker compose up -d
```

Then open **http://localhost:5006** to complete the initial setup:

1. Create a new password for the server.
2. Create a budget file (recommended name: **"Presupuesto Familiar"**).
3. Set up your category groups:

| Grupo                | Categorías sugeridas                          |
|----------------------|-----------------------------------------------|
| 🛒 Mandado           | Supermercado, Mercado, Despensa               |
| 🏠 Servicios         | Luz, Agua, Internet, Gas, Teléfono            |
| 🎉 Entretenimiento   | Cine, Restaurantes, Salidas, Streaming        |
| 👧 Domingos / Mesada | Domingo Emma, Domingo Lucas                   |
| 💰 Ahorro            | Fondo de emergencia, Ahorro familiar          |
| 📦 Otros             | Ropa, Transporte, Médico, Escuela             |

## Architecture

This service is **fully decoupled** from the Family Task Manager backend.  
In the future it will:

- Have its own FastAPI middleware (`actualpy`) for automation (receipt OCR, points → money conversion).
- Have its own dedicated Astro frontend.

For now, the existing Astro frontend provides a `/parent/finances` page that embeds or links to this instance.

## Data Persistence

All budget data is stored in `./actual-data/` (mounted as a Docker volume). Back up this folder regularly.

## Ports

| Service         | Port  |
|-----------------|-------|
| Actual Server   | 5006  |
