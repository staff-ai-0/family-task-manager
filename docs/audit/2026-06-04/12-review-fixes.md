# Review fixes — adversarial self-review of the 5-PR stack

Ran an independent review workflow (reviewer + verifier per PR) over #31–#35, then
verified findings by hand. Applied fixes on each finding's SOURCE branch and rebased
the stack (network-FS git needed `core.checkStat=minimal`). All re-verified in-container:
**60 affected tests pass; only pre-existing failure is the GCS-credentials env test.**

## Fixed

### PR #35 (UX) — missing gig API proxy [FUNCTIONAL, was pre-existing]
`/api/gigs/*` browser calls had NO frontend proxy route to translate the httpOnly
cookie → Bearer (every other resource has one). So gig claim/complete/offering-CRUD/
approve all 404'd (dev) / 401'd (prod) — and the new unified `/parent/approvals` gig
approve inherited it. Added `frontend/src/pages/api/gigs/[...path].ts` (mirrors budget).
→ commit 677e49f.

### PR #33 (ops) — 3 HIGH (verifier-confirmed)
- `RATE_LIMIT_STORAGE_URI` was read via getattr but had no Settings field
  (`extra='ignore'` dropped the env var) → added the field to config.py.
- Scheduler lock renew/release acted on the key blind → could refresh/delete another
  worker's lock after TTL takeover. Now stores a per-worker token; renew/release use
  compare-and-expire / compare-and-delete Lua. New test asserts a wrong-token release
  can't delete the lock. Verified live: leader acquires + stores token `host:pid`.
- New SECRET_KEY validator + local compose `DEBUG: ${DEBUG:-false}` crashed a fresh
  `compose up` (no .env) → local compose now defaults `DEBUG=true` (prod gcp stays false).
- `AI_LIMIT`/`EMAIL_LIMIT` were dead constants → applied AI_LIMIT (30/hr) to the receipt
  scan endpoint, EMAIL_LIMIT (5/min) to verify-email / resend-verification.
→ commit 2dd449c.

### PR #32 (security) — A2 email regression [MEDIUM]
notify_parents_gig_pending embedded `<img src={base_url}/uploads/...>`; A2 made that URL
auth-required so email clients render a broken image. Replaced the embed with a "photo
attached — open the app" note; the existing "Review & approve" button already deep-links
to the authed page. → commit 93c76f2.

## Accepted / deferred (with rationale)
- A3 Jarvis: timeout-only (no threadpool) — caps blocking 600s→60s; full offload noted.
- B6 webhook 503-retries permanently-unprocessable events for PayPal's ~3-day window —
  judged safer than the original silent-drop (transient failures must retry).
- Scheduler: non-leader workers don't re-poll; a dead leader pauses jobs until restart
  (acceptable for daily/5-min sweeps; documented in scheduler_lock.py).
- Uploads scoped to family (any member incl CHILD can fetch a family proof) — low.
- Nits left: orphaned `fab_photo` key, `gig_mode` sent for plain chores (backend ignores),
  lost gig-card timestamp (not in the claim response schema anyway).

## Stack after fixes (force-pushed)
#31 (unchanged) · #32 +93c76f2 · #33 +2dd449c (rebased) · #34 (rebased) · #35 +677e49f (rebased)
