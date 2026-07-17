# AGENTS.md

**Canonical agent/dev context lives in [CLAUDE.md](CLAUDE.md).** Read that file — it covers architecture, conventions, environments, deploy paths, testing, and reference data. This file exists only so non-Claude tools find an entry point; do not duplicate content here.

Non-negotiables (mirrored from CLAUDE.md):

- **Multi-tenant isolation**: every family-data model carries a non-nullable `family_id` FK; every service query filters by the JWT's `family_id`.
- **Layers**: Routes (HTTP only) → Services (business logic) → SQLAlchemy models. No business logic in routes.
- **Migrations**: Alembic only — never raw SQL schema changes.
- **Tests**: new features need tests; CI runs ruff + full pytest + astro check/build on every PR.
- **Billing**: PayPal only — never introduce Stripe/Mercado Pago.
- **AI**: every LLM call site must be premium-gated (`require_feature("ai_features")`).
- **Prod**: on-prem 10.1.0.91, rootless podman, deploy via `./scripts/deploy-onprem.sh`. Never `sudo podman`.
