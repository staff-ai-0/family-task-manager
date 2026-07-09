# Observability

Lightweight, dependency-free observability for Family Task Manager. This
documents the three probe/scrape endpoints the backend exposes, how to scrape
metrics, and the host-level alert we recommend for the shared on-prem box.

> Scope note: this is deliberately minimal — no `prometheus_client`, no
> Grafana bundled in the repo. A single Prometheus (or any agent that can GET a
> text endpoint) can scrape `/metrics`; full dashboards can come later. See the
> 2026-07-07 launch-gaps audit (`docs/audit/2026-07-07/01-launch-gaps.md`).

## Endpoints

| Path       | Purpose                        | Auth            | Touches DB/Redis |
|------------|--------------------------------|-----------------|------------------|
| `/health`  | Liveness — the process is up   | none            | no               |
| `/ready`   | Readiness — DB + Redis reachable | none          | yes (SELECT 1 + PING) |
| `/metrics` | Prometheus scrape target       | token (see below) | yes (a few COUNTs) |

- `/health` returns `200 {"status":"healthy"}` and never claims dependency
  state. Use it for a liveness probe / uptime ping.
- `/ready` returns `200 {"status":"ready", ...}` when both PostgreSQL and Redis
  answer, else `503 {"status":"degraded", ...}`. Use it for readiness gating and
  a real "is the app actually serving" uptime check.
- `/metrics` returns Prometheus text-exposition (`text/plain; version=0.0.4`).

## `/metrics`

Hand-rolled Prometheus exposition (no `prometheus_client` dependency).
Implemented at `backend/app/api/routes/internal/metrics.py`; counters live in
`backend/app/core/metrics.py`.

### Access control (token-guarded, fail-closed)

The endpoint reuses the internal-service secret `INTERNAL_API_TOKEN` (the same
one the `/api/internal/*` routes use). It **fails closed**: if
`INTERNAL_API_TOKEN` is unset, every request is rejected with `403`. Present the
token via **either** header:

- `Authorization: Bearer <token>`  ← Prometheus `authorization.credentials`
- `X-Internal-Token: <token>`

This guard matters because the public Cloudflare tunnel routes
`api-family.agent-ia.mx` straight at the backend, so `/metrics` is
internet-reachable. **In production you MUST set `INTERNAL_API_TOKEN`** in the
host `.env` (a long random value), otherwise `/metrics` returns `403` to
everyone (safe default) — and the scraper must send that same token.

Defense in depth: prefer to also keep `/metrics` off the public tunnel route
(the tunnel only needs `/` for the frontend and `/api/*` for the app) and scrape
it over the internal podman/host network. The token is the backstop.

### Prometheus scrape config

```yaml
scrape_configs:
  - job_name: family-task-manager
    metrics_path: /metrics
    scheme: https
    # Prometheus sends this as `Authorization: Bearer <credentials>`.
    authorization:
      type: Bearer
      credentials: "<INTERNAL_API_TOKEN value>"
    static_configs:
      - targets: ["api-family.agent-ia.mx"]
    # If scraping over the internal network instead of the public tunnel:
    #   scheme: http
    #   targets: ["family_onprem_backend:8000"]
```

Quick manual check:

```bash
curl -s -H "X-Internal-Token: $INTERNAL_API_TOKEN" http://localhost:8003/metrics
```

### Metrics exposed

| Metric                            | Type    | Meaning |
|-----------------------------------|---------|---------|
| `family_up`                       | gauge   | Always `1` when the app answered the scrape. |
| `family_metrics_db_up`            | gauge   | `1` if the gauge COUNT queries succeeded, `0` if the DB hiccuped (the scrape still returns 200 with zeroed gauges). |
| `family_families_total`           | gauge   | Total families (tenants). |
| `family_active_users`             | gauge   | Users with `is_active = true`. |
| `family_nonfree_subscriptions`    | gauge   | Active subscriptions on a paid (non-free) plan — a proxy for paying tenants. |
| `family_pending_receipt_drafts`   | gauge   | Receipt drafts awaiting human review (`status = pending`) — HITL queue depth. |
| `family_overdue_assignments`      | gauge   | Task assignments currently `OVERDUE`. |
| `family_llm_calls_total`          | counter | Outbound LLM/vision calls this worker made since startup (best-effort). |

Gauges are computed on demand from a handful of `COUNT` queries against a
short-lived session opened directly from `AsyncSessionLocal` (not the pooled
request dependency), so a scraper cannot tie up a pooled connection. Cost is
O(a few indexed COUNTs) per scrape — keep the scrape interval sane (e.g. 30–60s).

### Caveats

- **Per-worker counters.** Prod runs several uvicorn workers, each with its own
  in-process `family_llm_calls_total`. A scrape hits whichever worker answers,
  so the counter is per-worker and best-effort — good for rate/trend, not exact
  totals. It resets to 0 on restart (a normal Prometheus counter reset). The
  gauges are DB-backed and identical across workers.
- **Best-effort LLM counting.** `record_llm_call()` is called at each outbound
  LLM/vision call site (Jarvis, receipt/calendar scanners, recipe import,
  translation, task-proof validator, budget categorizer). It never raises into
  the caller's hot path; a missed increment is acceptable.

## Recommended host-level alerting (from the 2026-07-07 audit)

The single biggest operational risk on the shared on-prem host (10.1.0.91) is
**silent disk exhaustion**: `docker-compose.onprem.yml` has no log rotation, the
`receipt_uploads` volume grows unbounded (gig proofs + receipt images, no
retention/prune job), and nothing alerts on disk pressure. A full disk takes
down PostgreSQL (and every other stack on the box) with no warning.

Minimum viable, in priority order:

1. **Disk-usage alert.** A host-level alert when the filesystem holding the
   podman volumes crosses ~85%. Cheapest form is a cron that emails on
   `df -h`:

   ```bash
   # /etc/cron.hourly/disk-alert (as jc, or a user crontab)
   THRESH=85
   USE=$(df --output=pcent /home | tail -1 | tr -dc '0-9')
   if [ "$USE" -ge "$THRESH" ]; then
     echo "disk at ${USE}% on $(hostname): $(df -h /home | tail -1)" \
       | mail -s "[family] disk ${USE}%" ops@agent-ia.mx
   fi
   ```

   Better: `node_exporter` + the platform repo's monitoring, alerting on
   `node_filesystem_avail_bytes`. Full Prometheus/Grafana can wait past launch.

2. **Log rotation** on the compose services (`logging: driver json-file` with
   `max-size` / `max-file`, as the staging override already sets) so container
   logs can't fill the disk.

3. **Uploads retention/prune.** Pair the disk alert with an orphan-cleanup job
   for proof/receipt images tied to completed/expired assignments (or move
   uploads to object storage). Tracked as a MEDIUM in the audit.

Secondary (already partially covered elsewhere): enable Sentry (`SENTRY_DSN`
is shipped empty in the env template) for error tracking, and add an external
uptime monitor that polls `/ready` so a 2 a.m. outage is noticed before a user
complains.
