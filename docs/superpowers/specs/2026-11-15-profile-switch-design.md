# Profile switcher (UX-E4) — design

Date: 2026-11-15. Status: approved approach, awaiting spec review. Program: UX audit `docs/audit/2026-09-27-ux-competitive/` (E4).

## Intent

A family often shares one phone or tablet. Today a kid there needs their own email and password, or uses the kiosk, which shows a read-only per-kid view. The user asked for "PIN kid profiles": a parent signs in once on a shared device, a kid taps their avatar, types their 4-digit PIN and is in the real app (deck, pet, rank, rewards) as themselves. The user did not describe a specific pain point in their own words; they chose this approach from three options, so the intent above is the inferred one and is flagged as such.

## Goals

- Kid or teen switches into their own account on a parent-signed-in device with avatar + PIN, no email/password.
- A kid session is a normal kid session: same API, same role limits, same screens.
- Returning to the parent requires the parent's own password. A kid session can never produce a parent session.
- Reuse the existing per-member PIN (set by a parent on the kiosk settings) rather than a second PIN.

## Non-goals / anti-goals

- No PIN-only public login (no family-code + PIN endpoint). That is approach 3, rejected: new brute-force surface on a public route.
- No kid or teen reaching parent screens, ever, through this feature. A bug that lets a kid mint a parent session is a failure even if every test passes.
- No change to kiosk behavior or to the kiosk PIN throttle.
- No new PIN storage in this project (see Constraints).

## Approaches considered

1. Extend the kiosk only — rejected: kids still need an email and password on their own phones, solves nothing new.
2. **Profile switcher in the main app — chosen by the user.** Reuses PIN, throttle idea and `token_version`.
3. PIN as the kid's only login — rejected (public brute-force surface, a new login path).

## Behavior

**Switch.** `POST /api/auth/profile-switch {user_id, pin}`, authenticated by the device's *home* session (below). The target must be an active, approved CHILD or TEEN in the caller's family; anything else is the same 403 as a wrong PIN (no oracle for which ids exist). On success it returns a normal access + refresh pair for the kid, both carrying a claim `sw: true` (switched). The `sw` claim survives `/api/auth/refresh`.

**Home session.** A parent who wants a shared device signs in normally, then taps "Share this device" (parent settings). The frontend stores the parent's refresh token in a separate httpOnly cookie `ftm_home` whose `Path` is restricted to the two Astro routes `/api/auth/profile-switch` and `/api/auth/profile-return`, so it is never sent with ordinary requests and a kid session cannot read or use it. The ordinary `ftm` cookies are then replaced by the kid's pair. The avatar picker (names, avatar colors, "has PIN") is served by the home cookie through a small `GET /api/auth/profile-list` on the same restricted path.

**Return.** `POST /api/auth/profile-return {password}` uses `ftm_home` plus the parent's current password (re-verified, rate-limited by the existing `AUTH_LIMIT`). It restores the parent's ordinary cookies. A PIN is never accepted for return.

**Limits on a switched session.**
- Refresh-token lifetime 2 hours instead of 30 days (my call), so a left-behind device falls back to the picker.
- `sw` sessions cannot call profile-switch or profile-return (a kid cannot switch to a sibling from a kid session; they go back to the picker, which needs the home cookie).
- Teen and kid roles keep exactly their existing permissions; `sw` adds no privilege.

**PIN throttle.** Failures are counted per (family member, home session user) and also per member alone, in Redis, with the existing `PIN_MAX_FAILURES` and lockout window (429 after the cap). A member-wide counter stops a sibling rotating devices. Success clears only the per-pair counter.

**Parents.** PIN set/reset stays where it is today (kiosk member prefs, parent only). The picker shows "Ask a parent to set a PIN" for a member with none.

**Revocation.** `token_version` bump (logout-everywhere, password reset, soft-delete) already invalidates a kid's switched sessions. A parent's logout-everywhere also invalidates `ftm_home`, because it is that parent's refresh token.

## Constraints

- Multi-tenant: every lookup filters by the caller's `family_id` from the home session JWT.
- PINs live in Redis today (`MemberPrefsService`, family prefs JSON, bcrypt). A Redis flush wipes them. For this project that fails closed (`verify_member_pin` returns None → "PIN not set"). Moving PINs to Postgres is out of scope; flag it to the user in the PR.
- New client fetches need an Astro route file (no catch-all auth proxy).
- Copy only in a new `frontend/src/lib/profileSwitch.ts`; no native alert/confirm/prompt; section-tone headers per the visual system; `/kiosk` untouched.
- No new family-scoped table, so nothing to add to the family-export registry.

## Verification expected

Tests prove: wrong PIN and unknown member give the same 403; non-kid target 403; cross-family 403; member-wide lockout 429; kid token cannot call switch/return; return needs the right password and a valid home cookie; `sw` survives refresh; refresh TTL 2 h; `token_version` bump kills a switched session. A browser check (shared phone flow, two kids) before merge.

## Calls made after the builder check (mine, not the user's)

- **Home token.** `ftm_home` holds a normal PARENT refresh token. `profile-switch`, `profile-list` and `profile-return` each validate it exactly like `/api/auth/refresh` (type `refresh`, `ver == token_version`, family active) and require role PARENT (a TEEN or CHILD home token is 403). Each use rotates it and rewrites `ftm_home`. Nothing in a kid session ever touches it. On return the backend mints a fresh parent access + refresh pair; nothing is "restored".
- **Switched-session lifetime.** Sliding, not absolute: each refresh of a `sw` token issues a new `sw` pair with a 2 h refresh TTL, so a kid is not logged out mid-use, and an abandoned device falls back to the picker after 2 h idle.
- **PIN check.** Wrap `MemberPrefsService.verify_member_pin` (no throttle of its own). Reuse the `PIN_MAX_FAILURES` and lockout constants; the new Redis keys use a separate prefix (`switch_pin_fails:`), never the kiosk's `kiosk_pin_fails:`.
- **Redis flush.** The picker's "has PIN" flag reads the same prefs entry, so after a flush every member shows "Ask a parent to set a PIN". Accepted (fail closed).
- **Passwordless kids.** A kid created without email/password is a valid switch target; the builder must confirm `/auth/me` and the Astro middleware work for them and say so in the plan.
- **Logout in a switched session.** Clears the ordinary cookies and returns to the picker; `ftm_home` is kept. A parent's own logout (ordinary parent session) also clears `ftm_home`.

## Left to the builder

Avatar rendering in the picker, the exact cookie names beyond `ftm_home`, route file layout, ES/EN wording, where "Share this device" sits in settings.

## Open for the user (decide after reading)

- Is 2 h the right idle cap for a kid session on a shared device?
- Should a teen be allowed to switch without a PIN prompt when they have no PIN? (Default here: no, a PIN is required.)
