# Teen Jarvis access + PIN profile login/switching

**Date:** 2026-07-15
**Status:** Design — awaiting review

## Problem

1. Jarvis (the AI copilot) is parent-only. We want **teens on a paid plan** to have their own assistant.
2. Minors don't manage email, yet every account currently **requires a unique email** and login is email+password only. The only no-email path is the **kiosk** — a read-only PIN snapshot that mints **no session**, so a kid can't actually *use* the app (or Jarvis) as themselves. There is no easy parent↔kid switch on a shared device.

Feature 2 is the prerequisite that makes feature 1 (and every kid-facing feature) reachable without email.

## Locked decisions

- **Teen Jarvis scope:** read-only self-coach. No MCP tools at all, self-scoped context only. (Chosen over scoped-tools / full-parent because it removes the family-wide authority risk structurally.)
- **Minor auth trust model:** *parent unlocks the device first.* The device binds to a family only after a real parent email/password login; PIN-login is then limited to that family. No public family-code endpoint → no cross-family PIN brute-force.

---

## Feature 1 — Teen Jarvis (read-only self-coach) — DONE in code, pending frontend

Backend changes already implemented in `jarvis_service.py` + routes:

- Chat endpoints (`/chat`, `/chat-stream`, `/history` GET+DELETE) use `require_teen_or_parent` (was `require_parent_role`) and keep `require_feature("ai_features")` (= paid/Plus). CHILD excluded. Schedules, MCP tokens, and destructive-action approval stay parent-only.
- Service branches on role via `_is_teen(role)`:
  - **Tool-free:** teens get `tool_defs=[]`; the completion call omits `tools`/`tool_choice`; the tool-dispatch branch is guarded `and not teen`. A teen literally cannot call a tool → no family-wide CRUD.
  - **Self-scoped context:** `_build_teen_context(db, family_id, user_id)` renders only the teen's own points, cash, today's tasks, and gig-claim counts — not other members, finances, or the family PUP roll-up.
  - **Coach persona:** `SYSTEM_TEEN` (advise/encourage, can't act).
  - **Private thread:** teen user+assistant rows persist with the teen's `user_id`; history/list/clear filter by it. Parent thread stays family-wide but excludes teen rows (`user_id IS NULL OR user_id IN parent_ids`) — a no-op for pre-teen data. Daily cap stays family-wide (shared LLM budget).

Remaining: route wiring passes `role=current_user.role` to the service; frontend nav/page exposed to teens when the family has `ai_features` (upsell otherwise).

### Tests
- teen stream: no tools passed, self-context, reply persists with teen `user_id`.
- teen history isolation: a teen never sees the parent thread and vice-versa.
- CHILD → 403; teen on Free plan → 402/403 via `require_feature`.

---

## Feature 2 — PIN profiles (email-optional minors + switcher)

### Data / accounts
- **Email optional for kids.** In the add-member flow, if no email is given, auto-generate a synthetic unique internal address (`kid-<short-uuid>@no-email.local`), skip the verification email, and set a 4-digit **PIN** (via the existing `MemberPrefsService`) instead of a password. Parents and real-email kids unchanged. (Chosen over a `nullable` email migration to avoid touching the unique constraint + all email-login lookups; revisit later if needed.)
- PIN storage already exists: Redis `family_settings:{family_id}:member_prefs` → `{color, pin_hash}` per user, with `verify_member_pin` + failure-lockout helpers.

### Device→family binding (the trust boundary)
- When a **parent** completes a normal email/password login, set a persistent `device_family` marker (httpOnly, long-lived cookie holding `family_id`, signed/opaque). This binds the shared device to that family via a legitimate parent auth.
- The profile picker and PIN-login only ever operate within `device_family`. No family-code entry anywhere.

### PIN login → real session
- `POST /api/auth/pin-login { user_id, pin }`, gated on `device_family` (must be set; `user_id` must belong to that family).
- Verify PIN via `MemberPrefsService.verify_member_pin` + existing lockout (`record_pin_failure` / `clear_pin_failures`).
- On success, mint the normal session: `create_access_token` + set the same auth cookies as `/login`. Role scoping (CHILD/TEEN) then governs everything, including teen-Jarvis.

### Switcher UX
- "Who's using this?" avatar grid (reuses color+PIN prefs), reachable from the nav/profile menu and as a full-screen picker.
- Tap avatar → PIN pad → session swap. `device_family` persists across swaps.
- Switch back to a parent requires the parent's PIN (parents may set one) or their password — never just tapping the parent avatar.

### Security
- PIN-login requires `device_family` (a parent authenticated on this device first). No public endpoint.
- Existing lockout on repeated PIN failures; rate-limit the endpoint.
- Kid sessions are ordinary role-scoped sessions — no elevated scope. Switching to a parent needs full parent credentials, so a kid can't escalate.
- `device_family` cookie is httpOnly + signed; clearing it (explicit "sign out this device") requires the parent.

### Tests
- add-member without email → synthetic email + PIN set, no verification mail.
- pin-login happy path → valid session cookie, correct role.
- pin-login for a user outside `device_family` → 403; wrong PIN → lockout after N.
- pin-login with no `device_family` → 401.
- switch-to-parent requires parent credential (kid PIN rejected for a parent avatar).

---

## Rollout
- Backend feature-flagged where sensible; ship teen-Jarvis first (independent), then PIN profiles.
- No destructive migration (synthetic-email strategy avoids schema change).
- Deploy on-prem `.91` via `deploy-onprem.sh` after tests green.

## Non-goals
- No Jarvis tools/schedules for teens; no other-member/finance visibility.
- No CHILD Jarvis.
- No public family-code login; no biometric/OAuth kid login.
- Not making `users.email` nullable in this pass.
