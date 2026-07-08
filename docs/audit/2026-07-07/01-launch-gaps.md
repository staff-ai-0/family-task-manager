## prior-audit-delta

SUMMARY: Prior-audit delta is mostly healthy: of the deferred items, B7 (PayPal blocking requests), C1 (gig constraint drift), C2 (double-award race), C3 (dev/prod dep split + CVE pins) and the task-vs-gig unification (Option A shipped, approvals/badge unified, two-currency decision made) are all verifiably closed in current code. Still open: the A3 critical's remnant — 4 AI services (proof validator, calendar scanner, category AI, recipe importer) still make sync no-timeout LLM calls inside async functions that can block the event loop up to 600s; B5 is half-done (Sentry code exists but prod SENTRY_DSN is empty, so error tracking is effectively off for launch, and there is no catch-all exception handler or structured logging); the budget first-account cold-start UX gap deferred in Track D remains; and C7's large files have only grown.

### [HIGH][S] A3 remnant: 4 AI services still call the sync OpenAI client inside async functions with NO timeout (600s SDK default blocks the whole event loop)
file: backend/app/services/task_proof_validator.py
evidence: task_proof_validator.py:105-114, calendar_scanner_service.py:93-102, budget/category_ai_service.py:111-115, recipe_importer.py:94-99 — each instantiates OpenAI(base_url=..., api_key=...) with no timeout kwarg and calls client.chat.completions.create() directly inside an async def; grep for to_thread/run_in_executor in those 4 files = zero hits. Only receipt_scanner_service.py:285 got the full fix (run_in_threadpool + LLM_REQUEST_TIMEOUT_SECONDS). jarvis_service.py:292-304,468-481 has timeout=60 but still calls sync create() un-offloaded per tool hop (12-review-fixes.md logged this as accepted-
fix: Apply the receipt_scanner pattern to all 5 remaining call sites: OpenAI(..., timeout=30-60) plus await run_in_threadpool(lambda: client.chat.completions.create(...)). Proof-photo validation and calendar scan are kid/parent-facing upload paths — one slow LiteLLM response freezes every request on the worker.
verified: real=True — Verified all 4 cited call sites: each instantiates OpenAI() with no timeout kwarg and calls sync client.chat.completions.create() directly inside an async def, with all callers awaiting them on the ev

### [MEDIUM][S] B5 half-open: Sentry code is wired but prod SENTRY_DSN is empty — zero error tracking live; no catch-all exception handler, no structured logging
file: backend/app/main.py
evidence: main.py:34-45 guards sentry_sdk.init on settings.SENTRY_DSN; ssh to prod 10.1.0.91 `grep -c '^SENTRY_DSN=.+' /home/jc/family-task-manager/.env` returned 0 (empty/unset), and both .env.onprem.example:69 and .env.gcp.example:99 ship it blank. exception_handlers.py:102-110 registers only 7 domain exceptions + RateLimitExceeded (main.py:189); grep 'exception_handler(Exception)' across backend/app = zero hits. Logging is still plain-text basicConfig (main.py:27-30); grep for json_logger/structlog = zero hits.
fix: Before public launch, create a Sentry project and set SENTRY_DSN in the prod .env (5-minute config task — the code path already exists). Add the catch-all @app.exception_handler(Exception) so 500s are logged with context; JSON logging is optional on a single podman host.

### [MEDIUM][M] Budget cold-start still open: no way to create the first account outside buried Settings; no first-run onboarding
file: frontend/src/components/FABModal.astro
evidence: FABModal.astro:128-136 renders the account <select> from props with no inline '+ New account' option and throws errAccount (line 18) when empty; grep 'first account|New account|openAccountModal|no accounts' in budget/index.astro, transactions.astro, FABModal.astro = zero hits; grep -rln 'onboard' across frontend/src/pages/budget/ and frontend/src/components/ = zero hits. 11-trackD-progress.md fixed dead links + FAB labels but never the account-create entry (audit HIGH #21); UX waves #80-89 didn't touch it either.
fix: For public launch this is the signup cliff: a new family's first budget action dead-ends. Add an accounts.length===0 empty-state card on /budget/ that opens the account modal inline, and an '+ New account' option in the FAB account dropdown.

### [LOW][M] C7 large-file splits never happened — the flagged files have all GROWN since the audit
file: backend/app/services/task_assignment_service.py
evidence: wc -l today: task_assignment_service.py 1544 (was 1236), budget/allocation_service.py 1122 (was 972), receipt_scanner_service.py 1149 (was 1126), budget/settings.astro 1120, i18n.ts 1030 (was 883). 10-trackC-progress.md line 51 deferred C7 as 'opportunistic when touched' — files were touched repeatedly (gig refactor, UX waves) without splitting.
fix: Not a launch blocker. Set a soft ceiling (e.g. fail CI review checklist above ~1200 lines) and split task_assignment_service along its natural seams (assignment CRUD vs approval vs overdue sweep) next time it's opened.

## security

SUMMARY: Security posture is substantially better than a typical pre-launch codebase: prior audit fixes verified in place (register is parent-only with family_id forced from JWT at auth.py:50-63; uploads served via an authenticated family-scoped route with traversal rejection at uploads.py:27-80), upload handling sniffs magic bytes with hard size caps (core/upload_validation.py), the /mcp endpoint is off by default and uses 256-bit SHA-256-hashed family-scoped tokens, dependencies are actively CVE-managed (PyJWT migration, starlette/python-multipart pins documented in requirements.txt), tenant isolation spot-checks (shopping/meal/dm/calendar services) all filter by family_id, CORS is origin-pinned, and no real secrets are tracked in git. The two launch-blocking gaps are both rate-limiting: the entire slowapi layer is bypassable via spoofed X-Forwarded-For because uvicorn runs with --forwarded-allow-ips="*", and the expensive LLM endpoints (Jarvis chat/stream, calendar scanner) have no rate limit or plan metering at all — unbounded AI spend per Free-tier account. Security headers (HSTS/CSP/X-Frame-Options) are entirely absent.

### [HIGH][S] Rate limiting keyed on client IP is spoofable: uvicorn trusts X-Forwarded-For from any source
file: docker-compose.onprem.yml
evidence: docker-compose.onprem.yml:77 runs uvicorn with `--proxy-headers --forwarded-allow-ips="*"`, and backend/app/core/rate_limiter.py:34-38 keys slowapi on get_remote_address (request.client.host, rewritten from XFF). Cloudflare appends the real IP to the client-supplied X-Forwarded-For list rather than replacing it, and with allow-ips=* uvicorn trusts the whole chain, so the leftmost attacker-chosen entry wins. Every limited endpoint (login/register-family/forgot-password/reset-password at auth.py:76,196,403,421; receipt scan at budget/transactions.py:521) can be brute-forced by rotating a spoofed
fix: Key the limiter on CF-Connecting-IP (set by Cloudflare, not client-forgeable through the tunnel) or restrict --forwarded-allow-ips to the tunnel container subnet, and enable the Redis storage URI in the on-prem .env.
verified: real=True — Confirmed end-to-end: docker-compose.onprem.yml:77 (and the live prod container) run uvicorn with --proxy-headers --forwarded-allow-ips=*; uvicorn 0.27.0's proxy_headers.py returns the leftmost XFF en

### [HIGH][S] Jarvis chat and calendar AI scanner have zero rate limiting and zero plan/usage gating (unbounded LLM spend)
file: backend/app/api/routes/jarvis.py
evidence: Grepped limiter/require_feature/UsageTracking across backend/app/api/routes/jarvis.py, backend/app/services/jarvis_service.py, backend/app/api/routes/calendar.py, backend/app/services/calendar_scanner_service.py — zero hits. Only budget scan-receipt carries AI_LIMIT (budget/transactions.py:521) and premium gating. Jarvis is tool-calling + SSE streaming through LiteLLM; any authenticated parent (Free tier included) can loop requests and run unbounded Anthropic spend or exhaust the shared LiteLLM proxy that other tenants on the box use. [CORRECTED: Calendar AI scanner (calendar.py:190 scan-docum
fix: Add @limiter.limit(AI_LIMIT) to /api/jarvis chat+stream and /api/calendar/scan-document, and meter them via the existing UsageTracking/require_feature machinery (ai_features boolean + per-plan quota) before launch.
verified: real=True — Verified routes and service layers: calendar scan-document truly has zero rate limiting and zero plan/usage gating (only parent role + upload size cap), despite rate_limiter.py's AI_LIMIT comment clai

### [MEDIUM][S] No security headers: HSTS, CSP, X-Frame-Options, X-Content-Type-Options entirely absent
file: frontend/src/middleware.ts
evidence: Grepped 'Strict-Transport|Content-Security-Policy|X-Frame|X-Content-Type' across backend/app and frontend/src — zero hits. The only header set is Cross-Origin-Opener-Policy on /login (middleware.ts:121-127). Nothing in astro.config.mjs or FastAPI middleware; nothing in the repo configures Cloudflare to inject them either.
fix: Add a small header-setting pass in frontend middleware (or a Cloudflare Transform Rule tracked in docs): HSTS, X-Frame-Options DENY (kiosk mode may need frame-ancestors tuning), X-Content-Type-Options nosniff, and a starter CSP; add X-Content-Type-Options to the FileResponse in uploads.py.

### [LOW][S] /api/auth/check-methods is an account-enumeration oracle
file: backend/app/api/routes/auth.py
evidence: auth.py:250-278 returns {has_password, has_google} for any email: unknown emails get false/false, existing accounts get at least one true — a clean existence oracle despite forgot-password (auth.py:402-417) carefully avoiding this. Rate-limited at 10/min, but that limit is bypassable per the XFF finding.
fix: Accept as a deliberate UX trade-off only after fixing the rate-limit bypass; otherwise return has_google only when the account is OAuth-only and add a per-email (not per-IP) throttle.

### [LOW][S] Auth cookies omit SameSite attribute (relies on browser Lax default)
file: frontend/src/lib/auth-cookies.ts
evidence: buildCookie in frontend/src/lib/auth-cookies.ts:7-16 emits Path/HttpOnly/Secure/Max-Age but never SameSite (grep 'SameSite' in that file: only the unused interface field in login.ts). HttpOnly+Secure are correctly set for both tokens (lines 18-24).
fix: Append '; SameSite=Lax' explicitly in buildCookie so CSRF posture does not depend on per-browser defaults.

## compliance-legal

SUMMARY: Compliance is effectively at zero for a public kids-focused launch: the repo contains no privacy policy, terms, or LFPDPPP aviso de privacidad, no consent capture, no cookie disclosure, and no retention/subprocessor documentation. Children can self-register with their own email via family join codes with no age gate or parental-consent step, and kid-generated content (task proof photos, family chat) flows to third-party LLMs undisclosed. There is also no user-facing family deletion or personal-data export, so ARCO/GDPR rights cannot be exercised — findings 1-4 are launch blockers.

### [CRITICAL][M] No privacy policy, terms of service, or Mexico 'Aviso de Privacidad' exists anywhere
file: frontend/src/pages
evidence: Grepped frontend/src (pages, components, layouts) for privacy|privacidad|términos|terminos|terms|aviso — zero hits. frontend/src/pages/ listing confirms no policy pages (only login, register, pricing, help, etc.). LFPDPPP Arts. 15-17 require an aviso de privacidad BEFORE collecting personal data; Google OAuth app verification and PayPal live credentials also require a published privacy policy URL. [CORRECTED: Scope note: the verification covers this repository only; if a policy exists on a separate agent-ia.mx marketing site it is not linked from this app, so the in-app/legal-notice gap (and G
fix: Draft and publish /privacidad (aviso de privacidad LFPDPPP-compliant, naming purposes, ARCO rights, and transfers to subprocessors) and /terminos pages in ES/EN; link from register page and footer; register the URL with Google OAuth and PayPal.
verified: real=True — Repo-wide search (pages, components, public/, backend routes, middleware, docs) found no privacy policy, ToS, or aviso de privacidad page, no consent checkbox on register.astro, and no link to any ext

### [CRITICAL][L] Children can self-register with their own email; no age gate, birthdate, or parental-consent flow exists
file: backend/app/api/routes/auth.py
evidence: backend/app/api/routes/auth.py:77-120 (register_family): anyone with a family join code self-registers 'as the requested role (child/teen/parent) — defaults to CHILD' with their own email/password — no parent approval step. backend/app/schemas/user.py:19 requires EmailStr for all accounts including CHILD. Grepped backend/app/models/user.py for birth|age|edad — zero hits: no birthdate field, so no age verification is even possible. frontend/src/pages/register.astro has no consent/agree checkbox (grep zero hits). [CORRECTED: Accurate, with two minor caveats: joining an existing family requires k
fix: Add a COPPA/LFPDPPP-style flow: collect birthdate at signup, block direct child self-registration (require parent-initiated creation or parent approval of join-code signups), make child email optional, and record verifiable parental consent (timestamp + consenting parent) on child accounts.
verified: real=True — Verified auth.py register_family: with a join code anyone self-registers at a self-chosen role (default CHILD) with immediate token issuance and no approval step; UserBase/RegisterFamilyRequest requir

### [HIGH][M] No user-facing account/family deletion and no personal-data export (ARCO/GDPR rights unfulfillable)
file: backend/app/api/routes/families.py
evidence: backend/app/api/routes/families.py: grep 'delete' — zero hits (no family deletion endpoint at all). backend/app/api/routes/users.py:187 explicitly blocks a parent from deleting their own account ('Cannot delete your own account'), so a sole-parent family can never leave. Grepped users.py/families.py/auth.py for 'export' — zero hits; only budget/export.py exists (budget data only, not chat/DMs/photos/pet/points). [CORRECTED: Slightly overstated on one point: a parent CAN hard-delete OTHER family members (DELETE /api/users/{user_id}, cascade). The real gap is: no self-deletion, no whole-family d
fix: Add a parent-initiated 'delete my family' endpoint that cascades all family data (chat, DMs, uploads, budget, subscriptions) and a whole-family personal-data export endpoint, satisfying LFPDPPP ARCO cancellation and GDPR Arts. 17/20 for non-MX users.
verified: real=True — Verified all three evidence points: families.py has zero delete routes (FamilyService.delete_family at family_service.py:220 exists but is unwired, and the repo's own 2026-06-04 audit confirms its cas

### [HIGH][M] Kid-generated content (proof photos, family chat) flows to third-party LLMs with zero disclosure or consent
file: backend/app/services/task_proof_validator.py
evidence: backend/app/services/task_proof_validator.py:77-115 base64-encodes kid-uploaded task proof photos and sends them to a vision model via LiteLLM. backend/app/mcp/adapters_chat.py exposes family chat (including children's messages) as Jarvis MCP tools, so kids' messages become LLM prompt content. Also calendar_scanner_service.py and receipt_scanner_service.py send user images to Claude. No privacy policy exists to disclose any of this (finding 1), and no consent is captured anywhere. [CORRECTED: Minor scope corrections only: the default third-party recipient for photos/chat is Google Gemini (gemi
fix: Disclose AI processing and subprocessors (Anthropic via LiteLLM) in the aviso de privacidad, gate AI features touching child content behind an explicit parental opt-in flag on the family, and confirm zero-data-retention terms with the LLM provider.
verified: real=True — Verified task_proof_validator.py:77-126 base64-encodes kid proof photos and sends them via LiteLLM to RECEIPT_MODEL (default gemini-2.5-flash, config.py:193), invoked from task_assignment_service.py:7

### [MEDIUM][S] No consent capture at registration and no marketing-email opt-in/out mechanism
file: frontend/src/pages/register.astro
evidence: frontend/src/pages/register.astro: grep accept|agree|acepto|consent — zero hits (no terms checkbox). Grepped backend/app/services/email_service.py and backend/app/models/user.py for marketing|newsletter|unsubscribe|opt — zero hits: no consent flags stored and no unsubscribe path for any non-transactional email via Resend/SMTP.
fix: Add a 'I accept the terms and aviso de privacidad' checkbox to register/register-family (store timestamp + policy version on the user row), and a marketing_consent boolean plus unsubscribe link before sending any non-transactional email.

### [MEDIUM][M] No data retention policy or subprocessor/DPA documentation in the repo
file: docs
evidence: Grepped backend/app recursively for retention|retención — zero hits; chat messages, DMs, uploaded photos (gig proofs, receipts) and analytics snapshots are retained indefinitely with no purge job. No docs/ file lists subprocessors (Anthropic/LiteLLM, PayPal, Resend, Google OAuth/SMTP, Cloudflare) or their DPA status.
fix: Write a retention schedule (e.g., purge chat/uploads N months after family deletion, purge unverified accounts), implement it as a scheduled job, and maintain a subprocessor list with signed DPAs referenced from the privacy policy.

### [LOW][S] No cookie consent or cookie disclosure
file: frontend/src
evidence: Grepped frontend/src for cookie.consent|cookieconsent|consent — zero hits; no banner component exists. Auth session cookies are strictly-necessary (low risk), but the app is globally reachable and Cloudflare sets its own cookies, which EU/ePrivacy visitors must at minimum be informed about.
fix: Add a cookies section to the privacy policy describing the strictly-necessary auth cookies and Cloudflare cookies; a full consent banner is only needed if analytics/marketing cookies are ever added.

## observability-ops

SUMMARY: Observability is thin but not zero: there are real liveness (/health) and readiness (/ready with DB+Redis checks) endpoints, compose healthchecks, deploy-time smoke checks, and backend Sentry wiring — but Sentry ships disabled (empty SENTRY_DSN in the env template), the frontend has no error tracking at all, and nothing external polls or alerts, so a 2am outage is only discovered when a user complains. On a single shared podman host, the biggest operational risks are silent disk exhaustion (no log rotation in docker-compose.onprem.yml, unbounded uploads volume, no disk alerting) and zero metrics/request-correlation for diagnosing anything after the fact.

### [CRITICAL][S] No uptime monitoring or alerting — nobody is paged when prod goes down
file: scripts/deploy-onprem.sh
evidence: Grepped repo/scripts/compose for uptime-kuma, pagerduty, alert, cron pings: only hits are the deploy-time smoke check in scripts/deploy-onprem.sh:140-141 (curl of family.agent-ia.mx + /health, runs only during deploy). The good /ready endpoint (backend/app/main.py:273-311, checks DB+Redis, returns 503 when degraded) has no consumer — the compose healthcheck (docker-compose.onprem.yml backend healthcheck) hits /health (liveness only) and restart:unless-stopped just restarts silently. [CORRECTED: Slight reframe, not a refutation: fleet-wide Prometheus/Alertmanager with email alerting DOES exist 
fix: Stand up an external uptime monitor (Cloudflare Health Checks, UptimeRobot, or Uptime Kuma on another host) polling https://api-family.agent-ia.mx/ready and the frontend, with email/Telegram alerting to the operator. A single Cloudflare Health Check gets this done in an hour.
verified: real=True — Confirmed: deploy-onprem.sh's public curl is deploy-time only and doesn't even fail on non-200; the onprem compose healthcheck hits /health (liveness) and nothing consumes /ready; no uptime-kuma/pager

### [HIGH][S] Frontend has zero error tracking; backend Sentry is wired but disabled by default
file: backend/app/main.py
evidence: Backend: sentry-sdk in backend/requirements.txt:85, init gated on SENTRY_DSN at backend/app/main.py:34-44, but .env.onprem.example:69 ships SENTRY_DSN= (empty) so prod is off unless someone filled it — nothing enforces it. Frontend: grepped 'sentry' across frontend/src, frontend/package.json, astro.config.mjs — zero hits. Astro SSR crashes and client-side JS errors (the whole optimistic-mutate UI layer) vanish untracked. [CORRECTED: Claim is accurate but understated: it is not just "off unless someone filled it" — the actual production .env on 10.1.0.91 has no SENTRY_DSN entry, so backend erro
fix: Set SENTRY_DSN in the prod .env (verify on 10.1.0.91) and add @sentry/astro (or a minimal window.onerror → backend endpoint) for the frontend so client and SSR errors are captured before public users hit them.
verified: real=True — Verified main.py:34-44 gating, config.py empty-string default, empty SENTRY_DSN in both .env templates, and zero sentry/vendor/error-handler hits across frontend src, package.json, and astro.config.mj

### [MEDIUM][M] No metrics or dashboards at all — no visibility into latency, error rate, resource usage
file: docker-compose.onprem.yml
evidence: Grepped backend, frontend, and compose files for prometheus, statsd, opentelemetry, datadog, grafana: zero hits outside backend/.venv transitive deps. No /metrics endpoint, no node_exporter/cadvisor in docker-compose.onprem.yml. The only performance signal is Sentry traces_sample_rate=0.1 (backend/app/main.py:41), which is off while SENTRY_DSN is empty.
fix: Minimum viable: enable Sentry performance (comes free with finding 2) plus a host-level disk/CPU/memory alert (node_exporter + the platform repo's monitoring, or even a cron that emails on df -h > 85%). Full Prometheus/Grafana can wait past launch.

### [MEDIUM][M] Upload volume grows unbounded with no pruning and no disk-full protection
file: backend/app/api/routes/uploads.py
evidence: receipt_uploads volume mounted at /app/uploads (docker-compose.onprem.yml backend volumes). Gig proofs and receipt images written there by backend/app/api/routes/uploads.py; backend/app/jobs/ contains only subscription_sweep.py — grepped 'prune|cleanup' across jobs and upload code: no retention/cleanup logic anywhere. Single shared host; public-launch users uploading photos will fill the disk with no cap, quota, or alert.
fix: Add a retention/orphan-cleanup job for proof images tied to completed/expired assignments (or move to object storage), and pair with the disk-usage alert from the metrics finding.

### [MEDIUM][S] Plain-text logs, no request IDs — cannot correlate a user report to backend errors across 2 workers
file: backend/app/main.py
evidence: logging.basicConfig with '%(asctime)s - %(name)s - %(levelname)s - %(message)s' at backend/app/main.py:27-30; grepped 'X-Request-ID|request_id|correlation' across backend/app: zero hits. No JSON logging, no per-request ID middleware; uvicorn runs --workers 2 so interleaved plain-text lines are the only trace of a failed request.
fix: Add a small middleware that generates/propagates X-Request-ID, injects it into a logging filter, and returns it in responses; optionally switch to JSON logs (python-json-logger) so grep/jq works during incidents.

### [LOW][S] PII (user emails) logged at INFO on every OAuth login and email send
file: backend/app/api/routes/oauth.py
evidence: backend/app/api/routes/oauth.py:50 and :57 log full email + family_id on every Google login; backend/app/services/email_service.py:509,800,803 log recipient emails. With no log rotation these accumulate indefinitely on a shared host — a compliance and breach-surface issue for a public consumer SaaS in Mexico (LFPDPPP).
fix: Log user_id only (it is already logged) and mask emails (j***@gmail.com) in log lines; sweep with a grep for 'email=' in logger calls.

### [LOW][S] No slow-query logging and no in-app LLM cost/token visibility
file: backend/app/services/jarvis_service.py
evidence: Grepped backend/app/core/database.py and config.py for slow/echo/log_min_duration: no hits — postgres:15-alpine runs with defaults, so a slow query at 2am is invisible. Jarvis LLM calls (backend/app/services/jarvis_service.py) log no token usage or cost; only receipt_scan counts are metered via UsageTracking. Mitigated partially by everything routing through the on-prem LiteLLM proxy, which can track spend centrally — but per-family attribution is absent.
fix: Set log_min_duration_statement=500ms via postgres command args in the compose file; log response.usage tokens per Jarvis call with family_id so runaway LLM spend per family is detectable.

## data-safety

SUMMARY: Backup basics are in place and verified live: a user-level systemd timer on 10.1.0.91 pg_dumps daily at 03:30 with 14-day retention, a typed-confirmation restore script exists, Redis runs with AOF persistence, and the 78-migration Alembic chain is healthy (single head, all downgrades present). The launch-blocking gap is durability: every backup sits on the same disk as the live database with zero offsite copy (an explicit TODO in backup-db.sh), the uploads volume is never backed up, and the restore script's defaults still target the decommissioned GCP/Docker path and have never been drill-tested against the canonical podman host. Secondary concerns: hard-delete-everywhere outside the budget module (family deletion cascades a whole tenant irrecoverably) and a 24-hour RPO for financial data.

### [CRITICAL][S] No offsite backup copy — every backup lives on the same disk as the database
file: scripts/backup-db.sh
evidence: backup-db.sh:46-48 has an explicit TODO ('Off-VM durability ... intentionally a TODO', gsutil line commented out). Verified on prod host 10.1.0.91: dumps exist only at /home/jc/family-task-manager/backups/scheduled/ (48K daily, timer fired 12h ago) — same /dev/mapper/rhel_10-home filesystem that holds the podman volumes with the live postgres data. Grepped scripts/ + docs/ for gsutil|rclone|restic|borg|s3: only the TODO comment. `crontab -l` on the host: empty. Disk failure, ransomware, or house fire loses the DB and 100% of its backups simultaneously. [CORRECTED: Slightly overstated on total 
fix: Add an offsite push to backup-db.sh (rclone to B2/GCS/R2, or even scp to another box + the founder's Mac) and alert if the upload fails. This is the single highest-value data-safety fix before public launch.
verified: real=True — Confirmed on both repo and prod host: backup-db.sh (repo and deployed copy on 10.1.0.91) has the gsutil upload commented out as a TODO; daily dumps land only in /home/jc/family-task-manager/backups/sc

### [HIGH][S] Uploads volume (gig proof photos, receipt images) is not backed up at all
file: scripts/backup-db.sh
evidence: backup-db.sh only runs pg_dump; zero references to `receipt_uploads` or /app/uploads in any backup script (grepped scripts/). docker-compose.onprem.yml:68 mounts receipt_uploads:/app/uploads; deploy-onprem.sh:91-94 creates/chowns it but never backs it up. DB rows (BudgetReceiptDraft.image_url, gig proof paths) reference these files, so a host rebuild from DB dumps leaves dangling image references. Currently small (3.5M, 2 files on prod) but grows with every paying family. [CORRECTED: Scope refinement: receipt images attached to committed transactions are designed to persist to GCS (GCS_RECEIPT
fix: Extend backup-db.sh to tar the receipt_uploads volume mountpoint (podman volume inspect --format '{{.Mountpoint}}') alongside the SQL dump, and include it in the offsite push.
verified: real=True — Confirmed: backup-db.sh is pg_dump-only, deploy-onprem.sh only creates/chowns receipt_uploads, and the live 10.1.0.91 host has only the family-onprem-backup.timer (DB dumps) — no cron, timer, or scrip

### [HIGH][S] restore-db.sh defaults are wrong for the canonical prod host and a restore drill has never been run
file: scripts/restore-db.sh
evidence: restore-db.sh:16-17 defaults COMPOSE_FILE=docker-compose.gcp.yml and COMPOSE_CMD='sudo docker compose'. On 10.1.0.91 (rootless podman, no Docker, hard no-sudo-podman rule) running it as documented in scripts/systemd/README.md:33 (`./scripts/restore-db.sh backups/scheduled/...`) fails or worse. Only the backup .service sets the podman env overrides — there is no on-prem restore wrapper. Grepped logs/SESSION-WORKLOG.md + docs/ for restore-drill evidence: the script was written in PR #40 ('typed confirm') but no record of it ever being executed against a scheduled dump; the only real restore exer
fix: Fix the defaults (or add an onprem wrapper that sets COMPOSE_CMD='podman compose' COMPOSE_FILE=docker-compose.onprem.yml), then run one timed restore drill into a scratch DB from the latest scheduled dump and record the result in the README.
verified: real=True — Verified scripts/restore-db.sh:15-17 defaults are GCP (docker-compose.gcp.yml, sudo docker compose), scripts/systemd/README.md:33 documents the bare invocation, and no on-prem restore wrapper or drill

### [MEDIUM][M] Hard deletes everywhere outside budget — family delete cascades all tenant data with no soft-delete or grace period
file: backend/app/services/family_service.py
evidence: family_service.py:219-223 `delete_family` does `await db.delete(family)` with cascade to all related data; auth_service.py:173 hard-deletes users; same pattern in calendar_service.py:218, shopping_service.py:123/202, meal_service.py:135/277, gig_claim_service.py:223/291, base_service.py:139. Grepped models/ for deleted_at/is_deleted outside budget.py: zero hits — soft delete + recycle_bin exist only for budget tables (budget.py:36,58,112,187). In a multi-tenant DB, recovering one family's accidental deletion means restoring the whole-cluster dump (losing up to 24h for every other family).
fix: Add soft-delete + retention window at least for the catastrophic objects (Family, User) — e.g. deleted_at + a purge job after 30 days — before opening self-serve account deletion to the public. Jarvis's HITL gate mitigates AI-initiated deletes but not the API/UI path.

### [MEDIUM][S] RPO is 24 hours with 14-day retention and no PITR — thin for an app holding family finances
file: scripts/systemd/family-onprem-backup.timer
evidence: family-onprem-backup.timer:6 OnCalendar daily 03:30; backup-db.sh:18 RETENTION_DAYS=14. Confirmed live on 10.1.0.91 (last dump 2026-07-07 03:30). No WAL archiving/pgBackRest/wal-g anywhere (grepped repo: zero hits). A crash at 03:00 loses a full day of budget transactions, points, and cash ledger entries; a corruption noticed after 2 weeks is unrecoverable.
fix: Cheapest step: bump timer to every 6h and retention to 30d (dumps are 48K). If budget/cash usage grows post-launch, move to WAL-based PITR (pgBackRest to the offsite target from finding 1).

### [LOW][S] Redis allkeys-lru eviction can silently drop session keys despite AOF persistence
file: docker-compose.onprem.yml
evidence: docker-compose.onprem.yml:39: `redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru`. AOF persistence is correctly enabled (good), but allkeys-lru evicts any key — including active sessions — under memory pressure, and the eviction is durable. Impact is forced re-logins, not data loss, so low severity.
fix: Switch to `volatile-lru` (sessions already carry TTLs) or accept as-is; document that Redis holds no unrecoverable data.

## ci-cd-testing

SUMMARY: A substantial test asset base exists (134 backend test files, 1096 test functions; 30+ Playwright specs) but absolutely nothing executes any of it automatically: there is no CI system of any kind, and the canonical deploy script runs zero tests, lint, or type checks before recreating the production pod. For a public SaaS launch, the single highest-leverage move is a minimal GitHub Actions pipeline (backend pytest against a postgres service + frontend build/astro check) gating merges to main, plus an explicit rollback story in deploy-onprem.sh.

### [CRITICAL][M] No CI pipeline of any kind — nothing catches a broken commit before prod deploy
file: .github
evidence: .github/ contains only copilot-instructions.md, instructions/, memory-bank — no workflows/ dir. Checked absence of .gitlab-ci.yml, .circleci/, Jenkinsfile, .drone.yml (all missing). scripts/deploy-onprem.sh:30-41 pre-flight only checks compose file existence, podman reachability, and rootless GraphRoot; grep for pytest/npm run build/astro check/tsc in deploy-onprem.sh and deploy-gcp.sh: zero hits. The 1096 backend test functions across 134 files are only ever run manually. [CORRECTED: No CI pipeline exists and tests are never run automatically before deploy — that part is real and critical. Bu
fix: Add one GitHub Actions workflow on push/PR to main: (1) backend job — postgres:15 + redis:7 services, pip install, pytest; (2) frontend job — npm ci + astro build + astro check. Make deploy-onprem.sh refuse (or warn) when HEAD lacks a green run.
verified: real=True — Confirmed no CI of any kind: .github has no workflows/, no gitlab/circle/jenkins/drone configs, no git hooks/husky/pre-commit, and neither deploy script runs pytest or any test suite — the 1096 backen

### [HIGH][M] Deploy has no rollback path: untagged in-place image builds, irreversible migrations, down-before-verify
file: scripts/deploy-onprem.sh
evidence: deploy-onprem.sh:69 builds images in place with no version tag (old image is overwritten); :104 runs `alembic upgrade head` with no dry-run/downgrade step; :116-123 does `podman compose down` then `up -d` — if the new image fails health checks (:127-136) prod is already down with no previous image to fall back to. grep for 'rollback|downgrade' in deploy-onprem.sh and restore-db.sh: zero hits. Only recovery asset is the pre-deploy pg_dump (:44-49), which does not restore application code. [CORRECTED: Two overstatements: (1) migrations run BEFORE the down (lines 96-106, old backend keeps serving
fix: Tag each build (e.g. git SHA) and keep the previous tag; on health-check failure, automatically `up` the prior tag. Document/script the DB-restore + prior-image rollback as one command.
verified: real=True — Verified deploy-onprem.sh: line 69 untagged in-place build (old image left as dangling <none>), line 104 alembic upgrade with no downgrade step, lines 116-123 down-then-up with health checks only afte

### [HIGH][M] Playwright e2e suite (30+ specs) is never run by anything — local-only, no schedule, excluded from deploys
file: e2e-tests/playwright.config.js
evidence: playwright.config.js baseURL hardcoded to http://localhost:3003 (dev stack only); deploy-onprem.sh:58 rsync-excludes e2e-tests/ entirely; no CI or cron invokes `npm run test`. e2e-tests/ contains ~28 .spec.js files (auth, budget, gigs, jarvis, chat, kiosk, etc.) plus committed test-results/ and playwright-report/ artifacts, indicating ad-hoc manual runs only. [CORRECTED: Playwright e2e suite (26 spec files, ~25 active after testIgnore) is never run by any automation: baseURL hardcoded to the local dev stack, deploy scripts (both onprem and gcp) rsync-exclude e2e-tests/, and no CI, cron, or scr
fix: Run a small smoke subset (login + dashboard + one budget flow) in CI against the compose dev stack, and a post-deploy smoke against https://family.agent-ia.mx with a dedicated test account. Parameterize baseURL via env var.
verified: real=True — Verified playwright.config.js baseURL is hardcoded to http://localhost:3003, deploy-onprem.sh:58 (and deploy-gcp.sh:237-239) rsync-exclude e2e-tests/, and there is no CI (.github has no workflows/), n

### [MEDIUM][S] Frontend has zero quality gates: no lint config, no typecheck script, @astrojs/check installed but never invoked
file: frontend/package.json
evidence: frontend/package.json scripts are only dev/build/preview/astro — no `check` or `lint` script despite @astrojs/check@^0.9.9 and typescript@^5.9.3 in devDependencies. No eslint config anywhere in frontend/ (glob .eslintrc*/eslint.config* returned nothing). tsconfig.json exists but `astro check`/`tsc` appear in no script or deploy path.
fix: Add "check": "astro check" to package.json and run it in the CI frontend job alongside `astro build`. This is near-free since the tooling is already installed.

### [MEDIUM][S] Backend lint/type tooling declared but enforced nowhere (no pre-commit, no hooks, no CI)
file: backend/requirements-dev.txt
evidence: requirements-dev.txt:12-14 pins black==24.1.1, flake8==7.0.0, mypy==1.8.0, but there is no pyproject.toml/setup.cfg/.ruff.toml config, no .pre-commit-config.yaml, no .husky/, and .git/hooks contains only samples. The tools can only be run by hand and have no config to run consistently.
fix: Pick one linter (ruff replaces black+flake8 in one tool), add a minimal pyproject.toml config, and wire it into the CI backend job. Defer mypy strictness until after launch.

### [MEDIUM][M] No staging environment: docker-compose.stage.yml is stale fiction referencing decommissioned architecture
file: docker-compose.stage.yml
evidence: docker-compose.stage.yml header says 'Infrastructure services only (Database, Redis, Actual Budget Server) — Application services run via PM2' — Actual Budget was decommissioned in Phase 10 per CLAUDE.md, and nothing in the repo uses PM2. No script references this file (grep 'stage' in scripts/*.sh only hits vault secret names for a fam-stage.a-ai4all.com domain that is not the current infra). First place new code meets real prod-like infra is production itself.
fix: Either delete docker-compose.stage.yml to stop it misleading, or (better, pre-launch) stand up a real staging compose project on 10.1.0.91 with a separate DB and run the e2e smoke there before prod deploys.

### [LOW][S] No dependency update process; backend requirements mix pins and open ranges, making prod builds non-reproducible
file: backend/requirements.txt
evidence: No .github/dependabot.yml or renovate config (checked .github/ listing). requirements.txt has 33 requirement lines mixing exact pins with floating ranges (e.g. starlette>=0.40.0,<0.42.0, openai>=1.50.0, pymupdf>=1.24.0, google-cloud-storage>=2.18) — each prod image build can resolve different versions. Project memory already records an incident class: 'dev container masks requirements.txt resolution failures that only break clean prod builds'.
fix: Generate a fully-pinned lock (pip-compile from a requirements.in) and build prod images from the lock; enable Dependabot for pip + npm with weekly PRs so security bumps arrive through the (new) CI gate.

## performance-scaling

SUMMARY: Mostly hardened for its size — pagination caps, SSE with short-lived sessions, upload byte caps, and LLM timeouts are all in place — but one systemic defect dominates: 5 of 6 LLM call sites use the synchronous OpenAI client directly inside async handlers with only 2 uvicorn workers, so a handful of concurrent Jarvis/AI requests can stall the entire app for up to 60s per LLM hop. With that fixed, the single-box architecture should carry roughly 300-500 active families (~1-2k users); the next things to break in order are the 2s-per-connection SSE DB polling (Postgres query load at ~500+ concurrent open chat tabs) and missing composite (family_id, date/created_at) indexes as per-family row counts grow. Without the event-loop fix, the app visibly degrades at just tens of concurrent users whenever AI features are in use.

### [CRITICAL][S] Sync OpenAI client blocks the event loop at 5 LLM call sites (Jarvis, calendar scan, recipe import, proof validator, category AI)
file: backend/app/services/jarvis_service.py
evidence: jarvis_service.py:304 and :481 call client.chat.completions.create() (sync OpenAI, timeout=60.0 at :295/:471) directly inside async defs — same at calendar_scanner_service.py:102 (inside async def at :81), recipe_importer.py:99, task_proof_validator.py:114, budget/category_ai_service.py:115. Only receipt_scanner_service.py:285 wraps the call in run_in_threadpool. docker-compose.onprem.yml:77 runs uvicorn with --workers 2, so 2 concurrent Jarvis chats freeze ALL requests (API + SSE heartbeats) on both workers for up to 60s per tool-calling hop (MAX_TOOL_HOPS loop multiplies this). [CORRECTED: C
fix: Wrap all five call sites in run_in_threadpool (copy the receipt_scanner pattern) or switch to AsyncOpenAI. This is the single highest-leverage perf fix before launch.
verified: real=True — Verified all 5 cited sites: sync OpenAI client.chat.completions.create() is called directly inside async defs at jarvis_service.py:304/:481 (loop of up to 5 hops, MAX_TOOL_HOPS=4), calendar_scanner_se

### [MEDIUM][S] No retry/circuit-breaker on LiteLLM — an outage makes every AI request hang the full 60s timeout
file: backend/app/services/jarvis_service.py
evidence: grep for retry/backoff/circuit across jarvis_service.py and receipt_scanner_service.py: zero code hits (only a comment about a cron retry sweep at receipt_scanner_service.py:857). Clients are constructed per-request with a single timeout (jarvis_service.py:292-296, receipt_scanner_service.py:255-259); no connect-timeout separation, no max_retries=0/health short-circuit. Combined with the sync-client finding, a LiteLLM outage means each attempt occupies a worker/event-loop for 60s.
fix: Set a short connect timeout (e.g. httpx.Timeout(connect=3, read=60)), max_retries=1, and a cheap in-process circuit breaker (skip LLM calls for N seconds after consecutive failures) returning a fast 503 to the UI.

### [MEDIUM][M] Chat/DM realtime is 2-second DB polling per open SSE connection — no Redis pub/sub despite Redis being deployed
file: backend/app/services/family_chat_service.py
evidence: family_chat_service.py:19 STREAM_WINDOW_SECONDS=30, :226-251 loop opens a fresh session and runs a SELECT every poll; dm_service.py:21-22 STREAM_POLL_SECONDS=2.0, same loop at :110-136. Redis usage grep shows only rate_limiter, scheduler_lock, fx_service cache, webhook dedup — no pub/sub for chat. Each open chat/DM tab = 0.5 queries/sec + pool checkout; 1,000 concurrent tabs = ~500 QPS of poll queries against the shared Postgres.
fix: Fine for launch (correctly avoids pinning pool connections). When concurrent connections approach several hundred, move to Redis pub/sub or Postgres LISTEN/NOTIFY fan-out; alternatively raise poll interval to 3-5s as a one-line stopgap.

### [MEDIUM][S] No composite (family_id, date/created_at) indexes on the hottest tables — single-column indexes only
file: backend/app/models/budget.py
evidence: budget.py:169-187 BudgetTransaction has separate index=True on family_id, account_id, date, payee_id, category_id, deleted_at but no Index((family_id, date)) — grep 'Index(' across app/models hits only reward_goal.py:45 and gig.py:90. family_chat.py has family_id indexed (:25) but created_at (:33) unindexed, while the SSE poll query filters family_id + created_at > cursor ORDER BY created_at every 2s per connection (family_chat_service.py:228-236). task_assignment.py relies on single-column indexes for family_id/due_date list queries.
fix: Add composite indexes via one alembic migration: budget_transactions(family_id, date DESC), family_chat_messages(family_id, created_at), task_assignments(family_id, due_date). Cheap insurance; Postgres bitmap-AND covers today's row counts but plan/latency degrades as families accumulate years of transactions.

### [LOW][M] Proof/receipt images served full-size (up to 5MB) with no thumbnailing, through a double proxy hop
file: backend/app/api/routes/uploads.py
evidence: uploads.py:80 returns FileResponse(path, Cache-Control: private, max-age=300) with no resize step; grep for thumbnail/resize/Image.open across routes/gigs.py and routes/uploads.py: zero hits. Uploads capped at 5MB (task_assignments.py:189,211 read_upload_capped(MAX_PROOF_BYTES)) but stored and served as-is. Every image transits backend FileResponse -> Astro SSR proxy (/uploads/gig-proofs/[file].ts) -> cloudflared; a parent approval queue with 10 phone photos can push ~50MB through the single box per page view, and private caching defeats Cloudflare edge cache.
fix: Generate a ~200px WebP thumbnail at upload time (Pillow, in threadpool) and serve it in list views; keep the original for detail view. Consider longer max-age since filenames are immutable UUIDs.

### [LOW][S] PDF rasterization (PyMuPDF, up to 3000px) runs on the event loop before the threadpool offload
file: backend/app/services/budget/receipt_scanner_service.py
evidence: receipt_scanner_service.py:248-250: _pdf_first_page_to_png(image_bytes) is called synchronously inside the async scan path; only the subsequent LLM call (:283-285) is wrapped in run_in_threadpool. Rendering a full-res scanned page at zoom (comment at :135 mentions 4032x3024 camera frames) is a CPU-bound stall of roughly 0.5-2s that freezes one of the 2 workers, delaying SSE heartbeats and API responses during every PDF receipt scan.
fix: Move the _pdf_first_page_to_png call inside the same run_in_threadpool block (or its own await run_in_threadpool).

### [LOW][S] No container resource limits; DB pool ceiling (60 conns across 2 workers) undocumented against shared-box Postgres
file: docker-compose.onprem.yml
evidence: grep mem_limit/cpus/deploy: in docker-compose.onprem.yml: zero hits — backend/frontend/postgres/redis run uncapped on a shared box also hosting school-admin/medical/platform/vLLM. database.py:10-12 sets pool_size=10, max_overflow=20 per worker x 2 workers = up to 60 connections against Postgres default max_connections=100 (own container, so OK, but SSE poll churn plus scheduler jobs consume from the same pool). Redis is capped (compose :39 --maxmemory 256mb allkeys-lru) — note allkeys-lru will evict scheduler locks/rate-limit keys under memory pressure.
fix: Add mem_limit/cpus to backend and postgres services; switch Redis to volatile-lru (or noeviction) so lock/rate-limit keys aren't silently evicted; document the 60-connection pool ceiling.

## product-completeness

SUMMARY: The core funnel is in better shape than typical pre-launch: real bilingual landing page, self-serve register with family creation/join codes/invitations, complete password-reset flow with anti-enumeration, an onboarding checklist + tour with funnel analytics (backend/app/api/routes/onboarding.py), bilingual help center linked from the welcome email, and self-serve subscription cancel. The fatal gaps are on the operational/compliance side: no way for a customer to delete their account or family, no operator admin tooling whatsoever, no support contact anywhere, unenforced email verification, and a demo credential on the login page that doesn't actually exist in the seed data.

### [HIGH][M] No self-serve account or family deletion
file: backend/app/api/routes/users.py
evidence: users.py:187 explicitly raises ValidationException("Cannot delete your own account") for parents; FamilyService.delete_family exists (backend/app/services/family_service.py:219) but grep 'delete_family' across backend/app shows zero route callers. No frontend page under parent/settings offers account/family deletion.
fix: Add a parent-only 'delete my family' flow (confirm + password re-auth) that calls delete_family and cascades, plus self-deletion for the last parent. Required for Mexico's LFPDPPP/ARCO rights before public launch.
verified: real=True — Verified users.py:184-187 blocks self-deletion for parents; DELETE /me does not exist; FamilyService.delete_family (family_service.py:219) has zero callers anywhere in backend/app (no route, no MCP to

### [HIGH][L] No operator admin back-office at all
file: backend/app/api/routes/internal/a2a_retry.py
evidence: Grepped 'is_admin|superuser|SUPERADMIN|back.office|impersonat' across backend/app: zero hits. routes/internal/ contains only a2a_retry.py. Only operator tooling is raw psql on the prod box. [CORRECTED: Claim is accurate as to no admin back-office/role/impersonation; only the evidence detail "only operator tooling is raw psql" is slightly overstated — there are also ops CLI scripts (scripts/backup-db.sh, restore-db.sh, deploy-onprem.sh, backend/scripts/setup_paypal_plans.py, seed scripts), but none constitute an operator back-office.]
fix: Build a minimal internal admin surface (family lookup by email, subscription state, usage counters, disable/delete family) gated by a separate admin role or IP-restricted internal route. Refunds can stay in the PayPal dashboard but you need the lookup side.
verified: real=True — Confirmed: UserRole enum (backend/app/models/user.py) is only PARENT/CHILD/TEEN with no operator/admin role; grep for is_admin/superuser/impersonate is empty across backend and frontend; routes/intern

### [MEDIUM][S] Email verification exists but is never enforced
file: backend/app/api/routes/auth.py
evidence: POST /verify-email and resend exist (auth.py:365-391), but the only read of user.email_verified in request paths is the resend guard (auth.py:390). Grep 'email_verified' in dependencies.py and auth_service login path: no gate — unverified accounts get full app access and receive all transactional email.
fix: Gate at least invitations/outbound-email-triggering actions (or login after N days) on email_verified, with a persistent 'verify your email' banner. Prevents spam signups and mail to unowned addresses.

### [MEDIUM][S] Demo credentials on the public login page are wrong and demo mode is just a shared writable account
file: frontend/src/pages/login.astro
evidence: login.astro:275 advertises 'Demo: parent@demo.com / password123', but seed_data.py:107 creates mom@demo.com (no parent@demo.com anywhere in backend), and the prod demo family uses a different password per ops notes — so the advertised demo login fails. Even if fixed, all prospects share one mutable account.
fix: Fix or remove the advertised credential now; for launch, replace with a read-only demo (per-session ephemeral demo family, or nightly-reset seeded family with a rotating known password).

### [MEDIUM][S] No support/contact channel anywhere in the product
file: frontend/src/pages/help.astro
evidence: Grepped 'mailto|support@|soporte@|contact' across frontend/src, docs/USER_GUIDE_ES.md and USER_GUIDE_EN.md: zero hits. Help center pages (/help, /ayuda) render the guides but give users no way to reach the operator — notable for a paid product with PayPal billing.
fix: Add a support email (e.g. soporte@agent-ia.mx) in the landing footer, help pages, and billing/settings pages; optionally a simple contact form posting to the existing Resend/SMTP pipeline.

### [MEDIUM][S] No custom 404/500 error pages
file: frontend/src/pages
evidence: find frontend/src -name '404*' -o -name '500*' -o -name '*error*': zero results. Astro serves its bare default error pages in production for any bad URL or SSR failure — unbranded, English-only.
fix: Add frontend/src/pages/404.astro and 500.astro using the existing Layout/brand components with ES/EN copy and a link back to /dashboard.

### [LOW][M] No whole-family data export (only budget export)
file: backend/app/api/routes/budget/export.py
evidence: budget/export.py:22 exports budget data as ZIP, but grep for any family-wide export across routes shows nothing covering tasks, points history, gigs, calendar, chat, meals, pet — no data-portability endpoint for the rest of the app.
fix: Add a parent-only 'export my family data' endpoint (JSON/ZIP dump per domain). Pairs with the deletion flow for ARCO/GDPR-style portability.

### [LOW][S] Landing CTAs send new users to /login instead of /register
file: frontend/src/pages/index.astro
evidence: index.astro:33 ('Comenzar gratis'/'Get started') and :53 ('Comenzar ahora'/'Start now') both href="/login"; register.astro exists with a full self-serve family-create/join-code flow, reachable only via the small link at login.astro:251.
fix: Point primary landing CTAs at /register to remove one step of friction in the signup funnel.

## mobile-pwa-push

SUMMARY: Mobile/PWA foundation is substantially healthier than typical at this stage: complete manifest with maskable icons and shortcuts, a service worker with offline shell + web-push handlers, install banner (including an iOS A2HS tip), iOS meta tags, a VAPID web-push backend (pywebpush) with dead-endpoint pruning and a per-user rate limit, and broad trigger coverage (task approve/reject, gig pending/approved/rejected, chat, DMs, rewards, pet, calendar, shopping) plus a kiosk page for the tablet story. The launch-relevant gaps are the missing "task assigned / chores due" trigger in the core chore loop, no native app path for App Store presence, and a few push-reliability/deploy-template details.

### [HIGH][M] No push or notification when a chore is assigned or due — the core loop is silent
file: backend/app/models/notification.py
evidence: NotificationType enum (backend/app/models/notification.py:17-27) has GIG_APPROVED/REJECTED/PENDING, rewards, pet, calendar, shopping — no TASK_ASSIGNED or TASK_DUE. Grep for 'TASK_ASSIGNED|task_assigned' across backend/app: zero hits. Assignment generation in task_assignment_service.py (create paths around lines 195-240) creates TaskAssignment rows with no NotificationService/PushService call; the only sweeps in backend/app/main.py are overdue-penalty, pet decay, pup snapshot, Jarvis schedules, subscription sweep — no daily 'chores due today' reminder job. [CORRECTED: Real, but "the core loop 
fix: Add TASK_ASSIGNED push when assignments are generated/claimed, and a scheduled morning 'you have N chores today' reminder per kid (the scheduler-leader infra in main.py already exists). For a chores app this is the single highest-value notification.
verified: real=True — Verified all cited evidence: NotificationType (notification.py:17-27) has no TASK_ASSIGNED/TASK_DUE, grep for task_assigned/task_due is empty, the sole TaskAssignment creation site (_new_assignment, t

### [HIGH][L] No native app / Capacitor project — App Store and Play Store absence for a phone-first category
file: frontend/package-lock.json
evidence: Grep for 'capacitor' across the repo hits only frontend/package-lock.json:7080 — @capacitor/preferences as an optional peerDependency of a transitive package, not a dependency. No ios/, android/, capacitor.config.* anywhere. On iOS the only install path is the manual Safari share-sheet A2HS tip banner (frontend/src/layouts/Layout.astro:227-231), and web push there requires iOS 16.4+ AND prior install.
fix: For public launch, plan a Capacitor wrap: feasible with the Astro SSR frontend via a remote-URL shell (server.url pointing at family.agent-ia.mx) plus native push (FCM/APNs) instead of web push; a full offline-bundled SPA port is not required. Treat as post-MVP-launch but pre-growth work.
verified: real=True — Verified: the sole 'capacitor' hit is an optional peerDependency of transitive package unstorage in frontend/package-lock.json:7080 (not in package.json); no ios/, android/, capacitor.config.*, Xcode/

### [MEDIUM][S] VAPID keys missing from .env.onprem.example — push silently no-ops on any fresh environment
file: .env.onprem.example
evidence: grep -i vapid .env.onprem.example → no matches (also absent from docker-compose.onprem.yml environment block; backend relies on env_file .env). Defaults are empty strings (backend/app/core/config.py:78-80); PushService.send_to_user then skips with only a log warning (push_service.py '_vapid_configured') and GET /api/push/public-key returns 503 (routes/push.py:33-37), so the Enable button just shows 'Error'.
fix: Add VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY/VAPID_CLAIM_EMAIL (with the generation command already documented in config.py:74) to .env.onprem.example, and verify the current prod .env on 10.1.0.91 has them set via GET /api/push/health.

### [MEDIUM][S] Service worker has no pushsubscriptionchange handler — browser-rotated subscriptions die silently
file: frontend/public/sw.js
evidence: grep -c pushsubscriptionchange frontend/public/sw.js → 0. sw.js handles only install/activate/fetch/push/notificationclick (lines 17-108). When Chrome/FCM rotates an endpoint, the old one starts returning 410 and gets pruned server-side (push_service.py dead-endpoint logic), leaving the user with zero subscriptions and no UI signal until they manually re-click 'Enable push notifications' (rendered only on /dashboard and /parent).
fix: Add a pushsubscriptionchange listener in sw.js that re-subscribes with the stored VAPID key and POSTs to /api/push/subscribe; optionally have the app re-assert the subscription on page load when Notification.permission === 'granted'.

### [MEDIUM][S] iOS Safari (browser tab) shows dead-end 'Push not supported' instead of directing users to install first
file: frontend/src/components/EnablePushButton.astro
evidence: EnablePushButton.astro:32-35 — if PushManager is absent (true in non-installed iOS Safari) the button is disabled with 'Notificaciones no soportadas', with no hint that installing the PWA (iOS 16.4+) enables push. The separate iOS install banner (Layout.astro:228-231) is unrelated, fires once 3s after load, and auto-dismisses after 15s (Layout.astro:218).
fix: In the unsupported branch, detect iOS + non-standalone (navigator.standalone / display-mode media query) and show 'Instala la app desde Compartir → Agregar a inicio para activar notificaciones' instead of a generic unsupported message.

### [LOW][S] Manifest is hard-coded English for a Spanish-primary market
file: frontend/public/manifest.webmanifest
evidence: manifest.webmanifest:2-13,22-25 — "lang": "en", name "Family Task Manager", description "Chores, rewards, budget — together.", shortcuts "Today's chores"/"Rewards" all English. Static file, single locale; installed-app name, splash and long-press shortcuts render in English for Mexican users. (App UI itself is bilingual; apple-mobile-web-app-title in Head.astro:33 is also English-only.)
fix: Since the manifest is a static public asset, either default it to Spanish (Mexico-first) or serve it via an Astro endpoint that localizes name/description/shortcuts from the user's language cookie.

## billing-subscriptions

SUMMARY: Billing plumbing is better than typical pre-launch (verified webhook signatures via PayPal's verify endpoint, Redis event dedup with commit-then-mark ordering, idempotent state transitions, an atomic UPSERT metering primitive, a daily downgrade sweep). But the dunning path is broken end-to-end: a single failed payment instantly downgrades the family to Free (the advertised 3-day grace is a docstring, not code), no event restores them after a successful retry, and no email tells them anything — that is exactly what breaks first with a real customer. Second-order risks: /checkout can clobber an active subscription and orphan the old PayPal sub (double-billing), and there is no reconciliation cron plus no handling of SUSPENDED/EXPIRED/refund events, so any missed webhook drifts state permanently.

### [CRITICAL][M] Payment failure = instant downgrade to Free with no recovery path (the 'what breaks first' answer)
file: backend/app/services/subscription_state.py
evidence: subscription_state.py:72-86 sets status='payment_failed' on BILLING.SUBSCRIPTION.PAYMENT.FAILED and the docstring claims a '3-day grace period', but core/premium.py:117 get_family_plan only honors status in ('active','past_due') — 'past_due' is never set anywhere (grepped, zero writers) and 'payment_failed' is excluded, so the family drops to Free the moment the webhook lands. payment_failure_at is written but never read by any job or gate (grepped app/ and scripts/, only the setter). Recovery: PayPal signals a successful retry with PAYMENT.SALE.COMPLETED, which subscriptions_webhook.py:126-14
fix: Treat 'payment_failed' as entitled during a real grace window (add it to get_family_plan with a payment_failure_at + N days check enforced by the daily sweep), and handle PAYMENT.SALE.COMPLETED to flip payment_failed→active and extend current_period_end.
verified: real=True — Verified every element: apply_payment_failed sets status='payment_failed' which premium.py:117 excludes (only 'active'/'past_due' honored), 'past_due' has zero writers, payment_failure_at is write-onl

### [HIGH][M] /checkout clobbers an active paid subscription before payment, orphaning the old PayPal subscription
file: backend/app/api/routes/subscriptions.py
evidence: subscriptions.py:180-200 upserts the family's single FamilySubscription row: an existing row — including one with status='active' — gets status='pending', a new plan_id, and its paypal_subscription_id overwritten with the new checkout's ID, before the user has paid. Since get_family_plan only matches active/past_due, merely opening (or abandoning) an upgrade checkout downgrades a paying customer to Free, and the previous PayPal subscription ID is lost without ever calling cancel_subscription — PayPal keeps billing the old sub with no local record (double billing on completed upgrade).
fix: On checkout for a family with an active sub, keep the current row untouched and stage the pending PayPal sub separately (or only mutate the row inside /activate after payment), and cancel the old PayPal subscription at PayPal when the new one activates.
verified: real=True — Verified subscriptions.py:180-200 upserts the family's single FamilySubscription with no status guard, setting status='pending' and overwriting paypal_subscription_id pre-payment; premium.py get_famil

### [HIGH][M] No PayPal state reconciliation and narrow webhook coverage — permanent drift on suspend/expire/refund and stale period_end
file: backend/app/api/routes/subscriptions_webhook.py
evidence: Webhook handles only 3 event types (subscriptions_webhook.py:126-147); BILLING.SUBSCRIPTION.SUSPENDED, .EXPIRED, PAYMENT.SALE.REFUNDED/REVERSED are ignored. Renewals never extend current_period_end (apply_activated at subscription_state.py:40-41 no-ops when already active; PAYMENT.SALE.COMPLETED unhandled), so period_end stays at activation+30d forever. The only cron is jobs/subscription_sweep.py:26-32, which downgrades solely rows with cancel_at_period_end=True — grepped for any PayPalService.get_subscription re-sync job: none. A missed webhook (24h retry window expired during an outage) mean
fix: Add a daily reconciliation pass in the sweep that calls PayPalService.get_subscription for each non-free sub and converges local status/current_period_end; handle SUSPENDED and PAYMENT.SALE.COMPLETED events at minimum.
verified: real=True — Verified all cited lines: webhook handles only 3 event types (subscriptions_webhook.py:126-147), apply_activated no-ops when already active so current_period_end never advances (subscription_state.py:

### [MEDIUM][S] family_member limit bypassed via join-code registration
file: backend/app/api/routes/auth.py
evidence: Only the invitation path is gated (invitations.py:61 require_feature('family_member',...)). The public /api/auth register endpoint with data.family_code (auth.py:105-155) adds a user to an existing family with no require_feature or member-count check — anyone with the join code grows the family past the Free plan's max_family_members=4 without limit.
fix: Call require_feature('family_member', ...) (or an equivalent count check against the plan limit) in the join-by-code branch of register before creating the user.

### [MEDIUM][M] Zero billing emails: no dunning notice, no payment receipt, no cancellation confirmation
file: backend/app/services/email_service.py
evidence: email_service.py exposes only send_verification_email, send_password_reset_email, send_welcome_email/_if_not_sent, send_invitation_email (lines 535-814). Grepped subscriptions.py, subscriptions_webhook.py, subscription_state.py for 'email': zero hits. A customer whose payment fails gets silently downgraded (see finding 1) with no notification to fix their payment method, and paying customers get no receipt/invoice for any charge.
fix: Send at minimum a payment-failed dunning email (with PayPal update link) from apply_payment_failed and a subscription-activated/cancelled confirmation; PayPal's own emails partially cover receipts but the dunning notice is on you.

### [LOW][S] Metered gating is read-then-write racy on budget transactions and receipt scans; the atomic path exists but is only used for gigs
file: backend/app/api/routes/budget/transactions.py
evidence: transactions.py:90-97 does require_feature('budget_transaction') (a read) then a separate UsageService.increment; same pattern at :321-340 and for receipt_scan at :551-558. UsageService.try_increment_within_limit (usage_service.py:100-168) was built precisely to close this race — its docstring names the require_feature→increment race — but grep shows only task_assignment_service.py:1127 (gig_completion) uses it. Concurrent requests can each pass the limit check and both increment past the cap.
fix: Switch the budget_transaction and receipt_scan routes to try_increment_within_limit. Low severity at family scale (limits overshoot by a handful, not a revenue hole), but cheap to fix before launch.

### [LOW][M] Plans priced in USD only for a Mexico-first product
file: backend/scripts/setup_paypal_plans.py
evidence: setup_paypal_plans.py:105-123 creates all PayPal billing plans with currency_code 'USD' (fixed_price, setup_fee). SubscriptionPlan model stores price_monthly_cents/price_annual_cents with no currency column (models/subscription.py:30-31). Grepped repo for 'MXN' in billing code: only the gig economy (1pt=$1MXN), not subscriptions.
fix: Decide the launch currency deliberately: either create MXN-denominated PayPal plans (PayPal MX supports MXN) or at minimum label prices as USD in the subscription UI to avoid Mexican customers assuming pesos.

### [LOW][S] 7-day trial defined at PayPal but invisible to the app (trial_end_at never populated)
file: backend/app/services/subscription_state.py
evidence: setup_paypal_plans.py:75 provisions plans 'with 7-day trial', and FamilySubscription.trial_end_at exists (models/subscription.py:61-63), but the only writer is apply_activated's optional trial_end_at param (subscription_state.py:48-49) which no caller ever passes — webhook (subscriptions_webhook.py:135-139) and /activate (subscriptions.py:272-276) both omit it. The app cannot show trial status or warn before first charge; period_end is also set to now+30d at activation, ignoring the trial phase.
fix: In the ACTIVATED handler, parse resource.billing_info cycle data (or call get_subscription) to populate trial_end_at and a correct current_period_end; surface trial state in /current for the UI.

## i18n-a11y

SUMMARY: i18n foundations are better than the debt note suggests — both ES and EN exist essentially everywhere on the frontend (700 inline ternaries across 71 files do the job, ugly but bilingual), html lang is set dynamically, emails and Jarvis prompts localize via user.preferred_lang, and login syncs the lang cookie from the account. The two launch-blocking gaps for a Spanish-first market are (1) backend in-app/push notifications that hardcode a random mix of English and Spanish strings ignoring preferred_lang, and (2) inconsistent anonymous-locale defaults (landing=es, login/app=en) with no Accept-Language fallback. A11y is moderately healthy (all imgs have alt, real buttons everywhere, modals have Escape+aria-modal) but ~70% of form labels lack for= association, and white-on-coral badges fail AA contrast.

### [HIGH][M] Backend notification/push strings are hardcoded in a random mix of English and Spanish, ignoring user.preferred_lang
file: backend/app/services/notification_service.py
evidence: NotificationService.create takes literal title/body from 9 caller services with no lang parameter. task_assignment_service.py:1177 sends English ('❌ Gig rejected', "'...' approved by parent."); gig_claim_service.py:172-196 sends Spanish ('📋 Gig por revisar', 'aprobada al instante'). Same user receives both languages in the same feed/push regardless of preferred_lang. Contrast: email_service.py:172-175 does localize via _t(key, lang), so the infra pattern exists but notifications never adopted it. [CORRECTED: The gap is real but the "never adopted" framing is overstated: a minority of notificat
fix: Add a keyed translation table (mirroring email_service's _COPY/_t) to NotificationService, resolve recipient's preferred_lang at create time, and migrate the ~30 call sites across the 9 services to keys instead of literals.
verified: real=True — Verified the cited code: NotificationService.create (backend/app/services/notification_service.py:16-74) takes literal title/body with no lang parameter and passes them straight to web-push; task_assi

### [HIGH][S] Default locale for anonymous visitors is inconsistent (es vs en per page) with zero Accept-Language detection — Spanish-first users land in English mid-funnel
file: frontend/src/layouts/Layout.astro
evidence: index.astro:10, register.astro:8, accept-invitation.astro:9 default `?? "es"`, but Layout.astro:13, login.astro:6, forgot-password.astro:4, kiosk.astro:16 and ~15 other pages default `?? "en"`. Grepped 'Accept-Language' across frontend/src and backend/app: zero hits. A first-time Mexican visitor sees a Spanish landing page, clicks login, and gets English. [CORRECTED: Real but narrower than implied for authenticated pages: api/auth/login.ts:96-117 syncs the lang cookie from the account's preferred_lang at login (and register.ts carries it into the account), so the ~40 "en"-default authenticated
fix: Centralize locale resolution in middleware.ts: cookie → Accept-Language sniff → 'es' (Mexico-first default), and remove per-page `?? "en"` fallbacks. One small middleware change plus a mechanical sweep.
verified: real=True — Verified all cited lines verbatim: index/register/accept-invitation default "es" while login/forgot-password/reset-password/verify-email/kiosk/Layout and ~40 more default "en", and there is zero Accep

### [MEDIUM][L] 700 inline `lang === 'es'` ternaries across 71 files vs only 23 files using lib/i18n.ts — translation drift and no path to a 3rd locale
file: frontend/src/lib/i18n.ts
evidence: grep `(lang|locale|language)\s*===?\s*['\"]es['\"]` over pages/components/layouts: 700 occurrences in 71 of 115 .astro files (worst: register.astro 39, accept-invitation.astro 36, dashboard.astro 33, budget/scan-receipt.astro 33). Only 23 files import lib/i18n. This matches the known-debt memory note; both languages ARE present, so it's maintainability/consistency risk rather than a user-visible gap today.
fix: Don't block launch on a full refactor; instead freeze the pattern (lint rule banning new `=== 'es'` ternaries) and migrate opportunistically page-by-page into i18n.ts keys.

### [MEDIUM][S] Form labels not programmatically associated with inputs — 92 of 130 <label> elements lack for= (including the core budget add/edit-transaction form)
file: frontend/src/pages/budget/transactions.astro
evidence: grep: 130 `<label` across pages/components, only 38 with `for=`. transactions.astro:392-428: Amount/Date/Payee/Category/Account labels are bare `<label class=...>` siblings of inputs that already have ids (edit-amount, edit-date, edit-payee...), so screen readers announce unlabeled fields. Positives found: 0 <img> without alt, 0 clickable div/span onclick, 8 aria-modal/role=dialog usages, Escape handling in 6 sheet/modal components.
fix: Add for= attributes matching the existing input ids (or wrap inputs in the label). Mostly mechanical; prioritize register, login, budget transaction, and task-template forms.

### [LOW][S] White text on brand-coral (#FF8A65) fails WCAG AA contrast (~2.2:1) on notification badges and a CTA button
file: frontend/src/components/BottomNav.astro
evidence: global.css:11 defines --color-brand-coral: #FF8A65; white-on-#FF8A65 computes to ~2.2:1 (AA needs 4.5:1, 3:1 large). 5 occurrences of `bg-brand-coral text-white` (non-deep): BottomNav.astro:82,95 (unread-count badges at 10px font), MoreSheet.astro:111, shopping.astro:175, parent/rewards.astro:176 (button). The -deep variants (#E96A45 ≈3.1:1) are used elsewhere and are closer to passing.
fix: Swap these 5 spots to bg-brand-coral-deep (or darker) with white text, or coral background with brand-ink text; verify with a contrast checker.

### [LOW][S] Money formatting is hand-rolled `$X.toFixed(2)` in 21 places (no thousands separators, no MXN locale) with only one Intl.NumberFormat usage
file: frontend/src/pages/parent/payouts.astro
evidence: grep toFixed(2): 21 hits (payouts.astro:18 `$${(cents/100).toFixed(2)}`, dashboard.astro:110, profile.astro:104, budget/scan-receipt.astro:255). Only AssignFundsModal.astro:158 uses Intl.NumberFormat('es-MX', {currency:'MXN'}). $10000.00 renders without grouping ($10,000.00 expected in es-MX). Dates are healthier: toLocaleDateString consistently branches es-MX/en-US (profile.astro:107, calendar.astro:115, meals.astro:79).
fix: Export a single formatMXN(cents, lang) helper from lib/helpers.ts wrapping Intl.NumberFormat and replace the 21 call sites.

