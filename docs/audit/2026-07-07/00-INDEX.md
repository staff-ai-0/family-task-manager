# Launch-Readiness Audit + Competitive Intel — 2026-07-07

Master log. Read this first to resume (survives context reset / new session).

Rendered report (artifact): https://claude.ai/code/artifact/ecaa3294-eaf0-4b89-a0c1-430da6cfc05c

## Method
Workflow `wf_25d21dfa-c92` — 44 agents, 2.02M tokens. 11 repo audit dimensions
(every critical/high adversarially re-verified against code + live prod host 10.1.0.91;
none refuted, several re-scoped with corrections kept inline) + 7 web-research lanes
covering 28 competitor products (sources as of 2026-07-07).

## Files
- `01-launch-gaps.md` — 71 verified findings by dimension, with file:line evidence,
  fix recommendation, effort (S/M/L), and verify verdicts.
- `02-competitor-intel.md` — 28 competitors: positioning, pricing, complaints,
  112 features rated for adoptability, per-lane INSIGHTS blocks.
- `report.html` — synthesized report (same content as the artifact).

Severity totals: 7 critical · 18 high · 27 medium · 19 low.
Prior audit baseline: `docs/audit/2026-06-04/` (Tracks A–D shipped; delta re-checked here).

## Headline verdict
Engineering healthy. Launch blocked by: (1) legal at zero for a kids app,
(2) billing dunning broken end-to-end, (3) no ops safety net.
Market: nobody serves Spanish/LATAM; nobody bundles chores+money+budget+AI.
Highest-ROI build = "Family Bank" (payday + jars + parent interest/match) on existing ledgers.

## Roadmap / status — update as work lands

### P0 — Don't launch without (~2–3 wk)
- [ ] Legal: /privacidad + /terminos pages (ES/EN), consent checkbox at register, link from footer; register URL with Google OAuth + PayPal
- [ ] Legal: child-signup consent flow (birthdate, parent-initiated/approved child accounts, optional child email, consent record)
- [ ] Legal: family delete endpoint (wire FamilyService.delete_family + cascade + confirm/re-auth) + whole-family data export
- [ ] Legal: AI disclosure + parental opt-in for AI on kid content (proof photos → Gemini, chat → Jarvis MCP)
- [ ] Billing: honor grace period (payment_failed entitled N days), handle PAYMENT.SALE.COMPLETED → reactivate, dunning email
- [ ] Billing: /checkout guard (don't mutate active sub pre-payment; cancel old PayPal sub on upgrade activate)
- [ ] Billing: daily PayPal reconciliation in sweep; handle SUSPENDED/EXPIRED/refund events
- [ ] Billing: require_feature('family_member') on join-code register branch (auth.py:105-155)
- [ ] Data: offsite backup push (rclone) + tar uploads volume + fix restore-db.sh onprem defaults + run ONE restore drill
- [ ] Ops: SENTRY_DSN in prod .env (code already wired); external uptime check on /ready; catch-all exception handler
- [ ] CI: GitHub Actions — backend pytest (pg+redis services) + astro build + astro check; tagged images + rollback in deploy-onprem.sh
- [ ] Perf: run_in_threadpool + timeout on 5 sync LLM sites (jarvis_service.py:304,481; calendar_scanner_service.py:102; recipe_importer.py:99; task_proof_validator.py:114; category_ai_service.py:115) — copy receipt_scanner pattern
- [ ] Sec: rate-limit key on CF-Connecting-IP (drop --forwarded-allow-ips="*" trust), Redis RATE_LIMIT_STORAGE_URI; rate-limit + meter Jarvis chat/stream + calendar scan-document; security headers (HSTS/CSP/XFO/nosniff)
- [ ] Product: support email (soporte@) in footer/help/billing; fix login demo creds (parent@demo.com doesn't exist); landing CTAs → /register; 404/500 pages; enforce email verification (min: gate email-triggering actions)
- [ ] Push: TASK_ASSIGNED notification type + morning "chores due today" job
- [ ] i18n: locale middleware (cookie → Accept-Language → es); NotificationService keyed translations (port email _t pattern, ~30 call sites)

### P1 — Launch differentiators (~3–4 wk)
- [ ] Family Bank: weekly payday job; Save/Share/Spend jars w/ % auto-split; parent-paid interest; parent match
- [ ] Onboarding: age-preset ES/MX chore+gig+reward template packs (Jarvis-generated); budget first-account empty state + FAB "+ New account"
- [ ] Tasks: sibling rotation strategy; interval-since-completion recurrence; photo proof + approval on task templates (reuse gig infra); kid-proposed gigs; 1-tap award/deduct points
- [ ] Kid money: goal jar (earmark points toward reward, progress visual); kid envelopes in budget; star mode for ages 3-7
- [ ] Kiosk: per-kid PIN switch; per-member colors app-wide; leaderboard panel; "convierte tu tablet en un Skylight" marketing
- [ ] Pricing: MXN PayPal plans (Plus ~MX$79-99, Pro ~MX$149-199, per-family); pricing page copy
- [ ] Packaging: scan-a-flyer button on kiosk+onboarding; Jarvis weekly meal-plan scheduled prompt; Jarvis surfaced in budget pages (suggested ES money questions)

### P2 — Post-launch growth
- [ ] Quest-mode kid UI + pet evolution stages — BLOCKED on pet go/no-go decision (memory: feedback_virtual_pet_uncertain; research strongly supports — Joon evidence in 02, decays wk 4-8 without progression ladder)
- [ ] Family Cup weekly leaderboard season; cooperative family boss battle; completions auto-post to chat
- [ ] Budget: month rollover + cover-overspend flow; bill calendar + 30/60d forecast; learning categorization (corrections as few-shot); recurring-charge detection
- [ ] Capacitor wrap (remote-URL shell + FCM/APNs) for app stores; referral program; Spanish SEO content ("cuánto domingo dar por edad"); routines library (icon tap-through); TDAH content angle
- [ ] Ops maturity: staging env; request-ID middleware; metrics; image thumbnails; composite (family_id, date) indexes; Redis pub/sub for chat SSE; soft-delete for Family/User; 6h backup cadence

### Explicit don't-build (research-backed)
Card issuance / bank aggregation at launch (MX coverage poor, category's #1 complaint source);
investment sync; local-first; Stripe (memory: PayPal only).
