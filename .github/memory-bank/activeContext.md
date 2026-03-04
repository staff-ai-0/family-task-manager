# Active Context

**Current Phase**: Production Complete  
**Week**: N/A (post-launch)  
**Status**: Live in production  
**Last Updated**: March 3, 2026

## 🎯 Phase Goals

Maintain production stability, keep AI assistant context minimal and current.

## 📋 Current Sprint/Week

**Focus**: Lightweight context for production maintenance

### Tasks
- [x] Production deployed and verified (2026-03-01)
- [x] Maintain AGENTS.md as single source of operational truth
- [x] Prune legacy sync/Actual Budget artifacts
- [ ] Keep memory-bank concise and current (update as needed)
- [ ] Refresh instructions only when architecture shifts

## 🚧 Blockers

**None**

## ⏭️ Next Steps

1. Update memory-bank entries only when production changes.
2. Keep AGENTS.md aligned with deployment reality.
3. Remove stale docs promptly to reduce noise.

## 📝 Recent Decisions

**2026-03-01**: Production deployed on TrueNAS (10.1.0.99) with Docker compose; Actual Budget service removed.
- Frontend: Astro 5 SSR on port 3003 (internal 3000)
- Backend: FastAPI on port 8002 (internal 8000)
- PostgreSQL (5437), Test DB (5435), Redis (6380)
- Reverse proxy serves https://family.agent-ia.mx

**2026-02**: Deprecated Actual Budget sync stack; all `/api/sync/*` return 410. Budget system now native (`/api/budget/*`).

## 🎯 Success Criteria

- Production services healthy (frontend, backend, db, redis)
- Budget system only (no Actual Budget artifacts)
- Memory-bank trimmed to essentials
- Docs align with AGENTS.md

## 📊 Current Metrics

- **Test Coverage**: ≥70% (last known 74%)
- **Tests Passing**: last run 118/118
- **Services**: 5/5 healthy (per AGENTS.md)
