# Track A — Security Criticals: execution progress

Branch: `rename/frankie-to-jarvis` (also carries jarvis rename + Track A; split at commit time).
Tests run inside `family_app_backend` container (image rebuilt from current tree;
jarvis-consistent). Test DB = test_db:5432. RED watched for each before fixing (TDD).

## A1 — /register cross-tenant escalation — DONE ✓ (GREEN)
- Fix: `backend/app/api/routes/auth.py` register route now requires
  `Depends(require_parent_role)` and forces `user_data.family_id = current_user.family_id`
  (body family_id ignored). Public self-signup unaffected (uses /register-family).
- Tests: `tests/test_security_criticals.py::TestRegisterAccessControl` (4) +
  updated `tests/test_auth.py::TestUserRegistration` (3, rewritten to authed contract). All pass.

## A2 — public /uploads StaticFiles mount — DONE ✓ (GREEN)
- Fix: removed `app.mount("/uploads", StaticFiles...)` in `main.py`; added authed,
  family-scoped route `backend/app/api/routes/uploads.py`
  (`GET /uploads/gig-proofs/{filename}` → checks GigClaim + TaskAssignment proof_image_url
  for caller's family; 404 on miss; path-traversal guard). Frontend proxy
  `frontend/src/pages/uploads/gig-proofs/[file].ts` now forwards `Authorization: Bearer`.
- Tests: `TestUploadsAuth` (4: require-auth, serve-own, block-other-family, traversal). Pass.

## A3 — sync LLM/vision call blocks event loop, no timeout — DONE ✓ (GREEN)
- Fix (receipt_scanner_service.py): `OpenAI(..., timeout=60s)` + `.create()` wrapped in
  `await run_in_threadpool(...)` so it never blocks the loop. jarvis_service.py: added
  `timeout=60.0` to both OpenAI constructors (caps 600s→60s; full threadpool offload there
  is a follow-up given the tool-loop/SSE complexity).
- Test: `TestReceiptScannerResilience::test_scan_receipt_sets_finite_timeout`. Pass.

## Regression check
`pytest test_receipt_scanner test_receipt_scanner_v2 test_auth test_gig_approval` →
42 passed, 1 failed. The 1 failure (`test_pipeline_returns_dup_warning_without_committing`)
is a PRE-EXISTING env issue: `google.auth.DefaultCredentialsError` in gcs_receipt_service
(no GCS creds locally) — unrelated to these changes.

## A4 — budget month dashboard N+1 — DONE ✓ (GREEN)
- Fix: added `AllocationService.get_categories_available_amounts(db, family_id, month, categories)`
  → exactly 4 grouped aggregate queries (budgeted@month, activity@month [date in
  month..end_of_month, deleted null], prior_budgeted [month<month], prior_activity
  [date<month, deleted null]); read-only (no allocation auto-create on a GET);
  int()-cast sums (Decimal→int per CLAUDE.md mobile note). Refactored
  `routes/budget/month.py get_month_budget` to collect all categories and call it ONCE
  instead of `get_category_available_amount` per category.
- Tests: `tests/test_budget_month_n1.py` — (1) batched==per-category field-for-field
  equivalence, (2) query count ≤5 for 4 categories (constant, N+1 gone), (3) GET
  /api/budget/month/2026/2 returns correct numbers. All pass.
- Regression: test_budget_allocation + test_allocation_advanced → 21 passed.

---

## TRACK A SUMMARY — ALL DONE ✓
A1 (register escalation), A2 (public uploads), A3 (LLM timeout), A4 (month N+1).
New/changed: auth.py, uploads.py(new), main.py, receipt_scanner_service.py, jarvis_service.py,
allocation_service.py, routes/budget/month.py, frontend uploads proxy. New tests:
test_security_criticals.py (9), test_budget_month_n1.py (3); updated test_auth.py (3).
All green in container. No regressions in targeted suites.

## REMAINING BEFORE MERGE/DEPLOY
- Run FULL suite in CI (targeted suites clean; known pre-existing failures: GCS-cred
  env tests like test_pipeline_returns_dup_warning_without_committing, + the ~51 stubs).
- Split commits: (a) jarvis rename, (b) Track A security fixes — currently same branch.
- Prod .env: FRANKIE_ → JARVIS_ before deploy (see RENAME doc).
- A3 follow-up (optional): full threadpool offload for jarvis (only timeout applied there).

## NOT committed / NOT deployed yet.
Deploy note (still pending): prod .env FRANKIE_ → JARVIS_ (see RENAME doc).
