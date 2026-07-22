# UX Audit — 2026-07-02

> **ARCHIVED 2026-07-22** — all 10 waves (PRs #80-89) shipped and deployed; see
> `docs/audit/2026-07-22-forensic/` for the current audit. Kept for history.

Multi-agent audit (10 dimensions + completeness critic) of frontend UX. 77 findings, grounded in code with file paths. Impact: high/medium/low. Effort: S <1d, M 1-3d, L >3d.

## Navigation & Information Architecture

### [high/M] Meals, Shopping, Calendar and DM are orphan pages with zero navigation entry points

**Problem.** pages/meals.astro (300 lines), pages/shopping.astro (294), pages/calendar.astro (317) and pages/dm.astro (132) are fully functional domains, but a repo-wide grep finds no href to /meals, /shopping, /calendar or /dm anywhere — not in BottomNav, DrawerMenu, /parent cards, /profile, the welcome tour, or the help guides. The only entries are typed URLs or notification deep links (pages/notifications.astro n.link), so the family will never discover these features; calendar/scan and dm/[id] only link back to their own orphaned parents.

**Fix.** Add a role-aware app-wide drawer (generalize the existing DrawerMenu pattern beyond /budget, opened from a hamburger in PageHeader) or a 'More' grid section on /dashboard and /parent listing Meals, Shopping, Calendar and Direct Messages; also add a DM entry point from /chat since they share the messaging mental model.

Files: `frontend/src/pages/meals.astro`, `frontend/src/pages/shopping.astro`, `frontend/src/pages/calendar.astro`, `frontend/src/pages/dm.astro`, `frontend/src/components/DrawerMenu.astro`, `frontend/src/components/BottomNav.astro`

### [high/M] Parent bottom nav has 10 icon-only items that silently overflow off-screen on phones

**Problem.** Parents get 10 bottom-nav items (tasks, rewards, inbox, chat, profile, gigs, budget, manage, lang, logout); kids get 9. At ≤430px the labels go sr-only and .nav-row becomes overflow-x:auto with scrollbar-width:none (BottomNav.astro lines 203-225), so on a 360-390px phone the last items — Manage and Logout for parents — can sit off-screen with no visual affordance that the bar scrolls. Ten unlabeled icons is also heavy recognition load for a child on a shared tablet.

**Fix.** Cap the bar at 5 role-relevant destinations (kid: Tasks, Gigs, Rewards, Pet, Chat; parent: Tasks, Approvals/Manage, Budget, Gigs, Inbox) and move the rest (profile, lang, logout, chat-for-parent) into a 'More' item or the profile page; keep labels visible at all widths once item count is 5.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/components/ui/PageLayout.astro`

### [high/S] Approvals — the top parent action — is 3 taps deep with no badge in the global nav

**Problem.** A parent approving a kid's work must tap Manage in BottomNav (1), find the Approvals card on /parent (2), then approve (3). The pending count (task + gig approvals) is computed only inside pages/parent/index.astro, so BottomNav's Manage icon shows nothing — a parent opening the app on /dashboard or /budget gets zero signal that kids are waiting, while the notifications bell does get an SSR badge (BottomNav.astro lines 14-25).

**Fix.** In BottomNav.astro, when role === 'parent', fetch the two pending-approvals endpoints alongside unread-count (or add a combined /api/oversight/badge endpoint) and render the red count badge on the Manage icon; optionally link the badge directly to /parent/approvals to make it 2 taps.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/pages/parent/index.astro`, `frontend/src/pages/parent/approvals.astro`

### [medium/S] One-tap logout (no confirmation) and language toggle occupy permanent bottom-nav slots

**Problem.** BottomNav.astro lines 141-162 render the lang toggle and a logout POST form as first-class nav items on every page. Logout fires immediately on a single tap at the screen edge where kids swipe — on the family's shared tablet an accidental tap logs the child out and forces a full email+password re-login. These two low-frequency actions also consume 2 of the ~10 slots causing the overflow problem.

**Fix.** Move logout and language toggle to /profile (pages/profile.astro currently has almost no links — only Help), and add a confirm step to logout. This frees two nav slots and eliminates accidental logouts on shared devices.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/pages/profile.astro`

### [medium/S] Orphaned duplicate finance hub at /parent/finances competes with /budget

**Problem.** pages/parent/finances/index.astro is a live 247-line hub (quick stats + 6 nav cards) with zero inbound links — the /parent 'Finances' card goes straight to /budget, and BottomNav goes to /budget/month. Its sibling import.astro is already a legacy redirect, and budget/accounts + budget/categories were correctly converted to 301 redirects, but this page was missed. It duplicates BudgetNavNew/DrawerMenu destinations and issues an extra month-budget API call whenever someone lands on it from an old bookmark.

**Fix.** Convert pages/parent/finances/index.astro to `return Astro.redirect("/budget/", 301)` exactly like pages/budget/accounts/index.astro does, and delete its unused card markup; keep import.astro's existing redirect.

Files: `frontend/src/pages/parent/finances/index.astro`, `frontend/src/pages/parent/finances/import.astro`, `frontend/src/pages/budget/accounts/index.astro`

### [medium/S] Inconsistent back behavior: parent sub-pages missing back links; budget drawer has no exit to the app

**Problem.** 17 pages set backHref (approvals, tasks, members, settings, etc. → /parent) but parent/gigs, parent/payouts, parent/analytics and parent/jarvis have none — e.g. /parent/payouts is reached from /parent/gigs yet offers no way back except the browser chrome. On /budget/* the hamburger DrawerMenu is titled 'Menu' but contains only budget links (Management/Tools/System sections), with no 'Home' or 'Back to family' entry, so the budget area reads as a separate app whose only exit is decoding the icon-only BottomNav.

**Fix.** Add backHref='/parent' to parent/gigs, payouts, analytics and jarvis (payouts should go back to /parent/gigs), and add a top 'Home' section to DrawerMenu with links to /parent and /dashboard so budget pages have an explicit exit.

Files: `frontend/src/pages/parent/payouts.astro`, `frontend/src/pages/parent/gigs.astro`, `frontend/src/pages/parent/jarvis.astro`, `frontend/src/pages/parent/analytics.astro`, `frontend/src/components/DrawerMenu.astro`

### [low/S] Help pages' back link dumps parents onto the kid dashboard instead of where they came from

**Problem.** pages/help.astro and pages/ayuda.astro set backHref='/' — the marketing landing — which for a logged-in user 302s to /dashboard (pages/index.astro lines 11-13). A parent who opened Help from the /parent onboarding widget taps back and lands on the task dashboard, not the parent dashboard they left, adding a confusing extra hop mid-onboarding.

**Fix.** Point the help pages' backHref at the role home (read the ui_role cookie already used by Layout.astro: parent → /parent, else /dashboard), or accept a ?from= query param set by the onboarding widget link in parent/index.astro.

Files: `frontend/src/pages/help.astro`, `frontend/src/pages/ayuda.astro`, `frontend/src/pages/index.astro`

## ONBOARDING & FIRST-RUN

### [high/M] The advertised way to add a kid is a dead end — and the working fallback silently makes kids PARENTs

**Problem.** InvitationModal tells parents 'Email invitations are for adults (18+) only. To add children or teens, share the family code instead', and members.astro says the code lets members 'join using Google Sign-In'. But login.astro hardcodes join_code: null in the Google callback — there is no UI anywhere for a kid to enter a family code with Google. The only place a code can be typed is /register, where backend register_family unconditionally creates role=UR.PARENT (auth.py 'Create PARENT user'), and google_oauth_service.py:185 also hardcodes UserRole.PARENT. A kid following the family-code instructions either dead-ends or gets full parent access (approvals, budget, member deletion) in the family.

**Fix.** Add a role choice to the join-by-code path: /register with a family_code should ask 'Who is joining?' (child/teen/parent) and pass it to register_family — defaulting to CHILD, with parent promotion from /parent/members. Add a 'Have a family code?' field to the login page Google flow so the documented Google+code path actually exists.

Files: `frontend/src/components/InvitationModal.astro`, `frontend/src/pages/login.astro`, `frontend/src/pages/register.astro`, `backend/app/api/routes/auth.py`, `backend/app/services/google_oauth_service.py`

### [high/S] Getting-started checklist step 'Invite a child' links to a page that does not exist (404)

**Problem.** parent/index.astro:135 renders the checklist arrow for the child_invited step as <a href="/parent/invite">, but there is no invite page anywhere under frontend/src/pages (no invite.astro, no middleware rewrite) and no custom 404.astro — the brand-new parent who taps the third onboarding step lands on Astro's bare 404 screen at the most fragile moment of first-run.

**Fix.** Point the link at /parent/members (where the join code, invitation modal, and add-member form actually live), ideally with a #invite anchor that scrolls to/opens the invitation section. One-line fix plus an anchor id.

Files: `frontend/src/pages/parent/index.astro`, `frontend/src/pages/parent/members.astro`

### [high/S] New parent registers and lands on the KID dashboard, greeted with 'Ask a parent to shuffle!'

**Problem.** api/auth/register.ts:60 redirects every new registration to /dashboard, but register-family always creates a PARENT. dashboard.astro is the kid task view; with an empty family it shows the empty state dashboard_no_assignments = 'No tasks assigned for today. Ask a parent to shuffle!' (i18n.ts:46) — addressed to the person who IS the parent. The getting-started checklist lives on /parent, and PageLayout deliberately drops the checklist tour step on /dashboard (element absent), so the one step that teaches setup is skipped on the exact page new parents land on.

**Fix.** In register.ts, redirect founding parents to /parent instead of /dashboard (role is always PARENT on this path; keep /dashboard for join-code kids once finding 1 lands). Optionally add a parent-only variant of the dashboard empty state: 'No tasks yet — create your first chore →' linking to /parent/tasks.

Files: `frontend/src/pages/api/auth/register.ts`, `frontend/src/pages/dashboard.astro`, `frontend/src/lib/i18n.ts`

### [medium/M] Kid accounts require a real email + password; the add-member form is buried at the bottom of the members page

**Problem.** The only way to create a CHILD account is the register form at the very bottom of /parent/members — below the join-code card, invite card, pending invitations, and every member card — and it requires an email (type=email, required) plus an 8-char password even for a 6-year-old. Parents must fabricate an address, and backend register then fires a verification email at it (auth.py: 'Send verification email' right after register_user). A kid on the shared tablet must then type a fake email + adult-length password to log in.

**Fix.** Short term: move/anchor the 'Add family member' form to the top of members.astro and auto-suggest a generated address (e.g. name+family-slug@kids.internal) that skips the verification email for child/teen roles. Medium term: username- or PIN-based kid login for shared devices (kiosk mode exists but is a wall display, not a login path).

Files: `frontend/src/pages/parent/members.astro`, `backend/app/api/routes/auth.py`

### [medium/S] Checklist 'Invite a child' never completes via the primary add-child path, and the widget can't be dismissed until everything is done

**Problem.** OnboardingService.advance('child_invited', ...) is called only from register_family when someone self-joins with a family code (auth.py:160). The main path a parent actually uses — the add-member form on /parent/members which hits the parent-scoped POST /api/auth/register — never advances the step, and neither does sending an email invitation. Meanwhile the dismiss button on the widget only renders when all_done (parent/index.astro:96-102), so a family that added kids 'the wrong way' stares at a permanently incomplete, permanently undismissable checklist at the top of the parent dashboard.

**Fix.** Advance child_invited inside the parent-scoped register route when the created role is child/teen (one line next to the existing verification-email call) and when an invitation is sent. Also render the dismiss × unconditionally — a checklist users can't get rid of trains them to ignore the whole widget.

Files: `backend/app/api/routes/auth.py`, `frontend/src/pages/parent/index.astro`

### [medium/S] Checklist step 'Create a reward' sends the parent to a page that tells them to 'Ask a parent'

**Problem.** The reward_created checklist arrow links to /rewards (parent/index.astro:128), the shared redemption page. For a new family that page renders the empty state 'No rewards yet / Ask a parent to add some rewards!' (i18n.ts rewards_empty_title/subtitle) with no create control — rewards.astro has zero parent affordances (isKid only gates goal buttons). Reward creation actually lives at /parent/rewards, so the parent following the checklist hits a kid-voiced dead end and has to guess the real location.

**Fix.** Change the checklist link to /parent/rewards, and in rewards.astro render a parent-only empty-state CTA ('+ Create your family's first rewards' → /parent/rewards) instead of the 'ask a parent' copy when user.role === 'parent'.

Files: `frontend/src/pages/parent/index.astro`, `frontend/src/pages/rewards.astro`

### [medium/S] Every unverified user gets a permanent 'verify email to unlock all features' banner — but nothing is actually gated, and kids' emails are fake

**Problem.** Layout.astro shows a non-dismissible top banner on every page whenever /api/auth/me-status returns verified:false. Grepping the backend, email_verified gates nothing (it's only read by resend-verification and set by OAuth/verify) — the 'unlock all features' claim is false. Worst case: child accounts created with parent-invented emails (see previous finding) can never verify, so kids on the shared tablet see the nag on every single page forever, with a 'Resend email' button that mails a nonexistent address.

**Fix.** Suppress the banner for child/teen roles (me-status already fetches the full user, so return role too), make it dismissible with a localStorage snooze for parents, and soften the copy to match reality ('Verify your email so you can recover your password').

Files: `frontend/src/layouts/Layout.astro`, `frontend/src/pages/api/auth/me-status.ts`

## KID/TEEN EXPERIENCE

### [high/M] One accidental tap spends points: no redeem confirmation and requires_parent_approval is never enforced

**Problem.** The 'Canjear' button in rewards.astro is a bare POST with no confirmation — one tap by a 7-year-old instantly deducts points. Backend `redeem_reward` (reward_service.py:100-190) deducts immediately, sends a push notification only to the kid themself, and never notifies a parent; the `Reward.requires_parent_approval` column (models/reward.py:42, commented 'High-value rewards') is checked nowhere in the redeem path, so there is no pending/fulfillment state — the parent may never learn the kid redeemed '30 min screen time'.

**Fix.** Add a confirm step in rewards.astro (native dialog like the gig-proof modal), push-notify parents on every redemption, and honor requires_parent_approval by creating a pending redemption the parent approves (mirroring the existing gig approval queue pattern).

Files: `frontend/src/pages/rewards.astro`, `backend/app/services/reward_service.py`, `backend/app/models/reward.py`

### [high/S] Gig proof photo is silently lost on upload (wrong URL + wrong response field)

**Problem.** Both gig pages upload proof photos from the browser to `/api/task-assignments/proof-upload`, but no such Astro route exists (the proxy lives at `/api/assignments/proof-upload`), so the fetch 404s every time. The `if (uploadRes.ok)` guard swallows the failure and submits the claim anyway with `proof_image_url: null` — and even if the URL worked, the code reads `.url` while the endpoint returns `{proof_image_url}` (backend task_assignments.py:220, proxy proof-upload.ts:7). A teen photographs their finished work, taps 'Enviar para aprobación', gets a success state, and the parent reviews a claim with no photo — risking rejection and a broken trust streak.

**Fix.** In both gig pages, change the upload URL to `/api/assignments/proof-upload`, read `data.proof_image_url` (copy the working pattern from dashboard.astro:641-644), and abort with a visible inline error if the upload fails instead of silently continuing.

Files: `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/gigs/my-gigs.astro`, `frontend/src/pages/api/assignments/proof-upload.ts`, `backend/app/api/routes/task_assignments.py`

### [high/S] Completing a chore is silent — the confetti celebration is dead code for the core loop

**Problem.** dashboard.astro fires confetti + points-badge pulse only when `[data-flash-success]` renders, which requires the `flash` cookie. But the completion proxy (api/assignments/complete.ts) only ever sets `flash_error` on failure — on success it redirects with no cookie at all. The only places that set a success `flash` are rewards redemption and the parent-only patch.ts. So the kid's most frequent action (tap the check circle on a chore) produces a full page reload where the card just vanishes into a collapsed <details> — zero reward feedback, despite the celebration code already existing.

**Fix.** In complete.ts, on `response.ok` append `Set-Cookie: flash=+N pts` (the backend PATCH response includes the assignment/points; localize with the lang cookie) so the existing confetti and points-pulse actually fire after every completion.

Files: `frontend/src/pages/api/assignments/complete.ts`, `frontend/src/pages/dashboard.astro`

### [medium/M] Kiosk is display-only: kids can't check off a chore from the shared tablet

**Problem.** kiosk.astro renders a read-only snapshot (events, tasks with checkboxes that are pure decoration, member tallies, shopping counts) and hard-reloads every 60s via `location.reload()`. On the shared family tablet — its stated purpose — a kid who sees their chore listed must go find their own device and log in to mark it done, and the full reload flickers and resets scroll.

**Fix.** Add tap-to-complete: tap a task → pick your avatar/name to confirm → POST to a kiosk-token-scoped completion endpoint (extend /api/kiosk with a write action guarded by the same token); replace the 60s reload with a fetch-based re-render.

Files: `frontend/src/pages/kiosk.astro`, `backend/app/api/routes/kiosk.py`, `frontend/src/pages/api/kiosk/[...path].ts`

### [medium/S] Pending chores don't show what they're worth in points

**Problem.** In dashboard.astro, pending required-task cards render title, description, and DifficultyChip only (lines 273-299); the point value appears only after completion ('+N pts earned', line 324), while bonus cards do show '+N pts' up front (line 380). A kid staring at their goal banner ('faltan 45 pts') cannot connect it to any action — they can't tell which chore gets them there.

**Fix.** Add the same '+{a.template_points} pts' chip used on bonus cards to pending required cards next to the DifficultyChip, so every card answers 'what do I earn?' before the kid does the work.

Files: `frontend/src/pages/dashboard.astro`

### [medium/S] Pet Feed/Play fail silently, and task-earned XP is invisible at the moment it's earned

**Problem.** pet.astro's POST handler captures errors for create/treat but ignores the result of feed/play entirely (lines 25-28); backend raises ValidationException('Pet is not hungry') (pet_service.py:107), so a kid taps 'Alimentar', the page reloads, and nothing changes with no explanation. Meanwhile the pet IS wired into the loop backend-side (task_assignment_service.py awards pet XP on completion at ~lines 704/726/1108), but nothing on the dashboard ever says so — the pet reads as an orphan tab.

**Fix.** Capture `ok/error` for feed/play into errorMsg like the treat path does, and include the pet XP gain in the completion flash from finding #2 (e.g. '+10 pts · Firulais +5 XP ⭐') so the pet visibly reacts to chores.

Files: `frontend/src/pages/pet.astro`, `backend/app/services/pet_service.py`, `backend/app/services/task_assignment_service.py`, `frontend/src/pages/api/assignments/complete.ts`

### [low/S] Gig claim/submit feedback is a blank reload plus blocking alert() errors

**Problem.** On the gig board and My Gigs, both claim and proof-submit handlers do `window.location.reload()` on success — no confetti, no flash, the teen must scan the page to notice the '⏳ Awaiting approval' pill changed — and errors surface as `alert(err.detail ?? "Error")`, a raw backend string that is English-only and jarring on mobile (gigs/index.astro:194,236; my-gigs.astro:197). The moment a gig gets approved (+$MXN, the biggest payoff in the app) also has no celebratory moment anywhere.

**Fix.** Set the same `flash` cookie before reload (or render inline success state) and replace alert() with an inline localized error banner reusing the existing flashError styles; reuse the dashboard confetti when a claim's status transitions to approved.

Files: `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/gigs/my-gigs.astro`

## PARENT WORKFLOWS

### [high/M] Cash payout step is disconnected from the approval loop and nearly unreachable

**Problem.** Approving a gig claim accrues cash, but /parent/payouts is linked ONLY from the /parent/gigs header (parent/gigs.astro:61-66). The parent dashboard grid (parent/index.astro:167-437) has 10 tiles -- tasks, rewards, members, consequences, approvals, assignments, settings, Jarvis, chat, budget -- but no Gigs and no Payouts tile, and the per-kid oversight cards show points but never pending cash. So after approving cash work in /parent/approvals there is zero affordance telling the parent money is now owed or where to settle it.

**Fix.** Add a pending-cash chip to each kid card on the parent dashboard (the /api/cash/family data payouts.astro already fetches) linking to /parent/payouts, and after approving a gig item in approvals.astro show an inline 'owe $X -- pay out' link.

Files: `frontend/src/pages/parent/index.astro`, `frontend/src/pages/parent/payouts.astro`, `frontend/src/pages/parent/approvals.astro`

### [high/S] Gig-claim push notification deep-links to a page that no longer shows the queue

**Problem.** When a kid submits gig-board work, `_notify_parents_pending` creates the parent notification with link="/parent/gigs?tab=pending" (gig_claim_service.py:174), and NotificationService.create pushes that URL to the parent's phone. But /parent/gigs no longer renders pending claims -- the page itself says claims moved to the unified /parent/approvals queue (parent/gigs.astro:22-24), and no frontend code handles ?tab=pending. The parent taps the push, lands on the gig management page, and must find the 'Review submitted work' link to actually act -- the single most frequent notification->action path in the app has a dead-end landing.

**Fix.** Change the link in _notify_parents_pending to "/parent/approvals" (matching the legacy bonus-task path in task_assignment_service.py:806 and PushService.fan_out_pending_gig which already use it). One-line fix.

Files: `backend/app/services/gig_claim_service.py`, `frontend/src/pages/parent/gigs.astro`

### [high/S] Approvals queue is strictly one-by-one with no batch action, despite AI scores already on screen

**Problem.** approvals.astro renders each pending item with its own Approve/Reject buttons and per-item POST (lines 199-231); there is no 'approve all' or multi-select, so a parent clearing 2 kids x 3 chores does 6 tap-and-wait cycles on the phone. The page already displays an AI validation score badge per item (lines 99-113) but never uses it to reduce work, and when the last item is approved it does a full window.location.reload() (line 220) instead of showing the empty state in place.

**Fix.** Add a sticky 'Approve all' button (and optionally 'Approve all AI >= 70%') that loops the existing single-approve endpoints client-side with a progress count -- no backend change needed. Swap the final reload for injecting the existing empty-state markup.

Files: `frontend/src/pages/parent/approvals.astro`

### [medium/M] Parent cannot mark a chore completed from the assignments calendar

**Problem.** The edit-assignment modal in assignments.astro only offers reassign, reschedule, and a status select limited to 'pending'/'cancelled' (lines 496-499). When a parent watches the kid do the chore in person (or the kid has no device), there is no way to complete it on their behalf -- the only workaround is the free-text manual points-adjust form buried in members.astro, which bypasses streaks/pet/history. Completed cells are also disabled buttons (editable check at line 301), so a mis-tap completion can't be reverted either.

**Fix.** Add a 'mark completed (award points)' option to the status select that calls the completion endpoint on behalf of the assignee (parent-authorized), reusing the existing award path in task_assignment_service so points/pet/onboarding stay consistent.

Files: `frontend/src/pages/parent/assignments.astro`, `backend/app/services/task_assignment_service.py`

### [medium/M] Quick point adjustments on Members are typing-heavy full-page form posts

**Problem.** The adjust-points row in members.astro (lines 372-396) is a 20px-wide number input plus a mandatory free-text reason, submitted as an SSR POST that re-renders the whole page (and can re-submit on refresh). Giving a quick '+5 helped with groceries' on a phone means two fields of typing per kid, and the destructive permanent-delete button sits in the same button row as Edit/Deactivate (lines 360-369) guarded only by a confirm().

**Fix.** Replace the row with +/- stepper chips (+5/+10/-5) and a preset-reason dropdown posting via fetch with an inline toast (the toast lib is already imported on this page), and visually separate or move the permanent delete behind the Edit modal.

Files: `frontend/src/pages/parent/members.astro`

### [medium/S] No pending-approvals badge on the persistent nav -- parents must visit /parent to learn work is waiting

**Problem.** BottomNav.astro fetches and badges only the notifications unread count (lines 14-23, 69-74); the parent 'Manage' item (/parent, line 130) has no badge. The pending-approvals count is computed server-side on parent/index.astro (lines 27-33) and shown only as a badge on that page's grid tile, so a parent living in /budget, /chat, or /gigs sees no signal that kids submitted work unless a push got through.

**Fix.** Reuse the two pending-approvals fetches (or add a cheap combined count endpoint) in BottomNav for role=parent and render the same red count badge on the Manage item that notifications already has.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/pages/parent/index.astro`

### [low/S] Approval errors surface as raw alert() with response body text

**Problem.** On approve/reject failure, approvals.astro does alert(`Error: ${err}`) with the raw response text (lines 222-227), and parent/gigs.astro does the same for gig save/archive (lines 250, 268). On a phone this shows a blocking native dialog possibly containing a JSON validation blob -- confusing for the Spanish-speaking parents and inconsistent with the toast pattern already used in members.astro.

**Fix.** Swap alert() for the existing showToast helper (frontend/src/lib/toast) with a translated generic message, keeping the raw detail in console.error.

Files: `frontend/src/pages/parent/approvals.astro`, `frontend/src/pages/parent/gigs.astro`

## BUDGET UX

### [high/M] Envelope funding is one-category-per-modal with a full page reload; backend auto-fill is never exposed

**Problem.** AssignFundsModal handles exactly one category per interaction and then does `window.location.reload()` after 800ms (line ~212). Budgeting a month across ~10 categories means 10 rounds of: open modal, scroll a giant `Group → Category` native select, type an amount, wait for a reload. Meanwhile the backend already has `POST /api/budget/allocations/auto-fill` with 5 strategies (per CLAUDE.md), and a grep shows zero frontend references to auto-fill — 'copy last month', the single most common monthly action, doesn't exist in the UI.

**Fix.** Add a 'Copiar mes anterior' button next to Ready-to-Assign that calls the existing auto-fill endpoint, and make the modal a multi-assign list (each category row with an inline budgeted-amount input, one save) with optimistic DOM updates instead of reload-per-category.

Files: `frontend/src/components/AssignFundsModal.astro`, `frontend/src/pages/budget/index.astro`, `frontend/src/components/BudgetCategoryGroup.astro`

### [high/S] Post-scan 'Edit' and duplicate 'Open original' links go to a page that doesn't exist (404)

**Problem.** scan-receipt.astro builds links to `/budget/transactions/${transaction_id}` in two places: the confirm card's Edit button (line ~432) and the duplicate-warning modal's 'Open original' (line ~483). There is no `/budget/transactions/[id]` page — `frontend/src/pages/budget/transactions/` contains only `new.astro` (itself a 301 redirect). So right after the flagship scan flow, tapping Edit or Open original lands the parent on a 404 and they must hunt for the transaction manually in the list.

**Fix.** Support a `?tx=<id>` query param in transactions.astro that auto-opens the existing edit bottom-sheet for that transaction (the openModal(txData) machinery is already there), and point both scan-receipt links at `/budget/transactions?tx=<id>`.

Files: `frontend/src/pages/budget/scan-receipt.astro`, `frontend/src/pages/budget/transactions.astro`

### [high/S] Transactions page is hard-locked to the current month — no way to see last month's spending

**Problem.** transactions.astro computes startOfMonth/endOfMonth from `new Date()` (lines 42-47) and never reads a month from the URL; the filter bar only offers account/category/search. On July 1st every June expense vanishes from the list and there is no path back to it ('Showing Jul 1 — Jul 31' footer with no controls). The budget dashboard has month navigation, but the transaction list — where a parent actually verifies charges — does not.

**Fix.** Read `?year=&month=` like index.astro does and add prev/next month chevrons (or reuse BudgetMonthNav) above the filter bar; carry the params through the existing applyFilters() URL builder.

Files: `frontend/src/pages/budget/transactions.astro`

### [high/S] FAB quick-add makes you re-pick the account every time, retype payees, and can't backdate

**Problem.** In FABModal the account select always resets to '--' (resetForm, line ~233) even though a family uses 1-3 accounts with one dominant; payee is a bare text input with no suggestions even though `/api/budget/payees/` exists (only category auto-suggest is wired); and there is no date field — `date: today` is hardcoded (line ~312), so logging yesterday's dinner means save-then-find-then-edit. Together the '#1 job: log what I just spent' costs several avoidable taps/typing on every single entry.

**Fix.** Persist the last-used account in localStorage (or preselect when only one account exists), attach a `<datalist>` of existing payee names, and add a compact date field defaulting to today with a 'yesterday' chip.

Files: `frontend/src/components/FABModal.astro`

### [medium/S] No UI path to record income — FAB always posts a negative amount

**Problem.** FABModal is titled 'Register expense' and posts `amount: Math.round(amount * -100)` (line ~314) unconditionally; the only create surfaces are this FAB, scan-receipt, and CSV import. To record salary or a cash gift the parent must create a fake expense and then flip it via the edit modal's Expense/Income toggle (which exists only in transactions.astro's edit sheet). Income totals on the dashboard depend on this.

**Fix.** Add the same Expense/Income toggle the edit sheet already has to the FAB entry step and sign the amount accordingly; when Income is selected, show income categories (index.astro already passes them, transactions.astro filters them out — unify on all categories).

Files: `frontend/src/components/FABModal.astro`, `frontend/src/pages/budget/transactions.astro`

### [medium/S] Receipt-draft review asks parents to edit amounts in raw negative cents and offers no category/account fix

**Problem.** receipt-drafts.astro's override form exposes `Amount (cents)` with placeholder 'e.g. -15050' (lines 217-224) — a parent correcting a $150.50 ticket must know to type -15050. The form also has no category or account inputs (the `l` dict defines `category`/`account` labels that are never used), so approved drafts land uncategorized and need a second edit. On top of that the inline script hardcodes English status strings ('Creating...', 'Transaction created!', 'Network error') for the Spanish-speaking family, ignoring the `l` translations.

**Fix.** Switch the amount input to pesos with `step=0.01` and convert to negative cents on submit; add category and account selects to the override form (approve endpoint accepts overrides); pass the `l` strings into the script via define:vars.

Files: `frontend/src/pages/budget/receipt-drafts.astro`

### [medium/S] Two different 'money left' numbers stacked with no explanation: 'Ready to Assign' vs 'Available'

**Problem.** The dashboard header shows Ready to Assign = income − budgeted (BudgetMonthNav big number), and immediately below it MonthSummaryBar shows 'Available' = income − spent (line 12). A non-YNAB parent sees two adjacent, differently-sized 'leftover' figures that rarely match and has no cue which one means 'can I spend?'. This is the core envelope concept and it's presented ambiguously on the app's main budget screen.

**Fix.** Rename MonthSummaryBar's third stat to 'Flujo del mes / Net this month' (or drop it in favor of budgeted-vs-spent) and add a one-line helper under Ready to Assign ('Dinero sin asignar a sobres'), so only one number reads as 'left to use'.

Files: `frontend/src/components/MonthSummaryBar.astro`, `frontend/src/components/BudgetMonthNav.astro`, `frontend/src/pages/budget/index.astro`

### [low/S] Search reloads the whole page per keystroke-burst (losing keyboard focus), and the account-required error throws 'es is not defined'

**Problem.** In transactions.astro, applyFilters() sets `window.location.href` on a 500ms debounce for the search box, yet the search match is computed client-side over already-fetched rows (lines 85-92) — so every pause while typing costs an SSR round-trip and dismisses the mobile keyboard/focus. Separately, the edit-save handler references `es` inside a `define:vars={{ token }}` script (line ~620) where `es` is not defined, so saving with no account shows the literal error 'es is not defined' instead of 'Selecciona una cuenta'.

**Fix.** Filter the rendered `.tx-row` elements in place for search (keeping URL sync via history.replaceState) and reserve full navigation for account/category changes; pass `es`/translated strings into the edit-modal script via define:vars.

Files: `frontend/src/pages/budget/transactions.astro`

## MOBILE ERGONOMICS & PWA

### [high/M] Gig proof photo is silently discarded when the upload fails, and capture= blocks gallery photos

**Problem.** In gigs/index.astro:212-227, if the proof-image POST to /api/task-assignments/proof-upload fails (backend caps at MAX_PROOF_BYTES = 5 MB in backend/app/core/upload_validation.py:15 — a fresh phone camera JPEG regularly exceeds that), the code just skips the URL and completes the claim with `proof_image_url: null`. The kid believes the photo was sent; the parent sees a claim with no evidence. Worse, the file input has `capture="environment"` (gigs/index.astro:146, my-gigs.astro:125), which on iOS/Android forces a live camera shot — a kid who already photographed the finished chore can't pick it from the gallery. No client-side compression exists (no canvas/toBlob anywhere in these pages).

**Fix.** Downscale the image client-side (canvas to ~1600px JPEG q0.8) before upload — this both defeats the 5 MB cap and makes uploads fast on mobile data; if the upload still fails, abort the submit with a visible error instead of completing proof-less. Drop `capture` (or keep two buttons like scan-receipt.astro does: 'Take photo' + 'Choose from gallery').

Files: `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/gigs/my-gigs.astro`, `backend/app/core/upload_validation.py`, `frontend/src/pages/budget/scan-receipt.astro`

### [high/S] Service worker is never registered unless the user taps 'Enable push'

**Problem.** The only `navigator.serviceWorker.register('/sw.js')` call in the codebase is inside EnablePushButton's click handler (frontend/src/components/EnablePushButton.astro:56). Layout.astro never registers it, so for everyone who hasn't tapped that one button, the entire sw.js machinery — offline.html fallback, cache-first /_astro/ asset caching, notificationclick routing — is dead code, even though the Layout install banner actively pushes users to install the PWA. An installed app opened offline shows the browser's dino error page instead of the shipped offline shell.

**Fix.** Register /sw.js unconditionally in Layout.astro (a tiny `is:inline` script guarded by `'serviceWorker' in navigator`), and have EnablePushButton reuse `navigator.serviceWorker.ready` instead of registering. One line of code makes offline fallback and asset caching real for every visitor.

Files: `frontend/src/layouts/Layout.astro`, `frontend/src/components/EnablePushButton.astro`, `frontend/public/sw.js`

### [medium/M] Bottom nav crams 10 targets including one-tap logout; icon-only and ~32px wide on phones

**Problem.** A parent gets 8 destinations + lang-toggle + logout in BottomNav.astro (lines 38-162). Items use `px-1 py-1` around a 24px icon, and under 430px labels become sr-only (style block lines 212-225), leaving ten unlabeled ~32px-wide targets — below the 44px minimum — in a scrollable row with hidden scrollbar. Logout is a plain one-tap form submit (line 153) sitting at the end of the row next to the lang toggle: on the family's shared tablet, a kid's mis-tap logs the parent out with no confirmation. DrawerMenu exists but is only used on budget pages (BudgetShell), so logout/lang have no other home.

**Fix.** Move logout and the lang toggle out of the nav (into the /profile page or a drawer available app-wide) and add a confirm step to logout; cap the nav at ~5 per role with min-w-[44px] targets and keep labels visible. This is the single highest-traffic component in the app.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/components/DrawerMenu.astro`, `frontend/src/pages/profile.astro`

### [medium/S] Every page render blocks on an SSR unread-count API call with no timeout

**Problem.** BottomNav.astro:13-25 awaits `/api/notifications/unread-count` in component frontmatter, and apiFetch (frontend/src/lib/api.ts) is a bare fetch with no AbortSignal/timeout. Since ClientRouter was removed (Layout.astro:83 comment), every navigation is a full page reload, so every single page-to-page tap on the phone re-pays this serial backend round-trip — and if the backend is slow, every page in the app hangs at TTFB just to draw a badge.

**Fix.** Move the unread badge to a client-side fetch after `astro:page-load` (render the nav instantly, patch the badge async), or at minimum wrap the SSR call in AbortSignal.timeout(400). Also consider re-adding ClientRouter so BottomNav persists across navigations — the fade `transition:animate` on Layout.astro:77 is currently a no-op without it.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/lib/api.ts`, `frontend/src/layouts/Layout.astro`

### [medium/S] Push button never reflects subscribed state and gives no iOS guidance

**Problem.** EnablePushButton renders `data-state="idle"` with 'Activar notificaciones' on every dashboard/parent-home visit forever — there is no load-time check of `Notification.permission` or `pushManager.getSubscription()` (frontend/src/components/EnablePushButton.astro:12-34), so already-subscribed users see a perpetual call-to-action. On iOS Safari outside the installed PWA, subscribe() throws and the user just sees 'Error', with no hint that iOS requires Add-to-Home-Screen first (16.4+). Meanwhile the backend push pipeline is fully wired (pet, notification, task, reward services all call PushService), so this button is the only bottleneck to delivery.

**Fix.** On astro:page-load, check permission + existing subscription: hide the button (or show a quiet 'Notificaciones activas' state) when subscribed; when permission is 'denied' show how to re-enable; on iOS non-standalone replace the button with the 'install first' tip that already exists in Layout's install banner.

Files: `frontend/src/components/EnablePushButton.astro`, `frontend/src/pages/dashboard.astro`, `frontend/src/pages/parent/index.astro`, `backend/app/services/push_service.py`

### [medium/S] Google Fonts loaded render-blocking from CDN on every page — slow on mobile data, broken offline

**Problem.** Head.astro:59-64 pulls two font families from fonts.googleapis.com as render-blocking CSS on every full-page navigation (and there are only full-page navigations — no ClientRouter). On Mexican mobile networks this adds a cross-origin DNS+TLS round-trip to first paint on every tap, and sw.js only caches same-origin requests (sw.js:42), so in installed/offline mode fonts always fail and the app flashes fallback type.

**Fix.** Self-host the needed Nunito + Plus Jakarta Sans weights as woff2 in frontend/public/fonts/ with `font-display: swap`, add them to PRECACHE_ASSETS in sw.js, and drop the two preconnects. Roughly 6 files and a @font-face block in global.css.

Files: `frontend/src/components/meta/Head.astro`, `frontend/public/sw.js`, `frontend/src/styles/global.css`

### [low/S] PWA manifest is English-only and portrait-locked for a Spanish-speaking family

**Problem.** manifest.webmanifest hard-codes `"lang": "en"`, English-only shortcut names ('Today's chores', 'Rewards'), and `"orientation": "portrait"` — so the installed app's long-press shortcuts appear in English for the Spanish-speaking household, and the portrait lock fights the kiosk/shared-tablet use case (frontend/src/pages/kiosk.astro) where tablets typically sit landscape in a stand.

**Fix.** Serve the manifest from a dynamic Astro endpoint (e.g. /manifest.webmanifest.ts) that reads the lang cookie to localize name/shortcuts (or simply default everything to es-MX since the real users are Spanish-speaking), and change orientation to "any". Add /kiosk as a third shortcut.

Files: `frontend/public/manifest.webmanifest`, `frontend/src/components/meta/Head.astro`, `frontend/src/pages/kiosk.astro`

## FEEDBACK, LOADING, ERROR & EMPTY STATES

### [high/S] Failed chat messages vanish silently — error banner is unreachable dead code

**Problem.** In chat.astro the POST handler sets errorMsg when the backend send fails (line 20) but then unconditionally runs `return Astro.redirect("/chat")` (line 22). The redirect re-renders the page fresh, so the error banner at line 77 can never appear, and the kid's typed message is discarded with zero feedback — it just never shows up in the feed.

**Fix.** On failure, set a `flash_error` cookie before redirecting (the exact pattern already used in api/assignments/complete.ts) and render it in the existing errorMsg slot; better, convert send to a fetch() that keeps the input's text on failure and shows showToast(error). Also disable the Send button while in flight.

Files: `frontend/src/pages/chat.astro`, `frontend/src/pages/api/assignments/complete.ts`

### [high/S] Gig proof photo upload failure is silently swallowed — claim submits without the photo

**Problem.** In gigs/index.astro the complete-form handler uploads the proof image and only reads the URL `if (uploadRes.ok)` (lines 212-222); if the upload fails (413, timeout, offline camera photo on mobile) it proceeds to POST /complete with `proof_image_url: null`. The kid believes their evidence photo was sent; the parent sees a proof-less claim in approvals and may reject it.

**Fix.** Check `uploadRes.ok`; on failure abort the submit, re-enable the button, and show a translated message ('No se pudo subir la foto — inténtalo de nuevo') without losing the typed proof_text. Mirror the fix in dashboard.astro's gig-proof modal, which shows hardcoded-English 'Upload failed: ...' (line 646).

Files: `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/dashboard.astro`

### [medium/M] Toast system exists but 11 pages still use blocking alert() with raw English API errors

**Problem.** lib/toast.ts + ToastContainer.astro are built (auto-dismiss, pause-on-hover, escape-safe) but only 4 pages use showToast (login, parent/members, budget/import, budget/settings). 11 pages use alert(): parent/approvals.astro does ``alert(`Error: ${err}`)`` where err is `await r.text()` — a raw JSON blob with an English `detail` — and gigs/index.astro does `alert(err.detail ?? "Error")`, showing English backend strings (e.g. premium.py's "requires a plus plan or higher") to the Spanish-speaking family in an OS-modal that blocks the page.

**Fix.** Replace alert() with showToast(message, 'error') across the 11 pages and translate: map known backend error shapes (detail.error === 'upgrade_required', duplicate claim, etc.) to ES/EN strings instead of dumping response text.

Files: `frontend/src/lib/toast.ts`, `frontend/src/pages/parent/approvals.astro`, `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/gigs/my-gigs.astro`, `frontend/src/pages/parent/gigs.astro`, `backend/app/core/premium.py`

### [medium/M] SkeletonLoader and UpgradePrompt are dead components — no loading or upsell states actually render

**Problem.** grep shows zero imports of SkeletonLoader.astro (3 ready variants) and UpgradePrompt.astro anywhere in src/. Every page is SSR-blocking, so a slow backend means a blank tab with no skeleton; and when premium gating fires (403 upgrade_required from premium.py), scan-receipt.astro line 318 shows a plain alert() instead of the designed UpgradePrompt card with usage meter and 'Ver Planes' CTA — the upsell path the component was built for never happens.

**Fix.** Wire UpgradePrompt into the 403/upgrade_required handling on gated pages (scan-receipt, reports, goals, import) — render it in-place with feature/plan_needed/current_usage from the error detail, which the backend already returns. Adopt SkeletonLoader in the client-fetched panels (price-comparison in transactions edit modal, receipt-drafts) or delete both components.

Files: `frontend/src/components/UpgradePrompt.astro`, `frontend/src/components/SkeletonLoader.astro`, `frontend/src/pages/budget/scan-receipt.astro`, `backend/app/core/premium.py`

### [medium/S] Approving work gives no success confirmation and leaves stale counters

**Problem.** In parent/approvals.astro a successful approve/reject just does `li.remove()` (line 219) — no toast confirming '+5 pts otorgados a Emma', and the section headers 'Chores & bonus (3)' keep the old count until every item is cleared (full reload only when remaining()===0). The page even reads a `flash` cookie (lines 26-27) but never renders it, so any success flash routed here is eaten silently.

**Fix.** On success call showToast with the kid's name and points/cash awarded (data is already in the row), decrement the section count in the header, and either render the consumed flash cookie or stop deleting it.

Files: `frontend/src/pages/parent/approvals.astro`

### [medium/S] No double-submit protection on dashboard task-complete buttons — double-tap shows a false error after success

**Problem.** Required-task completion in dashboard.astro is a native form POST (line 287) with no button disabling. A kid double-tapping on a slow tablet fires two PATCH /complete calls: the first succeeds, the second fails and api/assignments/complete.ts sets `flash_error` (line 42), so after redirect the kid sees a red error banner ('Cannot complete task') even though the task completed and confetti context is lost.

**Fix.** Add a shared submit listener on `form[data-complete-form]` that disables the button and swaps in a spinner once submitted (the bonus-path modal already prevents re-entry; the required path needs the same 3 lines).

Files: `frontend/src/pages/dashboard.astro`, `frontend/src/pages/api/assignments/complete.ts`

### [medium/S] Transaction edit modal can show the literal error 'es is not defined' to the user

**Problem.** In budget/transactions.astro the save handler lives in a `<script define:vars={{ token }}>` block but line 620 references the frontmatter-only `es` variable (`errorDiv.textContent = es ? "Selecciona una cuenta" : ...`). When the account select is empty (e.g. the tx's account was deleted), that throws a ReferenceError inside the try, and the catch renders `err.message` — the user literally sees 'es is not defined' in the modal.

**Fix.** Pass `es`/`lang` through define:vars (the price-comparison script two blocks below already does `define:vars={{ lang }}`), and while there, translate the other hardcoded 'Enter a valid amount' string in the same handler (line 610).

Files: `frontend/src/pages/budget/transactions.astro`

### [low/S] Chat emoji reactions do a full page reload per tap and fail silently

**Problem.** chat.astro's reaction handler awaits the POST/DELETE then calls `location.reload()` (line 222) — a full SSR round-trip (4 API calls in frontmatter) just to toggle one emoji, which also kills the live SSE stream and re-scrolls the feed. The `catch {}` (line 223) swallows failures entirely, so on flaky mobile networks the tap appears to do nothing.

**Fix.** Optimistically toggle the reaction chip in the DOM (increment/decrement count, flip data-toggle and classes) without reloading; revert and showToast on a non-ok response.

Files: `frontend/src/pages/chat.astro`

## FORMS & INPUT FRICTION

### [high/S] Edit-transaction validation shows 'es is not defined' instead of 'Select an account'

**Problem.** In /Users/jc/dev-2026/AgentIA/family-task-manager/frontend/src/pages/budget/transactions.astro line 620, the save handler runs `errorDiv.textContent = es ? "Selecciona una cuenta" : "Select an account"` inside a `<script define:vars={{ token }}>` block — only `token` is injected, and `const es` on line 19 is server-side frontmatter. When a user saves with an empty account, the ReferenceError is caught by the outer try/catch and the error box literally displays 'es is not defined'. The Spanish-speaking family sees a cryptic English JS error in their most-edited form.

**Fix.** Add `lang` (or a precomputed `errAccount` string, as FABModal.astro already does with errAmount/errCategory/errAccount) to the define:vars of that script, or derive `const es = document.documentElement.lang === 'es'` at the top of the IIFE like the dedup handler on line 819 already does.

Files: `frontend/src/pages/budget/transactions.astro`

### [high/S] Quick-expense FAB never remembers account/category and offers no payee suggestions

**Problem.** FABModal.astro is the only manual transaction entry path and it resets account and category to '--' on every open (resetForm, lines 229-240). A parent logging 3-4 expenses a day re-picks the same account from a select every single time — even when the family has exactly one account. The payee field is free text with autocomplete="off" and there is no <datalist> anywhere in the frontend (grep confirms zero datalist usage), despite `/api/budget/payees` existing, so 'Soriana'/'Oxxo' gets fully retyped on a phone keyboard each visit.

**Fix.** Preselect the account when `accounts.length === 1`; otherwise persist last-used account_id and category_id in localStorage and restore them on open. Render a `<datalist id="fab-payees">` from the payees API (already fetched family-scoped) so payee autocompletes after 2 chars — this also makes the existing categorization-rule suggest fire more reliably.

Files: `frontend/src/components/FABModal.astro`, `frontend/src/pages/budget/transactions.astro`

### [medium/M] Task create and edit forms have drifted into two different products

**Problem.** TaskCreateModal.astro (chip UI, gig-mode hidden unless bonus, background auto-translate, points input min="0" but JS requires >=1) and parent/tasks/[id]/edit.astro (select UI, gig-mode always visible, manual translate button, points min=1 max=1000) are fully duplicated implementations. Concretely: late-penalty options (auto_late_penalty, restriction type/severity/days, edit.astro lines 331-365) do not exist at create time — the create payload hardcodes `auto_late_penalty: false` (TaskCreateModal line 550) — so a parent must create a task and then immediately re-open it in a second, differently-styled form to configure the penalty.

**Fix.** Extract a shared TaskTemplateForm component (or at minimum add the late-penalty <details> block to the create modal's Advanced section and align points min/max constraints). Pick one assignment/difficulty control style so the parent isn't relearning the form between create and edit.

Files: `frontend/src/components/TaskCreateModal.astro`, `frontend/src/pages/parent/tasks/[id]/edit.astro`

### [medium/S] No way to record income from the quick-add — sign is hardcoded negative

**Problem.** FABModal.astro line 314 posts `amount: Math.round(amount * -100)` — always an expense — and /budget/transactions/new.astro is just a 301 redirect back to the list. The edit bottom sheet in transactions.astro (lines 314-321) has an Expense/Income toggle, so recording a payday or allowance deposit requires: create a fake expense, find it in the list, open the edit sheet, tap Income, save, wait for full page reload. That's ~6 extra taps plus a reload for a routine action.

**Fix.** Copy the existing Expense/Income toggle from the edit sheet into FABModal (same setTypeUI pattern) and multiply by -1 only when expense is selected. The backend already accepts positive amounts unchanged.

Files: `frontend/src/components/FABModal.astro`, `frontend/src/pages/budget/transactions/new.astro`

### [medium/S] Backdrop tap wipes half-completed modal forms with no confirmation

**Problem.** TaskCreateModal.astro closeModal() calls resetModal() (lines 422-455) which clears the task name, points, member checkboxes, and chip selections; the backdrop click is wired directly to closeModal (line 759). FABModal does the same (closeModal → resetForm, lines 219-240). On a phone, the backdrop is exposed all around the sheet, so one stray thumb tap while scrolling the member list throws away everything typed — including a custom task name and description — with zero warning.

**Fix.** Only reset the form after a successful submit (move resetModal/resetForm calls out of closeModal into the success path plus explicit open), or if any field is dirty, require a confirm ('Discard task?') before backdrop/Escape closes. Keeping state means an accidental dismiss costs one tap to recover instead of a full re-entry.

Files: `frontend/src/components/TaskCreateModal.astro`, `frontend/src/components/FABModal.astro`

### [medium/S] Register/login forms have zero autocomplete attributes and submit-and-pray password matching

**Problem.** register.astro has 6 fields with no autocomplete attrs at all (grep confirms none in register.astro or login.astro): email lacks autocomplete="email", passwords lack "new-password", so iOS/Android password managers never offer to generate or save credentials — the exact users (family members on phones) who most need it. Password mismatch is only detected on submit (line 252), after typing two masked 8+ char passwords. The optional family-code field also sits above all required fields, front-loading the rare join-existing-family case.

**Fix.** Add autocomplete="email", "name", "new-password" (register) / "current-password" (login); validate confirm-password on input/blur with an inline message; collapse family code behind a '¿Tienes un código de familia?' toggle so the common create-family path starts at the first required field.

Files: `frontend/src/pages/register.astro`, `frontend/src/pages/login.astro`

### [low/M] Every modal save ends in an artificial 1.5 s wait plus full page reload

**Problem.** InvitationModal.astro (lines 207-211) and EditMemberModal.astro (lines 166-170) show a success message, then setTimeout 1500ms, then window.location.reload(). The transaction edit sheet and delete flow in transactions.astro (lines 648, 680) also reload the whole SSR page — which re-fetches /api/auth/me, drafts count, transactions, accounts, categories, and groups — just to reflect a one-field change. On a phone each small edit costs ~3-5 seconds of dead time.

**Fix.** For member/invitation modals, drop the 1.5 s delay and reload immediately (or patch the row in place). For the transaction edit sheet, update the clicked .tx-row's data-attributes and visible text from the PUT response instead of reloading — the row already carries all fields as data-tx-* attributes, so in-place update is mechanical.

Files: `frontend/src/components/InvitationModal.astro`, `frontend/src/components/EditMemberModal.astro`, `frontend/src/pages/budget/transactions.astro`

## I18N & COPY

### [high/S] Google sign-in never restores the family's language preference

**Problem.** Password login syncs the `lang` cookie from the account's `preferred_lang` (frontend/src/pages/api/auth/login.ts:96-101), but the Google OAuth route (frontend/src/pages/api/oauth/google.ts, 58 lines) only sets auth cookies — no lang sync. Layout.astro:13 and every page default to `?? "en"`, so the real family (Gmail accounts, Spanish-speaking) lands in English on any new device, cleared browser, or shared tablet until they find the toggle. The BottomNav toggle (/api/lang) also only sets the cookie and never writes `preferred_lang` back, so the preference drifts per device.

**Fix.** In google.ts after token exchange, fetch /api/auth/me and set the lang cookie from preferred_lang exactly like login.ts does; make the /api/lang POST also PUT preferred_lang when authenticated. Optionally fall back to Accept-Language instead of hardcoded "en" in Layout.astro:13.

Files: `frontend/src/pages/api/oauth/google.ts`, `frontend/src/pages/api/auth/login.ts`, `frontend/src/pages/api/lang.ts`, `frontend/src/layouts/Layout.astro`

### [high/S] Locale-less dates render US-style (month/day) for Spanish users on SSR

**Problem.** 7 call sites use `toLocaleDateString()` with no locale. The SSR ones render with the Node container's locale (en-US), so a consequence end date shows as "7/2/2026" — which an es-MX family reads as February 7, not July 2. Kid-facing: profile.astro:162-164 (consequence "Until" date); parent-facing: parent/consequences.astro:259-261, budget/settings.astro:398 and :1112, RecycleBinTable.astro:253. Meanwhile calendar.astro:115 and lib/api/budget.ts formatDate already do it right with `lang === "es" ? "es-MX" : "en-US"`.

**Fix.** Pass the existing lang-derived locale to all 7 sites (or reuse formatDate from lib/api/budget.ts). Mechanical one-line fixes; day/month ambiguity on dates that decide when a punishment ends is genuinely confusing.

Files: `frontend/src/pages/profile.astro`, `frontend/src/pages/parent/consequences.astro`, `frontend/src/pages/budget/settings.astro`, `frontend/src/components/RecycleBinTable.astro`

### [medium/M] Gig error alerts show raw backend text in mixed ES/EN, sometimes with UUIDs

**Problem.** Kid-facing gig pages surface `alert(err.detail ?? "Error")` verbatim (gigs/index.astro:194,236, gigs/my-gigs.astro:197, parent/gigs.astro:250). Backend messages are inconsistently bilingual: Spanish ("Ya tienes un reclamo activo para esta gig", gig_claim_service.py:63) next to English with internals leaked ("Claim is {status}, expected claimed" :99, "Gig offering <uuid> not found or not active" :45). approvals.astro:223 alerts the raw response body text. A kid in English mode gets Spanish errors and vice versa; UUIDs read as breakage.

**Fix.** Map the known failure cases (already claimed, role not allowed, chores incomplete, wrong status) to short localized messages client-side keyed off HTTP status/error code, falling back to a generic lang-appropriate string; stop echoing f-string UUIDs in ValidationException messages.

Files: `frontend/src/pages/gigs/index.astro`, `frontend/src/pages/gigs/my-gigs.astro`, `frontend/src/pages/parent/approvals.astro`, `backend/app/services/gig_claim_service.py`

### [medium/M] Same peso amount formats three different ways across surfaces

**Problem.** lib/api/budget.ts:496 formatCurrency renders es-MX "$1,234" (0 decimals) in budget pages, but the kid dashboard hand-rolls "$123.45 MXN" (dashboard.astro:107), payouts uses `$${(cents/100).toFixed(2)}` with no thousands separators (parent/payouts.astro:18,104), transactions shows "$12.34 MXN" (transactions.astro:747), and approvals shows integer "+$50 MXN" (approvals.astro:153) — ~20 inline toFixed(2) sites total. A family comparing the kid's cash badge to the parent payout screen sees different currency styles for the same money.

**Fix.** Export one shared formatMoney(cents, {decimals}) helper (wrapping the existing Intl.NumberFormat es-MX formatter) from a non-budget lib module and swap the ~20 inline sites; decide once whether kid-facing cash shows decimals.

Files: `frontend/src/lib/api/budget.ts`, `frontend/src/pages/dashboard.astro`, `frontend/src/pages/parent/payouts.astro`, `frontend/src/pages/budget/transactions.astro`, `frontend/src/pages/parent/approvals.astro`

### [medium/S] Spanish copy missing accents and inverted punctuation throughout

**Problem.** The entire user base is native es-MX, and the Spanish dictionary reads unpolished: "Gestion", "Descripcion (opcional)", "Titulo (Espanol)", "Ingles" (lib/i18n.ts:604,908-919), the EN-side toggle label "Cambiar a Espanol" (i18n.ts:13), 9 es strings ending "!" without opening "¡" (e.g. "Todo listo!", "Disfruta tu dia!" — also missing día), 3 "?" without "¿" (e.g. "Eliminar?"), plus inline ternaries like "No hay categorias configuradas" / "Crear categorias" (budget/index.astro:149,152).

**Fix.** One copy-edit pass over lib/i18n.ts es block + a grep for accent-less common words (categorias|Descripcion|Titulo|Gestion|dia|sesion) across pages. Pure string edits, no refactor — this is the visible-quality half of the known ternary debt.

Files: `frontend/src/lib/i18n.ts`, `frontend/src/pages/budget/index.astro`

### [medium/S] Budget recycle-bin page is entirely English

**Problem.** RecycleBinTable.astro (442 lines) takes no lang prop: "Deleted Items", "No deleted items", "Your recycle bin is empty", "Restore Item?", "Permanently Delete?", "Empty Recycle Bin?", Cancel buttons, and all JS-rendered rows/toasts are hardcoded English. A Spanish parent recovering an accidentally deleted transaction hits a full destructive-action confirmation flow in the wrong language.

**Fix.** Pass lang from pages/budget/recycle-bin/index.astro into the component and ternary the ~15 user-visible strings plus the script-injected row labels/notifications — consistent with the existing inline-ternary pattern, no framework change.

Files: `frontend/src/components/RecycleBinTable.astro`, `frontend/src/pages/budget/recycle-bin/index.astro`

### [low/S] Kid-facing Spanish uses anglicisms and inconsistent 'gig' gender

**Problem.** Kids see "Pide a un padre que haga el shuffle!" (i18n.ts dashboard_no_assignments) even though the parent UI button is already "Mezclar" (i18n.ts:663) — a kid can't connect "shuffle" to anything on screen. "Gig" flips gender: "esta gig"/"Reclamada" (gig_claim_service.py:50,63; gigs/index.astro:126,161) vs "los gigs" masculine in the intro banner and tour (i18n.ts:945,961).

**Fix.** Replace "shuffle" with "mezclar" in the kid string, and standardize on masculine "el gig" (matching the intro banner) across gigs pages and backend messages — a small find-and-replace copy pass.

Files: `frontend/src/lib/i18n.ts`, `frontend/src/pages/gigs/index.astro`, `backend/app/services/gig_claim_service.py`

## Jarvis AI leverage for UX (cross-cutting)

### [high/M] No deep-link prefill (?q=) — manual high-friction flows can't offer an 'ask Jarvis' shortcut

**Problem.** jarvis.astro never reads Astro.url.searchParams, so no other page can hand off to Jarvis with a prefilled message. Meanwhile the manual alternatives are heavy on a phone: TaskCreateModal.astro is 778 lines with ~12 form controls, FABModal.astro (quick expense) has ~7 fields, and meal/shopping entry is multi-step — all operations Jarvis tools already perform in one sentence with the HITL gate protecting writes.

**Fix.** Support /parent/jarvis?q=<text>&send=1 (prefill input; auto-submit only when send=1) — about 10 lines in the existing astro:page-load handler. Then add contextual shortcuts where friction is highest: a 'o dícelo a Jarvis' link in FABModal and TaskCreateModal footers that deep-links with a domain-specific template (e.g. q='Registra un gasto de ' on budget pages).

Files: `frontend/src/pages/parent/jarvis.astro`, `frontend/src/components/FABModal.astro`, `frontend/src/components/TaskCreateModal.astro`

### [high/S] Pending HITL confirmations vanish on reload — GET /api/jarvis/actions has no UI

**Problem.** Confirm cards for destructive/money-moving tool calls exist only as DOM nodes created from the live SSE 'confirm' event (jarvis.astro lines 223-279). If the parent locks their phone, navigates away, or the page reloads, the card is gone: history rendering (lines 92-109) only shows role/content bubbles, and the action silently expires after 10 minutes (jarvis_pending_action_service.py line 48). The backend already exposes GET /api/jarvis/actions (jarvis.py line 139) but no frontend code calls it — a parent who asked Jarvis to 'pay Emma 50 points' and got interrupted has no way to complete it and no explanation why nothing happened.

**Fix.** On astro:page-load in jarvis.astro, fetch /api/jarvis/actions and render the same confirm card component for each pending action (reuse the existing approve/reject handlers, which already hit /api/jarvis/actions/{id}/approve|reject). Optionally show a small pending-count badge on the Jarvis card in parent/index.astro, mirroring the receipt-drafts nav-badge pattern.

Files: `frontend/src/pages/parent/jarvis.astro`, `backend/app/api/routes/jarvis.py`, `backend/app/services/jarvis_pending_action_service.py`, `frontend/src/pages/parent/index.astro`

### [high/S] Empty state gives zero capability discovery for 140 tools — add tappable example-prompt chips

**Problem.** The chat empty state is just '🤖 No messages yet. Ask Jarvis something.' (jarvis.astro lines 92-96) and the placeholder suggests only soft coaching questions ('How do I balance this week? What do I say to Emma?'). Nothing tells the parent Jarvis can actually create budget transactions, assign chores, post gigs, plan meals, or list pending approvals — capabilities all registered in backend/app/mcp/registry.py. A Spanish-speaking parent will never guess 'Registra $250 de super en OXXO' works, so the tool-calling investment goes unused.

**Fix.** Replace the empty state (and optionally a row above the composer) with 4-6 tappable chips grounded in real registered tools, ES/EN per lang cookie: e.g. 'Registra $250 de super en OXXO' (budget_transaction_create), 'Asigna lavar platos a Emma esta semana' (tasks assignment), '¿Qué falta por aprobar?' (tasks_pending/gig claims), 'Agrega leche a la lista del super' (shopping_item). Tapping fills #message-input and submits via the existing form handler.

Files: `frontend/src/pages/parent/jarvis.astro`, `backend/app/mcp/registry.py`

### [medium/M] Kids get zero Jarvis despite the registry already flagging safe read-only tools

**Problem.** Every /api/jarvis endpoint requires parent role (require_parent_role throughout backend/app/api/routes/jarvis.py), so a kid on the shared tablet cannot ask '¿qué tareas tengo hoy?' even though tasks_today/tasks_pending/tasks_overdue are registered as read-only (registry.py lines 422-440) and every EntitySpec already declares destructive_ops. Kids fall back to navigating dashboard/pet/shopping pages manually — the exact multi-tap friction Jarvis was built to remove.

**Fix.** Add a kid-mode chat that reuses JarvisService.chat_stream with an allowed-tools filter derived from the existing registry metadata: whitelist domains (tasks, pet, shopping, meals, calendar) and drop any op in destructive_ops plus all budget/points/consequences tools; scope task queries to the caller's user_id. Expose it at /jarvis for child/teen roles with the same ChatShell component.

Files: `backend/app/api/routes/jarvis.py`, `backend/app/services/jarvis_service.py`, `backend/app/mcp/registry.py`, `frontend/src/components/ui/ChatShell.astro`

### [medium/S] Jarvis is buried 3 taps deep behind the Manage hub — no persistent entry point

**Problem.** The only way into Jarvis is: BottomNav 'Manage' tab → parent hub → scroll to the Jarvis card (parent/index.astro line 377). BottomNav.astro has an active-state mapping for /parent/jarvis (line 174) but no actual nav item; DrawerMenu.astro is budget-only; WelcomeTour.astro never mentions Jarvis. For the app's single most leveraged feature, every use costs 3 taps plus a scroll, and new parents may never find it.

**Fix.** Give parents a persistent Jarvis affordance: either a floating 🤖 button rendered by the layout for role=parent (the FABButton.astro pattern already exists and is positioned above BottomNav), or swap one BottomNav slot for Jarvis on parent role. Add a WelcomeTour step introducing it. The chat page is plain cookie-authed fetch to /api/jarvis/chat-stream, so no new plumbing is needed.

Files: `frontend/src/components/BottomNav.astro`, `frontend/src/components/FABButton.astro`, `frontend/src/pages/parent/index.astro`, `frontend/src/components/WelcomeTour.astro`

### [medium/S] Scheduled Jarvis replies arrive as mistyped 'shopping_item_added' notifications, truncated to 200 chars

**Problem.** sweep_due delivers schedule results with type=NotificationType.SHOPPING_ITEM_ADDED (jarvis_schedule_service.py line 214) because no Jarvis notification type exists, and truncates the body to 200 characters. On the notifications page the weekly summary a parent scheduled shows up categorized/iconed as a shopping event with its content cut off — confusing and it undermines trust in the schedules feature the jarvis-schedules page works hard to enable.

**Fix.** Add a JARVIS_SCHEDULE member to NotificationType (backend/app/models/notification.py), use it in sweep_due, and render a 🤖 icon for it wherever notifications are listed. Keep link='/parent/jarvis' since the full reply is already persisted to Jarvis history by JarvisService.chat.

Files: `backend/app/services/jarvis_schedule_service.py`, `backend/app/models/notification.py`, `frontend/src/pages/parent/jarvis-schedules.astro`

### [low/S] Dead single-option model dropdown plus per-reply model badge waste mobile header space

**Problem.** The model select has exactly one option pinned to gemini-2.5-flash (jarvis.astro lines 81-90, ALLOWED_MODELS in jarvis.py line 30), yet renders as a full-width dropdown implying a choice, and every bot reply appends a '💎 Gemini 2.5 Flash' badge (lines 283-298). On a phone this costs a header row and repeats meaningless metadata after every message for a family user who doesn't care which LLM answered.

**Fix.** Hide the select while ALLOWED_MODELS has one entry (render it only when the backend exposes >1 model — e.g. return the allowed list from a config endpoint or inline it server-side) and drop the per-reply model badge, or reduce it to a one-time footer note. Keep the localStorage migration logic so re-expansion later still works.

Files: `frontend/src/pages/parent/jarvis.astro`, `backend/app/api/routes/jarvis.py`

## gaps

### [high/M] Invisible overdue chores soft-lock the entire bonus/gig economy with a self-contradictory message

**Problem.** No auditor looked at what happens the day AFTER a missed chore. The sweep flips yesterday's PENDING chores to OVERDUE (backend/app/services/task_assignment_service.py:1408-1427) and get_daily_progress returns only today's assignments (lines 1283-1330), so the overdue chore vanishes from the kid dashboard (dashboard.astro buckets only status 'pending'/'completed', lines 31-42) — yet has_open_mandatory_through (lines 582-599) counts every historical PENDING/OVERDUE row, so bonus_unlocked stays false forever. The kid sees 'Complete all required tasks to unlock bonus tasks' (i18n.ts:43) directly next to '3/3 completed' with no way to find or finish the blocking task, even though can_complete explicitly allows OVERDUE (models/task_assignment.py:162-168) — and auto_late_penalty consequences fire on these same invisible items with English-only notifications ('Auto-penalty applied: ...', task_assignment_service.py:1468-1476).

**Fix.** Include open OVERDUE assignments in the progress payload and render an 'Atrasadas' section of completable cards on the dashboard; when bonus is locked by a prior-day item, name the blocking task instead of the generic message; localize the auto-penalty notification and flag penalty-carrying tasks on the card before they expire.

Files: `backend/app/services/task_assignment_service.py`, `frontend/src/pages/dashboard.astro`, `frontend/src/lib/i18n.ts`

### [high/M] Unnamed root cause: 31 location.reload() sites across 14 pages — one shared mutation helper resolves ~8 filed findings at once

**Problem.** At least eight separate findings (chat reactions, approvals stale counters, envelope-funding modal, gig claim/submit blank reloads, 1.5s modal waits, kiosk refresh flicker, per-keystroke search reload) are symptoms of one missing pattern: there is no shared client-side mutate-and-update helper, so every write ends in a full SSR reload (grep: 31 location.reload() calls in 14 .astro pages) that re-runs 4-8 serial API calls. Each auditor proposed a page-local fix; none flagged that lib/toast.ts is already half the solution and that per-page patches will regress as new pages copy the reload idiom.

**Fix.** Build one small helper in frontend/src/lib (postJSON → optimistic DOM update → showToast → mapped error), adopt it on the five hottest paths (dashboard complete, approvals, chat, rewards redeem, FABModal), and grep-ban new location.reload() in review.

Files: `frontend/src/lib/toast.ts`, `frontend/src/pages/parent/approvals.astro`, `frontend/src/pages/chat.astro`, `frontend/src/components/FABModal.astro`

### [high/S] The points/cash economy has no visible ledger — kids can never see why their balance changed

**Problem.** For a gamified app whose core loop is earning, nobody noticed there is zero transaction history surface. PointsService.get_transaction_history exists (backend/app/services/points_service.py:168-182) but no route calls it (only MCP adapters read PointTransaction), and GET /api/cash/history exists (backend/app/api/routes/cash.py:44-51) but no frontend page fetches it. The mandatory 'reason' a parent types when adjusting points is stored and never shown to the kid; after a payout the dashboard cash badge just drops to $0.00 with no record. Points deductions, redemptions, and payouts are all unexplainable from any kid-facing screen.

**Fix.** Add GET /api/users/me/points/history wired to the existing service method and render a combined points+cash history list (reason, amount, date) on /profile, reusing the already-built /api/cash/history route.

Files: `backend/app/services/points_service.py`, `backend/app/api/routes/cash.py`, `backend/app/api/routes/users.py`, `frontend/src/pages/profile.astro`

### [medium/L] Shared-tablet identity is the theme three auditors half-saw: no low-friction kid re-auth or account switching exists

**Problem.** One-tap logout, fabricated kid emails with 8-char passwords, and the read-only kiosk were filed as three unrelated findings, but they share one missing capability: the family's shared tablet has no cheap way to say 'this tap is Emma'. login.astro offers only email+password and Google (no PIN, no profile picker; no PIN field on backend/app/models/user.py), so an accidental logout costs a child a full adult-grade re-login, and kiosk checkboxes must stay decorative because taps can't be attributed. Fixing the symptoms individually (confirm dialog, hiding logout) still leaves the main family device unable to switch kids.

**Fix.** Add a trusted-device quick-switch: kid avatar tiles + parent-set 4-digit PIN as an alternate login, then reuse it to let kiosk task checkboxes actually complete chores per-kid — defusing the logout, fake-email, and kiosk findings together.

Files: `frontend/src/pages/login.astro`, `frontend/src/pages/kiosk.astro`, `backend/app/models/user.py`

### [medium/M] Backend errors are English prose with no error codes — the filed 'translate the alerts' fixes are unimplementable as written

**Problem.** The i18n and feedback auditors flagged raw-English alert() text on 11 pages but missed the blocker: every exception class carries only a prose message and no machine-readable code (backend/app/core/exceptions.py has bare classes; handlers emit {detail: <string>}), so the frontend can only echo detail verbatim. Kid-blocking messages like 'Finish any open mandatory tasks (today + overdue) before claiming a gig' (task_assignment_service.py:648-651) and 'You have an active consequence that prevents reward redemption' (reward_service.py:126-132) reach Spanish-speaking kids untranslated, and no frontend mapping can fix them without a stable key.

**Fix.** Add a code field to FamilyAppException and the exception handlers (payload {detail, code: 'gig_mandatory_open'}), then a single frontend code→bilingual-string map; migrate the ~10 highest-traffic kid-facing messages first.

Files: `backend/app/core/exceptions.py`, `backend/app/core/exception_handlers.py`, `frontend/src/lib/i18n.ts`
