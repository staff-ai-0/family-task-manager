# Test Verification — live run, 2026-07-22

Run against the local podman stack (family_app_backend/frontend/db/test_db/redis, all healthy at run start), main branch, clean working tree.

| Suite | Result |
|---|---|
| `ruff check app` | **PASS** — 0 violations (`All checks passed!`) |
| Backend pytest (`tests/`) | **PASS** — 1894 passed, 0 failed, 3 skipped, 10 xfailed, **79.10% coverage** (gate ≥70%) |
| `alembic heads` / `upgrade head` | **PASS** — single head `cash_tx_week_of`; upgrade succeeded as a no-op (DB already at head) |
| `astro check` | **PASS** — 0 errors, 0 warnings, 90 hints (222 files) |
| `astro build` | **PASS** — exit code 0, `[build] Complete!` |
| Playwright e2e | see below |

No pytest failures to report. Migration chain confirmed single-head (matches CLAUDE.md's claim, though file count is 106 vs. documented 102 — doc drift, not a functional issue, folded into `02-docs-cleanup.md`).

## Playwright e2e

Full run, sequential (workers:1), retries:2, wall time 13.8m (~16m incl. install/browser warm-up).

**135 tests → 114 passed, 14 failed, 7 skipped.** Every failure below failed identically on all 3 attempts (deterministic, not flaky).

None of the 14 look like today's checkout being broken — backend gates (ruff/pytest/alembic) and astro check/build are all clean. They read as E2E test debt against evolved UI, not app regressions. No fixes attempted (per instructions) — flagged for triage.

### Failures

1. **auth.spec.js:144** — "Logout Flow › should logout and clear access token". `locator.click` timeout 30s on `a[href="/profile"]`. Root cause: that link lives inside the "More" bottom-sheet (closed/off-canvas by default) — element matches in DOM but never scrolls into view because the sheet isn't opened first. Test doesn't open the More sheet before clicking.
2. **dm.spec.js:29** — "thread list link reachable from BottomNav chat is /chat". `nav a[href="/chat"]` not found. Chat is no longer a direct `<nav>` child — moved inside the "More" sheet (confirmed by passing dashboard.spec.js:38). Stale test assumption vs. current BottomNav layout.
3-5. **jarvis-schedules.spec.js:17,25,34** — all 3 specs in the file: click timeout 30s waiting for `getByText(/Nueva programación|New schedule/i)`. Page loads fine (h1 assertion passes), but the "New schedule" button never resolves clickable. One root cause hit 3x, not 3 independent bugs — unconfirmed whether it's the same off-canvas pattern as #1 or a selector/markup mismatch.
6. **kid-onboarding.spec.js:72** — "eligible kid sees the points converter". Expected `/Convert Points to Money/i` in body text, not found — kid dashboard renders normally (points, cash, tasks) but no converter text anywhere. Either copy changed or seeded kid no longer meets the eligibility condition the test expects.
7. **members.spec.js:64** — "should display invitation section for new members". No button matches `Invite`/`Add member`/`New member` text patterns — copy/UI likely changed.
8. **middleware-security.spec.js:31** — "anonymous /dashboard redirects to /login with security headers". Expected redirect `Location: /login`, got `/login?next=%2Fdashboard`. Looks like an intentional behavior improvement (return-to-destination post-login) the test wasn't updated for. Security-header assertion itself never reached.
9. **pricing.spec.js:17** — "page renders + shows tier cards". Expected h1 `/Planes|Plans/i`, got "Suscripción" — copy changed since test was written.
10. **pricing.spec.js:25** — "manage link routes to subscription settings". `a[href="/parent/settings/subscription"]` not found — likely downstream of #9's page-structure change.
11. **rewards.spec.js:255** — "child can redeem reward". Post-redemption confirmation text (`redeemed|deducted|canjeado|descontados`) not found — either wording changed or redemption feedback didn't render as expected.
12. **scanner-v2.spec.js:5** — "one-tap snap → confirm card". Text "Snap receipt" not found on `/budget/scan-receipt`. Possibly renamed, or `receipt_scan` (metered AI feature per CLAUDE.md) isn't entitled for the test's parent account, showing an upsell state instead.
13. **ux-polish.spec.js:12** — "reports has no dead 'vs Budget' sub-tab". Expected 3 `.report-tab` elements, got 5 (consistent all 3 attempts) — `/budget/reports` now has more report tabs than when the test was written; the actual "dead tab" assertion was never reached. Likely stale test, not an app bug.
14. **ux-polish.spec.js:49** — "archiving a gig removes its card in place". Expected 1 `[data-gig-card]` matching "E2E Gig B", got 11→12→13 across retries. Count climbing on retry indicates test-data accumulation — leftover "E2E Gig B" cards from prior local E2E runs against the same unreseeded stack. Environment/fixture-hygiene issue, not app logic.

### Skipped (7, all intentional/guarded)

- `gigs.spec.js:21,65` — `test.skip` gated on demo-seed preconditions not met.
- `jarvis.spec.js:33` — `test.skip(!process.env.E2E_FULL, ...)`, requires `LITELLM_API_KEY`, not set this run.
- `scanner-v2.spec.js:18-21` (4 tests) — explicitly skipped with in-code notes: covered by specific backend unit tests instead.

### Triage grouping

- **Test debt vs. evolved BottomNav/More-sheet**: #1, #2 (and likely #3-5).
- **UI copy/route drift, tests not updated**: #6, #7, #9, #10, #11, #12.
- **Likely intentional behavior change, test needs updating**: #8 (`?next=` redirect param).
- **Fixture/environment hygiene (not app logic)**: #14 (stale gig cards from repeated unreseeded local runs).

Full logs/artifacts: `e2e-tests/test-results/` (screenshots + videos + error-context.md per failed test).
