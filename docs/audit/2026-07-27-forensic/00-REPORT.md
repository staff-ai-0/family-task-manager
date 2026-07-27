# Forensic Code Review — 2026-07-27

Scope requested: code quality · industry best practices · tech-debt elimination · code dedup · enhancement opportunities · UX enhancement · production-readiness for launch.

Method: 7 parallel dimension reviewers over `backend/app` (279 py files, 87 services, 64 route modules) and `frontend/src` (91 pages, 49 components), each required to cite verified `file:line` evidence. 59 raw findings → deduped → all 15 `high` findings put through an adversarial verifier whose job was to **refute** them. 9 verified by agent, 6 verified by hand after a session-limit interruption. Raw agent output preserved in `raw-findings.json`.

Baseline: prior audits `2026-06-04`, `2026-07-02-ux`, `2026-07-07`, `2026-07-22-forensic`. Reviewers were told what was already fixed or already tracked, so nothing below is a re-report — except where explicitly marked "still open".

## Verification outcome

| Claimed | Confirmed as-is | Confirmed, severity lowered | Refuted |
|---|---|---|---|
| 15 high | 8 | 7 → medium | 0 |

No finding was fully refuted, but the verifier corrected 7 severities and killed the framing of two (details inline). Take the corrected severity, not the original.

---

## P0 — fix before launch

### 1. Every receipt image scanned on prod since cutover has been silently discarded
`backend/app/services/budget/receipt_scanner_service.py:862-888` · **high** · effort medium

Receipt-image persistence is GCS-only, wrapped in a swallow-all `try/except`. Prod is on-prem — no GCS credentials exist there. The verifier ran `google.auth.default()` inside `family_onprem_backend` and got `DefaultCredentialsError`, then queried prod: **15 `receipt_scan` usage rows in July 2026 (latest 2026-07-10, post-cutover) and 0 of 73 `budget_transactions` with `receipt_image_path` set.** The serving endpoint (`api/routes/budget/transactions.py:232-266`) also reads GCS only, and the frontend hides the thumbnail when the path is NULL — so nothing ever surfaced the failure.

Users are permanently losing the original image of financial records they believe they archived. Local-volume storage already exists for gig proofs and receipt drafts (`settings.UPLOADS_ROOT`, covered by backup).

Fix: add a local-volume backend behind the same upload/download/delete interface, select on `GCS_RECEIPT_BUCKET` presence, and stop swallowing a permanently-failing upload. Or drop the GCS path and the `google-cloud-storage` dep entirely.

### 2. Month budget view double-counts categorized income
`backend/app/api/routes/budget/month.py:102` and `:150-151` · **high** · effort small

`totals.income` is seeded from an account-level sum of all positive on-budget transactions (no category filter), then income-group activity is added on top. Any positive transaction assigned an income category counts twice.

Not latent: every family is seeded with an `Ingresos` group (`default_categories.py:41`), and deposits get income categories automatically from `category_ai_service.py:198` and the bank-email-matcher intake (`bank_sync.py:241-243`). `frontend/src/pages/budget/index.astro:64` renders `totals.income` directly — the dashboard income card inflates up to 2×. Git history shows commit `284e030d` added the account-level query intending to replace the legacy `+=`, and left both live. No test asserts this number. `ready_to_assign` is computed separately, so envelope math is unaffected — display-level, but it is the headline figure of a finance app.

Fix: delete the `+=` branch, wrap the scalar in `int()` (missing Decimal cast), add a test asserting a single categorized income transaction is counted once.

### 3. `/api/oauth/google` is unauthenticated, unthrottled, and blocks the event loop
`backend/app/api/routes/oauth.py:50` · **high** · effort small

The verifier could not refute this and found the core claim understated.

- No rate limit. Every sibling auth route is decorated (`auth.py:78,94,170,301,318,338,356`); `oauth.py` imports the limiter nowhere. No default/application limits are configured on the `Limiter` (`core/rate_limiter.py:56-60`), no router-level dependency, no middleware fallback. Nothing throttles this route at any layer — and it creates users and whole families.
- Blocking I/O on the loop. `google_oauth_service.py:123` calls sync `id_token.verify_oauth2_token` inside `async def`. In the installed library, `_fetch_certs` runs **before** `jwt.decode` and is uncached — so a garbage token still triggers an outbound HTTPS GET (no valid Google credential needed to trigger it), and `google/auth/transport/requests.py` sets a **120 s** default timeout. With `--workers 2` on a box shared with school-admin/medical/platform, and this repo's documented fragile egress DNS on the .91 netavark net, one slow googleapis.com can pin a worker's whole event loop.
- Unbounded join-code oracle: invalid code → 400, valid code → 403 `approval_pending`. Codes are 6 chars over 31 symbols. The password join path is throttled; this one is not, and one Google ID token replays for its full validity hour.

Fix: `@limiter.limit(AUTH_LIMIT)` on both routes in `oauth.py`, wrap verification in `asyncio.to_thread` (the PayPal webhook already does exactly this), cache Google certs. Also add `clientIpHeaders(request)` to `frontend/src/pages/api/oauth/google.ts:24-27` — it currently forwards only `Content-Type`, so the limiter would otherwise key every browser into one bucket.

### 4. Deploy "smoke check" cannot fail the deploy; the tunnel is in no health gate
`scripts/deploy-onprem.sh:168` · **high** · effort small

`verify_public()` curls the two public URLs and only `echo`s the HTTP code — never asserts, never returns non-zero — and runs after the rollback decision is already made. `wait_healthy` polls `db/redis/backend/frontend` only; the `tunnel:` service in `docker-compose.onprem.yml:129-151` has no `healthcheck:` and is not in the wait list.

So the failure mode this host has already produced — cloudflared HTTP 530 after the egress-net DNS pin is lost — passes cleanly: all containers healthy, script prints "Deploy complete", public site down. CLAUDE.md advertises the deploy as smoke-checked.

Fix: assert `<400` on both URLs with a short retry loop for tunnel reconnect lag, exit non-zero with a loud banner. Do not auto-rollback there — healthy containers plus a dead public URL is an ingress problem, not an image problem. Add a tunnel healthcheck.

### 5. Access-token JWT serialized into page HTML on 6 surfaces
`frontend/src/pages/parent/settings/a2a.astro:59` (+5) · **high** · effort medium

Verified by hand. Six surfaces read the httpOnly `access_token` cookie server-side and inline the raw JWT into the delivered HTML via `define:vars`: `parent/settings/a2a.astro:59`, `budget/scan-receipt.astro:238`, `budget/transactions.astro:606`, `budget/settings.astro:578`, `components/TaskCreateModal.astro:411` (prop from `parent/tasks.astro:558`), `components/RecycleBinTable.astro:191`. (`reset-password.astro` and `kiosk.astro` also appear in the grep but carry a reset token and a kiosk device token — different, out of scope.)

httpOnly exists precisely so XSS cannot exfiltrate the credential; embedding it in the DOM hands it back. Stolen from HTML it is usable outside the browser until expiry, whereas the cookie is not.

The embed is unnecessary: `frontend/src/pages/api/**/[...path].ts:32` injects `Authorization` from the cookie whenever the client omits it. Fix: drop `token` from those `define:vars`/props and delete the client-side `Bearer` headers (`a2a.astro:65`, `scan-receipt.astro:301,460`, `transactions.astro:684,699,892,930`, `settings.astro:635,662`, `subscription/activate.astro:18`). Verify the multipart upload path still authenticates after the change.

---

## P1 — high value, next sprint

### Correctness / security

**Family suspension is bypassed on all four non-session auth paths** — `kiosk_service.py:337-338` and `:216-217`, `jarvis_mcp_token_service.py:61-69`, `budget/bank_sync.py:41-49` all check `Family.deleted_at` but never `Family.is_active`; `set_family_active` flips the flag without revoking tokens. The design spec promises suspension "locks out all members immediately"; `tests/test_family_suspension.py` covers login/refresh/Google only. Verifier downgraded **high → medium**: no path crosses a tenant boundary, the full-CRUD `/mcp` path needs `JARVIS_MCP_HTTP_ENABLED=true` which is off and absent from prod config, and the live paths are a read-only self-view plus the operator's own agent. Still a broken contract. Fix: one shared `assert_family_usable(family)` at all four sites + a test per path. `bank_sync` is also missing the `deleted_at` guard entirely.

**Google sign-in links an existing password account by email without requiring `email_verified`** — `google_oauth_service.py:243-255` attaches the presenting Google identity to any account matching on email, even one with a `password_hash` or already bound to a different `oauth_id`, then mints tokens with that account's role and `family_id`. `email_verified` is read only to upgrade our own flag. Classic pre-hijacking pattern. Verifier downgraded **high → medium**: `aud` is validated against our own client IDs, so Google itself must issue the identity; for @gmail.com (the real prod population) `email_verified` is always true and duplicate addresses can't exist, so the attack needs Workspace control of the victim's domain — an attacker who already has an equivalent path via password reset. Fix anyway; it is a few lines and the surrounding code is otherwise careful about exactly this class.

**Scheduler leader election fails open with `--workers 2`** — `core/scheduler_lock.py:74` returns `leader=True` on **any** Redis exception. Prod runs two workers (`docker-compose.onprem.yml:95`). A Redis blip while both workers boot — realistic during the scoped `down`/`up` when redis may still be starting — makes both leaders, and every cron fires twice concurrently, including `_family_bank_payday_sweep` and `_recurring_post_sweep`, which move family money. Given this project's July double-pay incident history, worth closing. Fix: gate fail-open behind an env var defaulting off when workers > 1, or retry-with-backoff for ~30 s before deciding; check the renew Lua result and shut down the local scheduler when the lock is lost.

**Budget backup import trusts arbitrary foreign keys from the uploaded ZIP** — `budget/export_service.py:191` rebuilds rows with `model_cls(**item_dict)`, overriding only `family_id`. Primary keys and every FK (`account_id`, `category_id`, `payee_id`, `group_id`, `transfer_account_id`) come verbatim from the untrusted file, and the constraints point at global tables, so family A can insert a row referencing family B's category. Only path in the budget domain that skips ownership validation. Fix: drop client `id`s, remap intra-archive FKs through an old→new dict, reject unresolvable references, whitelist accepted keys per model.

**Zip bomb in the same import** — `export_service.py:153` calls `zf.read()` on the member in one shot; the only cap is 25 MB on the *compressed* upload. DEFLATE reaches ~1000:1. Parent role only, no premium gate. Fix: check `zf.getinfo(...).file_size` and total/ratio before reading.

**`/api/meals/recipes/import` has no rate limit and fetches user-supplied URLs server-side** — `api/routes/meals.py:111`. Every other LLM route carries `@limiter.limit(AI_LIMIT)`; this one has only the premium gate, so one paid account can hammer LiteLLM from one IP. It compounds: `recipe_importer.py:80-87` fetches the URL with `follow_redirects=True` and only a scheme check — no private-IP guard — making it an unlimited SSRF probe into the LAN and internal container networks from the backend's vantage point. Fix: add the limiter, reject private/link-local resolutions before fetching.

**Budget-vs-actual report subqueries omit `family_id`** — `api/routes/budget/reports.py:129`. Two correlated scalar subqueries filter by `category_id` + date only, relying on the outer query's family filter plus the write-path guarantee. Currently sound, so defense-in-depth, but it violates the repo's hard rule. Fix: add the predicate to both (columns exist).

**`PointTransaction` has no `family_id`** — `models/point_transaction.py:32`. The core points ledger violates the stated schema rule; every `PointsService` aggregate (`:289-296`, `:299-308`, `reward_service.py:456-467`) scopes by `user_id` alone. Safe today only because callers resolve the user through `get_family_user` first — the entire points economy's tenancy rests on caller discipline instead of the data layer. Fix: migration adding backfilled non-nullable `family_id` + thread it through the service signatures.

**Pooled DB sessions held idle-in-transaction across LLM calls** — `receipt_scanner_service.py:532` opens a transaction then awaits a 60 s vision call with no commit; `jarvis_service.py:583-724` is worse: SELECTs open the transaction, then up to 5 sequential 60 s completions (`MAX_TOOL_HOPS=4`) hold the connection ~5 min. The streaming paths were fixed for exactly this (`family_chat_service.py:383-386` documents the pool-exhaustion → app-wide 502 incident); these non-stream paths were missed. Verifier downgraded **high → medium**: pool is 30/worker not 15, both endpoints are paid-gated and rate-limited at 30/hour per IP, and holds are bounded by request duration rather than accumulating passively like the SSE bug. Fix: commit and release before the LLM segment, re-acquire after.

**Jarvis `/chat` maps every `ValidationError` to HTTP 502** — `api/routes/jarvis.py:79`. Empty message (user error), daily cap reached (quota), and upstream LLM failure all collapse into 502 Bad Gateway. Kids hitting the cap see a service outage, and any 5xx-based alerting counts routine quota events as incidents. Fix: distinct `UpstreamAIError` → 502, plain `ValidationError` → 400, cap → 429.

**Operator actions leave no audit row on unexpected exception types** — `services/admin/admin_action_service.py:570,651,+1`. Three of ten actions narrow their catch (`except HTTPException` / `(HTTPException, FamilyAppException)`), so a plain DB error escapes the `_record_failure` path the module docstring promises. Fix: widen to `except Exception`, keep the re-raise behavior `set_user_active` already uses.

**a2a bank-sync HMAC has no timestamp or nonce** — `api/routes/budget/bank_sync.py:53`. Comparison is correct (`compare_digest`) but the signed message has no expiry and no binding to the endpoint, so a captured request replays forever. Impact limited (writes are idempotent, TLS terminates at the CF edge). Fix: sign an `X-A2A-Timestamp` + method + path, reject skew > 5 min, track recent signatures in Redis.

### Testing gaps that let money bugs ship green

**`DeduplicateService` has zero tests** (`budget/dedup_service.py`, 77 statements, 0 % coverage) — verified by hand: `grep -rl DeduplicateService backend/tests` returns nothing; the seven "dedup" matches in tests are unrelated (PayPal webhook dedup, CSV import). It soft-deletes the loser of each duplicate pair and transfers `receipt_image_path` to the winner, reachable at `POST /api/budget/transactions/deduplicate` with **`dry_run` defaulting to `False`** (`transactions.py:196`). Richness scoring, the both-have-images skip, the 1 % tolerance, and the path transfer are all unverified.

**`TransferService` at 16.7 % with zero direct tests** — verified: `grep -rn "TransferService\|budget/transfers" backend/tests` returns 0. `transfer_between_accounts` creates paired ledger transactions; a sign error or an unpaired write would corrupt account balances family-wide with nothing failing in CI. `test_cover_overspending.py` tests the *AllocationService* method, not this one. Do this before Jarvis MCP exposes transfer tools.

**CI never tests against the migration-produced schema** — verified: CI runs `alembic upgrade head` + a `downgrade -1` round-trip (`ci.yml:101-103`), then `conftest.py:92` drops everything and rebuilds from `Base.metadata.create_all`. The whole ~1980-test suite runs against the ORM schema; no `alembic check` / `compare_metadata` exists anywhere. A hand-written migration missing a column, index, or enum value passes the round-trip **and** the full suite, and first fails when `deploy-onprem.sh` runs alembic against prod. Fix: one CI step running `alembic check` (or a pytest asserting an empty `compare_metadata` diff) after upgrade.

**Playwright e2e (30 specs) never runs in CI** — `e2e-tests/playwright.config.js`. Wired only to a manually-started local stack. Combined with this project's documented stale-image problem, the suite only proves anything when someone remembers to rebuild first. Frontend script islands and middleware are structurally invisible to CI (`astro check` is types-only). Fix: a third CI job running a tagged `@smoke` subset per PR, full suite nightly.

**Zero e2e coverage for the admin console, bank, pet, meals, budget import** — the six `/admin/*` operator pages merged yesterday in PR #163 have no spec at all (`kiosk-admin.spec.js` is the kiosk device, not the operator console). `pricing.spec.js` asserts only a redirect and that the plan table renders. Priority: `admin.spec.js` (superadmin login → directory renders → one bounded write lands in the audit view), then `bank.spec.js`, then `budget-import.spec.js`.

**Frontend has no unit tests at all** — `frontend/package.json` has no test script or framework. `middleware.ts` carries the CSRF origin check, transparent token refresh, CSP headers, and module-bounce logic; its only test is the e2e spec that never runs. The CSRF check could be inverted and every automated signal would stay green. Fix: vitest over the pure helpers, wired into the frontend CI job — far cheaper than e2e-in-CI.

**New admin tests reintroduce the local-date `week_of` pattern PR #130 eliminated** — `tests/test_admin_actions.py:733` and `:877` (both written 2026-07-26) compute `week_of` from the runner's local clock while `BankService` computes the week via `_family_local_today`. On a UTC-6 machine any Sunday evening the row lands in last week's bucket and the money assertion fails. Fix: hoist `_current_week_monday` from `test_chore_paycheck.py` into `conftest.py`. The suite has no `freezegun`/`time-machine` dependency at all — adopting one retires this whole class.

**70 % global coverage gate hides critical modules at 0-40 %** — `pytest.ini:24`. Subsidized by well-tested CRUD: `dedup_service` 0 %, `schemas/validation.py` 0 %, `transfer_service` 16.7 %, `task_proof_validator` 29.4 % (the LLM gig-proof gate — only ever mocked), `family_export_service` 33.9 %, `bank_sync` 38.2 %, `budget/ai_settings.py` 39.6 % (zero test references), `receipt_draft_service` 43.7 %, subscriptions route 45.2 %. Fix: keep the global gate, add per-path floors for money/AI/admin code via a small script over `coverage.xml`.

**No dependency audit, secret scanning, or Dependabot** — `.github/` contains only `ci.yml`. Nothing will notice when a pin gains a CVE, and a committed secret (this repo handles PayPal, LiteLLM, SMTP, OAuth keys) would land unreviewed. Three files, <30 lines of YAML total.

### Production hardening

**Health gate is liveness-only** — `docker-compose.onprem.yml:97` points the backend healthcheck at `/health`, documented as "does NOT touch dependencies" (`main.py:428-431`). A readiness probe at `/ready` verifying DB + Redis and returning 503 already exists (`main.py:434-472`) and nothing consumes it. Since that healthcheck is the sole trigger for the deploy script's automatic rollback, a deploy that ships code unable to reach the DB reports every container healthy, skips rollback, and 500s on real traffic. Fix: point the healthcheck (or at least the deploy's post-up gate) at `/ready`.

**No resource limits, no `stop_grace_period`, no log rotation on a shared host** — `docker-compose.onprem.yml`. No service declares `mem_limit`/`cpus`; only redis is bounded. 10.1.0.91 also runs school-admin, medical, platform, and vault, so a leak here pressure-OOMs neighbors and the kernel picks the victim. Separately, the default 10 s SIGTERM→SIGKILL kills the backend mid-`scheduler.shutdown(wait=True)` while a money-moving sweep drains. Fix: `mem_limit` per service, `stop_grace_period: 30s` on backend, explicit logging driver options.

**Unauthenticated PayPal webhook amplifies each request into outbound PayPal calls** — `subscriptions_webhook.py:108`. Signature verification is delegated to PayPal's API, so every junk POST costs an OAuth token fetch + verify call (15 s timeouts each) and a default-executor slot; a flood can starve other `to_thread` users before any 401 returns. Fix: generous per-IP limit (~120/min) and short-circuit when the `paypal-transmission-*` headers are absent.

**`authlib==1.3.0` ships in the prod image, is imported nowhere, and carries CVE-2024-37568** — `requirements.txt:30`. Zero hits across app/tests/scripts. Auth is PyJWT + google-auth. Deleting the pin closes a scanner-bait CVE and shrinks the image for free. Best effort-to-value ratio in this report.

**Floating pins make prod builds non-reproducible** — `openai>=1.50.0`, `pymupdf>=1.24.0`, `google-cloud-storage>=2.18` (`requirements.txt:53,58,87`). `deploy-onprem.sh` builds fresh every deploy, so whatever PyPI serves that day lands in prod untested — an openai 2.x major or a pymupdf ABI change breaks receipt scanning *at deploy time*, not in CI. Exactly the failure this project already memorialized. Fix: pin to what prod currently runs.

**`mcp==1.12.4` is the keystone freezing the web stack** — `requirements.txt:96`. The file documents the chain: mcp pins sse-starlette which caps starlette <0.42 which caps fastapi at 0.115.6. mcp is 16 minors behind; fastapi, redis-py 5→8, alembic, sqlalchemy, asyncpg, uvicorn are all ~18 months stale. The new insight is the order: bump mcp first, and the ceiling dissolves. Do it before a CVE forces a big-bang upgrade.

**Env-template drift in both directions** — `.env.onprem.example:24` tells operators to generate `JWT_SECRET_KEY`, which nothing reads (JWTs are signed with `SECRET_KEY`) — an operator "rotating the JWT key" during an incident rotates nothing and leaves compromised tokens valid. `ANTHROPIC_API_KEY` is templated and defined in config but unread (all LLM traffic goes through LiteLLM). `.env.example:35-36` uses `SMTP_FROM_EMAIL/NAME`, which aren't settings fields. Missing from templates: `VAPID_*`, `LITELLM_*`.

**Ruff gate misses blocking-I/O-in-async** — `ruff.toml:10` runs only the default set plus DTZ ("widen gradually" — nothing has widened). `ruff check app --select ASYNC` today reports 12 real violations including 6 × ASYNC230 (sync `open()` of user-uploaded files inside async handlers: `task_assignments.py:225,234`, `receipt_scanner_service.py:1175,1181`, `email_service.py:1165`, `task_proof_validator.py:59`). Fix: add `ASYNC` to `extend-select`, fix the 12 with `asyncio.to_thread` (pattern already used in `push_service`). `B` is a follow-up and needs `ignore = B008`.

---

## P2 — dedup and maintainability

**20 copy-pasted API proxies, 1,635 LOC** (`frontend/src/pages/api/*/[...path].ts`) — all reimplementing cookie→Bearer injection, 401 refresh, and 502 fallback, in two generations (12 with manual redirect-follow, 8 without; 4 missing PATCH). Verifier downgraded **high → medium** and corrected the justification: the documented 307 `url.pathname` fix *did* propagate to all 20, every call site in the drifted domains is trailing-slash-exact, and the 4 proxies missing PATCH match the 4 backends with no PATCH routes — so nothing is broken today. It remains latent drift in token-handling code with a production-502 history. Fix: `createApiProxy(opts)` factory in `lib/server/proxy.ts`; each route collapses to ~5 lines, ~1,400 LOC saved, next proxy bugfix becomes a one-file change. Watch kiosk's `skipAuthPaths` (`/snapshot`) and the subscriptions webhook — the `const path` line is load-bearing in exactly those two.

**Client mutation handling fragmented across 4 conventions** — `lib/mutate.ts` and `lib/toast.ts` were built during the UX waves to end `fetch → alert → location.reload()`, but adoption stalled: 4 pages use `mutate()`, 12 use the shared `showToast`, while **45 `alert()` sites across 15 pages** and **77 `location.reload()` sites** remain (`budget/settings.astro` alone has 27, `budget/transactions.astro` 11), plus 6 pages define a private `showToast`. Worst daily-felt case: the parent routine builder reloads the whole page on every step add, step delete, routine toggle, and routine delete (`parent/routines.astro:290,305,317,330,352`) — building a 6-step morning routine costs 6+ full SSR reloads. Fix incrementally, worst pages first.

**LLM client scaffolding copy-pasted across 7 sites in 6 services** — identical `OpenAI(base_url=…LITELLM…, timeout=LLM_TIMEOUT)` construction plus the same "not configured" guard: `jarvis_service.py:413,615`, `calendar_scanner_service.py:98`, `recipe_importer.py:97`, `task_proof_validator.py:108`, `budget/category_ai_service.py:115`, `budget/receipt_scanner_service.py:273`. Worse than the LOC: four unrelated services import `LLM_TIMEOUT` **from the budget receipt scanner**, so the calendar scanner depends on a budget module for a core constant. Fix: `app/core/llm.py` owning the timeout, model aliases, and a `get_llm_client()` factory raising the domain exception.

**Modal shell duplicated ~10× plus 30 native `confirm()` dialogs** — the exact overlay string `hidden fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm px-4` is pasted across `bank.astro:299,325`, `gigs/index.astro:247`, `parent/settings/family-bank.astro:452,490`, `parent/tasks.astro:380` (35 `fixed inset-0` sites across 12 pages), alongside 8+ bespoke `*Modal.astro` components each re-implementing open/close/backdrop. Fix: one slotted `Modal.astro` with the z-index and safe-area rules baked in — which also structurally enforces the BottomNav z-index rule instead of relying on each author remembering it.

**Duplicated grade-credit math causes a 1-point dashboard/ledger mismatch** — `task_assignment_service.py:2040,1718` award points half-up (`(pts*pct+50)//100` → 25 pt @ 50 % = 13) while `bank_service.py:482` and the aggregate at `:566,875` use Python `round()` (banker's rounding → 12). Verifier confirmed the divergence numerically and downgraded **high → medium**: strictly display-only, since all money math consumes exact unrounded ×100 units and released weeks show actual ledger amounts. Worst case a parent sees one point fewer than the kid was awarded. Fix: one shared `grade_credit_points(points, pct)` helper across all four sites + a `.5` boundary test.

**Inline kid-role gates still repeated** (still open from 07-22) — `bank.py` defines `_require_kid` at line 67 but uses it at 2 of 9 sites; the other 7 plus `gigs.py:216` and `rewards.py:87,108` inline the check. No `require_kid_role` exists in `core/dependencies.py` although `require_parent_role` does. Note the variants intentionally differ (some return 400 with a pointer, some return None) — extract only the plain-403 sites.

**Amount-tolerance math still duplicated** (still open from 07-22) — `dedup_service.py:57,108` and `duplicate_guard_service.py:31,44`. 6 LOC; the point is a single tunable definition of "same amount".

**Family-scoped get-or-404 hand-rolled in 4 services** — `BaseFamilyService.get_by_id` already provides it and 18 services extend it, but `shopping_service`, `meal_service`, `calendar_service`, and `family_chat_service` re-implement the ~6-line lookup repeatedly. Each copy is tenant-isolation-critical code — the `family_id` filter *is* the boundary — so every hand-rolled instance is a place the filter can be forgotten.

**Secondary route-embedded logic** — `users.py:352-405` (`reject_pending_member` embeds the precondition, a bulk DELETE of the user's open assignments, and the audit policy), `months.py` and `month.py` build aggregates inline with mid-function imports. Smaller successors to the `register_family` extraction already shipped.

**PayPal checkout route** — `subscriptions.py:151-301` does inline billing-cycle validation, a `min()` multi-currency plan heuristic, and the staged-pending vs in-place-refresh branch with its own commit. Verifier downgraded **high → medium** and refuted the framing: the billing *state machine* already lives in `services/subscription_state.py` (idempotent, shared by route + webhook + sweep, unit-tested in `test_subscription_state.py`), so only the checkout orchestration is misplaced. Real sub-finding: the broad `except` at `:224-228` flattens typed PayPal exceptions into 500s whose detail can leak up to 300 chars of PayPal response body.

**`app/schemas/validation.py` is dead** — 0 % coverage, no importer. A "central validation limits" module nothing reads, silently drifting from the inline limits the schemas actually use. Same family as the dead Task exports the last audit caught. Delete it.

**Two phantom no-op migrations** — `fab16872eb7e_add_email_verification_tokens_table` and `8d23a3796561_add_password_reset_tokens_table` have `pass` for both `upgrade()` and `downgrade()`; the tables are actually created three months later inside `a6d655cbc18c`. Don't delete mid-chain files — add a one-line docstring pointing at the real revision.

**Allocation auto-fill N+1** — `budget/allocation_service.py:1034` and the `_average_n_months` sibling issue one SUM per category in a loop, plus a per-allocation existence check. `get_categories_available_amounts` (line 409) was already rewritten to kill exactly this pattern with four grouped queries — the batched shape exists, just unused here.

**CLAUDE.md count drift** — "107 revisions" (actual 114), "~1760 tests" (collects 1982), "17 budget tables" at line 253 vs "16 budget models" at line 158 (actual 16). Counts that rot every few weeks train readers to distrust the doc; soften the phrasing instead of re-fixing numbers.

---

## P3 — UX

**Shopping check-off is a full page reload per item, with swallowed errors** — verified: `shopping.astro` contains **zero** `fetch(` calls. Every action is a `<form method="POST">` handled in frontmatter, then `Astro.redirect` and a full SSR re-render (3 API round trips). Checking off 10 grocery items in the store = 10 full reloads, each losing scroll position on a long list — the single most-repeated in-store interaction in the app. And unlike the create branches at lines 18/30, the `toggle_item`/`delete_item`/`archive_list`/`delete_list` branches (44, 53, 61, 70) call `apiFetch` without destructuring `{ ok, error }`, so a failed write is indistinguishable from a successful one in the handler. Fix: `mutate()` with optimistic strike-through and revert-on-error (already live in `gigs/index.astro` and `bank.astro`), keeping the form POST as no-JS fallback.

**Kiosk bricks itself on any transient network failure** — `kiosk.astro:357` refreshes the always-on wall display with `location.reload()` every 60 s. A reload during a Wi-Fi blip, tunnel hiccup, or deploy lands the browser on its error page; the inline script holding the interval is gone, and the kiosk stays dead until a human walks over. Minimal fix: probe first and only reload on success. Better: fetch `/api/kiosk/snapshot` (already the frontmatter's data source) and patch the DOM, which also kills the visible white flash every minute.

**Page-level modals lack dialog semantics** — the design-system modals (`FABModal`, `TaskCreateModal`, `MoreSheet`, `DrawerMenu`, `AccountCreateModal`, `ui/BottomSheet`) all ship `role="dialog"`, `aria-modal`, Escape-to-close, and focus management (`MoreSheet.astro:209` has a real shift-Tab wrap). The hand-rolled page-level ones do none of it: `bank.astro:299,325`, `gigs/index.astro:247`, `parent/gigs.astro:411`, `parent/settings/family-bank.astro:452,490`, `parent/tasks.astro:380`, `parent/assignments.astro:506`. Folds into the shared `Modal.astro` extraction above.

**Three different treatments for the same interaction** — delete confirmation is a branded `#confirm-overlay` in `budget/settings.astro:559` but `window.confirm` in `budget/transactions.astro:1220`, `budget/reports.astro:703`, `chat.astro:416`, and ~25 more — which in the installed PWA renders browser chrome saying "family.agent-ia.mx says…". Same split for success/error feedback (toast vs `alert()`).

**Icon-only buttons built in JS lack accessible names** — `budget/transactions.astro:637,1255-1257`, `budget/reports.astro:154,699-701`, `components/BudgetNavNew.astro:190`. Screen readers announce "button". `GuideShell.astro:162-164` already does it right. One-line additive fixes.

**A2A settings form has no error catch and no double-submit guard** — `parent/settings/a2a.astro:62`. The only client submit handler in the app with neither. Dangerous here specifically because `rotate_secret: true` mints a new webhook secret, so a double-tap can rotate twice and display a stale one. Same script block as the token-embed fix.

---

## Suggested sequencing

1. **One PR, today**: delete the `authlib` pin, fix `month.py` income double-count (+ test), pin the three floating deps, add `@limiter.limit` to `oauth.py` + `meals.py` and wrap Google verification in `to_thread`, make `verify_public` assert. All small, all independent, four of them P0.
2. **Receipt storage PR**: local-volume backend + stop swallowing the failure. Data is being lost every scan until this lands.
3. **Token-embed PR**: strip `token` from the 6 surfaces and their `Bearer` headers.
4. **Test-gap PR**: `test_dedup_service.py`, `test_transfer_service.py`, `alembic check` in CI, dependabot + pip-audit + gitleaks.
5. Then the P1 correctness batch (suspension helper, `email_verified` guard, scheduler fail-open, import FK remap, `/ready` healthcheck), then the dedup work, which is the largest LOC win but the least urgent.

`raw-findings.json` holds all 59 findings with full evidence and per-finding verifier verdicts.
