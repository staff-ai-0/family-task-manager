# Profile switcher (UX-E4) — design

**As built.** Status: built, see plan docs/superpowers/plans/2026-11-15-profile-switch.md. Route names, cookie paths, the home token type and the extra cookies below are amended to match the implementation, including the final-review fixes (2026-11-16).

Date: 2026-11-15. Program: UX audit `docs/audit/2026-09-27-ux-competitive/` (E4).

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

**Switch.** `POST /api/auth/profile/switch {user_id, pin}`, authenticated by the device's *home* session (below). The target must be an active, approved CHILD or TEEN in the caller's family; anything else is the same 403 as a wrong PIN (no oracle for which ids exist). On success it returns a normal access + refresh pair for the kid, both carrying a claim `sw: true` (switched). The `sw` claim survives `/api/auth/refresh`.

**Home session.** A parent who wants a shared device signs in normally, then taps "Share this device" (parent settings). The Astro route `/api/auth/profile/share` sends the parent's ACCESS token to backend `POST /api/auth/profile/share` (PARENT only, approved, never a `sw` token: 403 otherwise), which returns a **home token**: its own JWT type (`type: "home"`, claims `sub`, `ver`, `jti`, 30 days), NOT a refresh token. The frontend stores it in a separate httpOnly cookie `ftm_home` with `Path=/api/auth/profile`, so the browser sends it only to the profile routes `list`, `switch` and `return` (and `share` sets it), never with ordinary requests. httpOnly hides the cookie from page scripts, not from a person with DevTools, which is why the token has its own type: `/api/auth/refresh` and every access-token route reject it (401), and profile `list`/`switch`/`return` accept nothing else (a refresh or access token gets 401 there). Holding it lets someone see the picker and try PINs (throttled); it never yields a parent session without the parent's password. The parent's ordinary cookies are cleared by `share`, and later replaced by a kid's pair on a switch. The avatar picker (names, avatar colors as hex, "has PIN") is served by the home token through `GET /api/auth/profile/list`. `list` and `switch` rotate the home token.

**Shared-device hint.** `ftm_shared=1` is a readable (non-httpOnly) 30-day cookie on `Path=/`, set by `share`, `list` and `switch` (so it renews with use) and cleared wherever `ftm_home` is cleared (parent logout, normal login, Google, register, invitation accept). When a request has no usable session and `ftm_shared` is present, the middleware sends `/` (the PWA start URL) and protected pages to `/profiles` instead of `/login`, so a kid whose 2 h session expired never lands on the parent's saved password or Google account. Other public pages stay reachable and API routes keep their 401. It is a hint only: no authorization depends on it. A 401 from `switch` on the picker (home token expired or revoked) goes to `/login`.

**Return.** `POST /api/auth/profile/return {password}` uses `ftm_home` plus the parent's current password (re-verified, rate-limited by the existing `AUTH_LIMIT`). It restores the parent's ordinary cookies. A PIN is never accepted for return.

**Limits on a switched session.**
- Refresh-token lifetime 2 hours instead of 30 days (my call), so a left-behind device falls back to the picker.
- `sw` sessions cannot call profile/switch or profile/return (a kid cannot switch to a sibling from a kid session; they go back to the picker, which needs the home cookie).
- Teen and kid roles keep exactly their existing permissions; `sw` adds no privilege.

**PIN throttle.** Attempts are counted per (family member, home session user) and also per member alone, in Redis, with the existing `PIN_MAX_FAILURES` and lockout window. A member-wide counter stops a sibling rotating devices. **Reserve first:** after the target is validated (an invalid target writes nothing to Redis), one `MULTI/EXEC` does INCR + EXPIRE on both keys BEFORE bcrypt runs; if either count is over `PIN_MAX_FAILURES` the attempt gets 429 without a PIN check. So concurrent guesses cannot all pass the gate (at most 5 PIN checks per window), and a key can never be left without a TTL. A wrong PIN needs no further write. A correct PIN deletes the pair key and refunds its own member reservation (atomic, never below zero, never creates a key). Each attempt renews the window, including attempts made while locked.

**Parents.** PIN set/reset stays where it is today (kiosk member prefs, parent only). The picker shows "Ask a parent to set a PIN" for a member with none.

**Revocation.** `token_version` bump (logout-everywhere, password reset, soft-delete) already invalidates a kid's switched sessions. A parent's logout-everywhere also invalidates `ftm_home`, because the home token carries that parent's `ver` and every use checks it.

## As built amendments

- **Routes.** Nested names `/api/auth/profile/share`, `/api/auth/profile/list`, `/api/auth/profile/switch`, `/api/auth/profile/return`, each an Astro route with a backend counterpart of the same path. Backend `share` takes the parent's access token and returns `{home_token}`; `list` and `switch` return the rotated token as `home_token`.
- **Cookie path.** `ftm_home` is `Path=/api/auth/profile`. The names are nested because of the RFC 6265 path boundary: `/api/auth/profile` does not match `/api/auth/profile-switch` (a path matches only on a `/` boundary), so flat names would never receive the cookie.
- **`ftm_sw`.** A readable (non-httpOnly) marker cookie set on a switched session and renewed on refresh. UX hint only (show "back to picker"); no authorization depends on it.
- **`ftm_shared`.** See "Shared-device hint" above.
- **Share.** `share` also clears the parent's ordinary session cookies, so a shared device rests at the picker. The parent returns with their password.
- **Home-token endpoints** reject inactive or unapproved parents (and `share` refuses an unapproved parent, since `get_current_user` does not check approval).
- **Return prompt.** The password field uses `autocomplete="new-password"` (the parent's saved password is never offered to the kid) and is emptied whenever the sheet closes. The share copy tells the parent not to save their password in the browser and to sign out of Google on the device.
- **Back button.** Share, switch and return navigate with `location.replace`, and `Layout` reloads any page restored from the back-forward cache, so Back never shows the previous person's page.
- **Trailing slashes.** `shouldAttemptRefresh` and `isPublicRoute` normalise them, so `/api/auth/profile/switch/` is still in the no-refresh and public lists.

## Constraints

- Multi-tenant: every lookup filters by the caller's `family_id` from the home session JWT.
- PINs live in Redis today (`MemberPrefsService`, family prefs JSON, bcrypt). A Redis flush wipes them. For this project that fails closed (`verify_member_pin` returns None → "PIN not set"). Moving PINs to Postgres is out of scope; flag it to the user in the PR.
- New client fetches need an Astro route file (no catch-all auth proxy).
- Copy only in a new `frontend/src/lib/profileSwitch.ts`; no native alert/confirm/prompt; section-tone headers per the visual system; `/kiosk` untouched.
- No new family-scoped table, so nothing to add to the family-export registry.

## Verification expected

Tests prove: wrong PIN and unknown member give the same 403; non-kid target 403; cross-family 403; member-wide lockout 429; kid token cannot call switch/return; return needs the right password and a valid home cookie; `sw` survives refresh; refresh TTL 2 h; `token_version` bump kills a switched session. Final-review additions: a home token gets 401 at `/api/auth/refresh` and `/api/auth/me`; a parent refresh or access token gets 401 at `list`/`switch`/`return`; `share` gives a parent a working home token and refuses kid, `sw`, unapproved and anonymous callers; concurrent wrong PINs reach the PIN check at most 5 times; both throttle keys always carry a TTL; a success refunds its reservation. A browser check (shared phone flow, two kids) before merge.

## Calls made after the builder check (mine, not the user's)

- **Home token.** *(Superseded at final review: the first build stored a normal PARENT refresh token here, which anyone could copy from DevTools and trade at `/api/auth/refresh` for a 30-day parent session.)* `ftm_home` holds a `type: "home"` token minted by backend `profile/share`. `profile/switch`, `profile/list` and `profile/return` each validate it like `/api/auth/refresh` validates a refresh token (but `type` must be `home`; `ver == token_version`, user active and approved, family active) and require role PARENT (a TEEN or CHILD home token is 403). `list` and `switch` rotate it and rewrite `ftm_home`. Nothing in a kid session ever touches it. On return the backend mints a fresh parent access + refresh pair; nothing is "restored".
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
