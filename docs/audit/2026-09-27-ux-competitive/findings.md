# UX / GUI / Engagement Audit + Competitor Scan — 2026-09-27

Scope: daily usage, UX friction and visual quality — NOT feature gaps (the
2026-07-07 audit covered those and nearly all of it shipped). Evidence comes
from a read-only mobile walkthrough (390×844) of prod as the seeded demo family
(parent / teen `diego.demo` / child `sofia.demo`), a static scan of
`frontend/src`, and a 2026 web scan of competitors.

## What we already have (keep, lean on)

- Breadth nobody else bundles: chores + points, gig board cash, Family Bank
  (payday / jars / interest / match), native budget, Jarvis AI, meals,
  shopping, calendar, chat, kiosk, family cup + boss battle.
- Spanish-first, MXN-denominated. MX competitors (Nimbi, Raccoon Kids,
  SweetChild) are kid-only star charts with no money or budget layer.
- Fast: TTFB 74–256 ms, page transfer 40–175 KB, two web fonts.
- Distinctive brand (cream + ink-drop shadows, Plus Jakarta / Nunito), PWA
  manifest + service worker + install banner.
- Built but hidden: icon tap-through **routines** for pre-readers
  (`models/routine.py`, `/routines`, `/parent/routines`).

## Findings

### Broken or leaking in prod (fix first)

| # | Finding | Evidence |
|---|---------|----------|
| F1 | **Push works but looks dead and nobody has it.** (Corrected after host check.) Prod keys are set and the pair is valid, but Parent Settings shows "VAPID not configured" because `/api/push/health` assumes a PEM private key (`len >= 60`) and prod uses the 43-char raw form. One Apple endpoint (subscribed 2026-07-16) 403s on every send and is never pruned (only 404/410 prune). Only **3 push subscriptions exist in all of prod**. | `push.py:54`; prod logs 7d: 3× `403 Forbidden`, same endpoint; `push_subscriptions` = 2 Apple + 1 FCM |
| F2 | **Dark mode does nothing.** System-dark sets `data-theme="dark"`, but pages hard-code `bg-brand-cream`/`text-brand-ink`; 0 `dark:` variants and 1 use of `var(--bg)` across all pages/components. Screenshot with `prefers-color-scheme: dark` is fully light. | `styles/global.css` `[data-theme=dark]` only re-maps `--bg/--fg`, coral, mint |
| F3 | **Jarvis leaks internals** into chat bubbles: `[actions: budget_spending_report(ok)]`; money unformatted ("13849" not "$13,849"). | `jarvis_service.py:790`, `:1028` |
| F4 | **`/kiosk` without a device token renders raw text "Missing token" (HTTP 400).** | prod walkthrough |
| F5 | **Routines are orphaned.** No link from BottomNav, MoreSheet, kid dashboard or parent home. Only `/parent/routines → /routines` links exist. | grep of `frontend/src` |
| F6 | CSP blocks the Cloudflare Insights beacon → console error on every page. | console log, `script-src` lacks `static.cloudflareinsights.com` |

### Friction (daily-use UX)

| # | Finding | Evidence |
|---|---------|----------|
| F7 | **Notification spam.** Prod: 958 unread across 10 users (avg 87, max 214); 69% are `task_due` (454) + `task_assigned` (210) reminders that are stale the next day. No grouping, no supersede, each card carries two underlined links. The permanent badge on More trains users to ignore badges. | `/notifications`; `notification_service.py:68`; `task_assignment_service.send_morning_reminders`; prod aggregate query 2026-09-27 |
| F8 | **Parent home is a nav grid, not a "what needs me now" screen.** Ten tiles duplicate the More sheet; first load stacks welcome tour + AI-consent card + "Getting started" + "How points & cash work". Approvals / payday / per-kid progress are not the lead. | `/parent` full-page screenshot |
| F9 | **Kid home hides the chores.** Above the fold: points, cash, streak, goal, then a paragraph-long "How points & cash work" explainer. Today's chores start below the fold. Small type for a 6–10 y/o. | `/dashboard` as `sofia.demo` |
| F10 | **Teen mode is the kid UI tinted grey** — same layout, same baby-stage pet. Teens outgrowing kid-ish apps is Joon's documented churn cause. | `/dashboard`, `/pet` as `diego.demo`; `global.css` teen block only swaps colors |
| F11 | **~99 native `alert` / `confirm` / `prompt` calls** — unstyled, blocking, English OS buttons, jarring in the installed PWA. `lib/dialog.ts` exists but only handles hand-rolled modals. | grep: 43 `alert(`, 25 `confirm(`, 13 `prompt(`, + `window.*` |
| F12 | **Visual system drift.** Each page picks its own hero color (navy, orange, sky, purple, green, magenta, yellow); emoji used as icons next to line icons; the UI kit is barely used (`BottomSheet` 0 imports, `FormField` 0, `Card` 2, `EmptyState` 1); 107 `bg-white` + 173 `gray-*` bypass brand tokens; 144 raw hex values. | static scan |
| F13 | **Budget double navigation + mixed signals.** `/budget/transactions` shows its own header and the Month/Transactions/Reports tabs twice; month view shows "Ready to assign $29,500" next to "Available −$19,078". | screenshots |
| F14 | **Every navigation is a hard reload** (ClientRouter removed). Cross-document View Transitions (`@view-transition { navigation: auto }`) would give app-like transitions at near-zero cost. | `Layout.astro` |
| F15 | BottomNav makes 4 SSR API calls on every page (unread, 2× pending approvals, `/auth/me`). Fine today (fast TTFB) but it is the per-page tax to watch. | `BottomNav.astro:30-50` |

## Competitor scan — what changed since 2026-07-07

New or newly relevant: **PointUp** (RPG quests, 15 ranks, 90+ badges, weekly
challenges, team quests, parents earn XP too), **Flinkis** (free, Calm Mode,
one-task-at-a-time sequencer, PIN-locked parent mode, 80+ templates),
**Sense** (routines as first-class containers, kitchen-tablet hub),
**Nori** (create chores by voice / photo of a handwritten chart / forwarded
email), **Fami** (AI onboarding), **Skylight Sidekick** (text a flyer → events
and chores; picture-based chores for pre-readers), **Joon** 2026 updates
(trainer levels unlock new pets, subtasks, per-pet conversations).
Spanish/MX: **Nimbi** (stars, 10 levels, badges, weekly challenges),
**Raccoon Kids** (mascot + coins), **SweetChild**.

Patterns that matter for us:

1. **Routine containers beat flat lists** for long-term use — "Bedtime 2/5"
   cards; parents say "mornings" and "bedtime" before "the chore list". We
   built routines and hid them (F5).
2. **Layered progression** (daily streak → weekly challenge → rank/level →
   badges) is what outlasts pet/points novelty, which fades in 4–8 weeks.
3. **Low-friction kid UI**: big tap targets, one task at a time, calm mode,
   pictures for non-readers, celebration on completion, mystery-reward reveal.
4. **AI removes typing**: photo/voice/email → chores & events; AI-guided
   setup. We have the vision + Jarvis pieces; the entry points are buried.
5. **Always-visible surface**: kitchen tablet (we have kiosk) and, for a PWA,
   push + **App Badging API** (iOS 16.4+ for installed web apps, outside EU).
6. **Reliability of notifications** remains the category's #1 complaint —
   F1 + F7 are exactly this.

## Decomposition — sub-projects (each gets its own spec → plan → SDD)

| ID | Sub-project | Covers | Size |
|----|-------------|--------|------|
| A | **Prod hygiene pack** | F1 (VAPID + push health check), F3, F4, F5 (link routines), F6, F7 (digest + auto-read + badge sanity) | S–M |
| B | **Design-system consolidation** | F2 (dark mode for real, or drop the toggle), F11 (styled confirm/prompt sheet), F12 (semantic tokens, one accent system, icon set), F13, F14 | L |
| C | **"Today" home screens** | F8 parent action hub, F9 kid today (routines first, big cards, one-at-a-time, celebration), F10 teen register | M–L |
| D | **Progression & engagement loop** | levels/ranks, badges, weekly challenge, mystery-reward reveal, app-icon badge, smart pushes | L |
| E | **AI-assisted creation** | snap a chore chart / voice → chores, Jarvis-guided family setup | M |

Suggested order: **A → C (with the slice of B it needs) → B → D → E**.

## Sources

- https://kidkarma.app/compare/best-chore-apps/
- https://getsense.ai/blog/posts/best-family-chore-apps-2026
- https://point-up.co.uk/compare/best-kids-chore-apps
- https://halallens.no/en/blog/best-chore-app-for-kids-free-habits-tracker-2026
- https://getsense.ai/blog/posts/best-ai-family-organizer-apps-2026
- https://heynori.com/blog/best-family-chore-app
- https://www.gethoneydew.app/blog/skylight-calendar-2-review-2026-whats-new-and-is-it-worth-it
- https://www.choosingtherapy.com/joon-app-review/
- https://apps.apple.com/mx/app/nimbi-tareas-y-recompensas/id6747768677
- https://raccoon.kids/es
- https://webkit.org/blog/14112/badging-for-home-screen-web-apps/
- https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide
- Prior feature-level intel: `docs/audit/2026-07-07/02-competitor-intel.md`
