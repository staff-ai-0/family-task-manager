# Profile Switcher (UX-E4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A parent signs in once on a shared device; a kid taps their avatar, enters their 4-digit PIN and gets a normal kid session; only the parent's password gets back to the parent.

**Architecture:** Backend adds three endpoints (`profile/list`, `profile/switch`, `profile/return`) authenticated by the parent's refresh token (the "home token"), plus an `sw` claim and 2 h sliding refresh TTL on switched sessions. Frontend stores the home token in an httpOnly cookie `ftm_home` whose Path is restricted to `/api/auth/profile`, so ordinary requests and kid sessions never carry it.

**Tech Stack:** FastAPI + PyJWT + Redis (PIN prefs/throttle, existing `MemberPrefsService`), Astro 5 server routes + vanilla `<script>` islands, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-11-15-profile-switch-design.md`

## Global Constraints

- Role gate: home token user must be `PARENT`; target must be active, approved, not soft-deleted, same family, role `CHILD` or `TEEN`. Every failure of target or PIN returns the SAME `403 {"detail": "Invalid profile or PIN"}`.
- A `sw` token (access or refresh) must never be accepted by profile endpoints, and never produces a parent session.
- Switched refresh TTL: `SWITCHED_REFRESH_TOKEN_EXPIRE_HOURS = 2`, sliding (every refresh of a `sw` token re-issues `sw` with 2 h).
- PIN throttle reuses `PIN_MAX_FAILURES` (5) and `PIN_FAILURE_WINDOW_SECONDS`; new Redis key prefix `switch_pin_fails:` (never `kiosk_pin_fails:`); lock at member scope and at (home user, member) scope; 429 `Too many attempts. Try again in a few minutes.`
- Cookie path boundary (RFC 6265): routes live under `/api/auth/profile/` so `Path=/api/auth/profile` matches them. `/api/auth/profile-switch` would NOT match.
- Family filter on every query (`family_id` from the home token's user). Copy only in `frontend/src/lib/profileSwitch.ts`. No native `alert/confirm/prompt`. Kiosk code untouched. New fetches from the browser need an Astro route file.

## Review Focus

- A kid's own refresh token sent to backend `profile/*` as Bearer → 403 (role CHILD/TEEN and `sw`). Test it.
- Rotating home sessions cannot dodge the lockout: member-wide counter blocks even a fresh home session. Test it.
- Unknown id, parent id, other-family id, inactive, unapproved, soft-deleted target → same 403 as wrong PIN, and unknown ids must not touch Redis counters (no oracle, no counter pollution).
- A member with no PIN set: same 403, not a distinct message to the API (the picker uses `has_pin` from `profile/list` to show "ask a parent").
- `sw` survives `/api/auth/refresh` and the cookie Max-Age follows (2 h), not 30 days.
- `token_version` bump (logout-everywhere) kills the switched session AND the parent's `ftm_home`.
- Passwordless kid (`password_hash` NULL; `email` is non-nullable) can be a switch target and `/api/auth/me` works for the switched session.
- Parent logout (non-switched) clears `ftm_home`; kid logout keeps it.

---

### Task 1: `sw` claim, 2 h TTL, refresh propagation

**Files:**
- Modify: `backend/app/core/config.py` (add `SWITCHED_REFRESH_TOKEN_EXPIRE_HOURS: int = 2`)
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/api/routes/auth.py` (`refresh_tokens`)
- Modify: `backend/app/schemas/user.py` (`TokenResponse`)
- Test: `backend/tests/test_profile_switch.py` (new; token tests here, endpoint tests in Task 2)

**Interfaces:**
- Produces: `create_access_token(data, expires_delta=None)` unchanged (callers put `"sw": True` in `data`); `create_refresh_token(sub: str, version: int, switched: bool = False) -> str` (adds claim `sw: True` and uses the 2 h TTL when switched); `TokenResponse.switched: bool = False`.

- [ ] **Step 1: Write failing tests** in `test_profile_switch.py::TestSwitchedTokens`:
  `test_switched_refresh_has_sw_claim_and_2h_exp` (decode with `decode_token`, assert `sw is True` and `exp - now <= 2h + 60s`, a normal one has no `sw` and ~30 d); `test_refresh_endpoint_propagates_sw` (POST `/api/auth/refresh` with a switched refresh token as Bearer → new access and refresh both decode with `sw True`, response `switched == True`, refresh exp ≤ 2 h); `test_refresh_endpoint_normal_unchanged` (`switched == False`, no `sw`).
- [ ] **Step 2: Run** `pytest tests/test_profile_switch.py -k Switched -v` → FAIL.
- [ ] **Step 3: Implement** the signature above; in `refresh_tokens` read `sw = bool(payload.get("sw"))`, put `"sw": True` in the new access data when set, pass `switched=sw` to `create_refresh_token`, return `TokenResponse(..., switched=sw)`.
- [ ] **Step 4: Run** the tests → PASS; also `pytest tests/test_auth.py tests/test_auth_hardening.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(auth): sw claim and 2h sliding refresh for switched sessions`.

### Task 2: Throttle, service and endpoints

**Files:**
- Modify: `backend/app/services/member_prefs_service.py` (switch-failure helpers)
- Create: `backend/app/services/profile_switch_service.py`
- Create: `backend/app/api/routes/profile_switch.py`
- Modify: `backend/app/main.py` (`app.include_router(profile_switch.router, prefix="/api/auth", tags=["Authentication"])`)
- Modify: `backend/app/schemas/user.py` (request/response models)
- Test: `backend/tests/test_profile_switch.py`

**Interfaces:**
- Consumes: Task 1 `create_refresh_token(..., switched=)`; `MemberPrefsService.get_family_prefs`, `verify_member_pin`, `PIN_MAX_FAILURES`, `PIN_FAILURE_WINDOW_SECONDS`; `decode_token`; `verify_password`; `AUTH_LIMIT` from `app.core.rate_limiter`.
- Produces (MemberPrefsService, all static async): `switch_failures(home_user_id, member_id) -> int` (returns the max of the pair counter and the member counter), `record_switch_failure(home_user_id, member_id) -> None` (increments both keys, both with the window TTL), `clear_switch_failures(home_user_id, member_id) -> None` (clears only the pair key).
- Produces (schemas): `ProfileSwitchRequest(user_id: UUID, pin: str)` (pin `^\d{4}$`), `ProfileReturnRequest(password: str)`, `ProfileEntry(id, name, role, color, has_pin)`, `ProfileListResponse(profiles: list[ProfileEntry], home_refresh_token: str)`, `ProfileSwitchResponse(TokenResponse)` + `home_refresh_token: str`, `ProfileReturnResponse(TokenResponse)`.
- Produces (routes, all `Authorization: Bearer <home refresh token>` via `oauth2_scheme`): `GET /api/auth/profile/list`, `POST /api/auth/profile/switch`, `POST /api/auth/profile/return`; the last two carry `@limiter.limit(AUTH_LIMIT)`.
- Produces (service): `ProfileSwitchService.resolve_home(db, token) -> User` (decode `expected_type="refresh"`; 401 on bad token, `ver != token_version`, deleted, inactive family; 403 if `sw` claim or role != PARENT); `list_profiles(db, home) -> list[ProfileEntry]` (active, approved, undeleted CHILD/TEEN of `home.family_id`; `has_pin` from `get_family_prefs`; color via `resolve_color_name`); `switch(db, home, user_id, pin) -> (User, access, refresh)`; `return_to_parent(db, home, password) -> (User, access, refresh)` (`verify_password` against `home.password_hash`; wrong/NULL → 403 `Invalid password`). Each endpoint rotates the home token: response carries a fresh `home_refresh_token = create_refresh_token(str(home.id), home.token_version)` (return does not need one).

- [ ] **Step 1: Write failing tests** (`TestProfileSwitch`, fixtures: parent logged in via `/api/auth/login`, kid and teen with a PIN set through `MemberPrefsService.update_member_prefs(..., pin="1234")`; home token = the login `refresh_token`):
  `test_list_returns_only_kids_and_teens_with_has_pin`; `test_switch_ok_returns_kid_pair_with_sw_and_rotated_home`; `test_wrong_pin_403_same_detail`; `test_unknown_parent_other_family_inactive_unapproved_deleted_targets_same_403` (parametrized; assert Redis counter untouched for unknown ids); `test_no_pin_set_same_403`; `test_member_lockout_429_even_with_fresh_home_session` (5 wrong PINs from home A, then home B for the same member → 429); `test_pair_counter_cleared_on_success`; `test_kid_refresh_token_as_bearer_403` (list, switch and return); `test_sw_token_rejected_as_home` (a switched refresh token → 403); `test_teen_or_child_home_token_403`; `test_return_needs_password` (wrong → 403, right → parent pair without `sw`); `test_return_rejected_for_sw_token`; `test_token_version_bump_invalidates_home_and_switched` (bump `users.token_version` for the parent → home 401; for the kid → switched refresh 401); `test_passwordless_kid_can_be_switched_to_and_me_works` (kid with `password_hash=None`; `GET /api/auth/me` with the switched access token → 200).
- [ ] **Step 2: Run** `pytest tests/test_profile_switch.py -v` → FAIL.
- [ ] **Step 3: Implement** the throttle helpers (Redis via the existing `_redis()`; keys `switch_pin_fails:pair:{home}:{member}` and `switch_pin_fails:member:{member}`), the service and the routes per Interfaces. In `switch`: validate target first (return the generic 403 without any Redis write when invalid), then check lock (429), then verify PIN (`None` or `False` → `record_switch_failure` + generic 403), then clear pair counter and mint `access = create_access_token({"sub", "role", "family_id", "sw": True})` and `refresh = create_refresh_token(str(kid.id), kid.token_version, switched=True)`.
- [ ] **Step 4: Run** the tests → PASS; `ruff check app` → clean.
- [ ] **Step 5: Commit** `feat(auth): profile list/switch/return for shared devices`.

### Task 3: Frontend cookies and Astro routes

**Files:**
- Modify: `frontend/src/lib/auth-cookies.ts` (add exports below; give `authCookies` an optional `switched = false` that sets refresh Max-Age to 2 h)
- Modify: `frontend/src/lib/server/refresh.ts` (pass `body.switched` into `authCookies`)
- Modify: `frontend/src/pages/api/auth/login.ts` (also clear `ftm_home` and `ftm_sw` on a normal login)
- Modify: `frontend/src/pages/api/auth/logout.ts`
- Create: `frontend/src/pages/api/auth/profile/share.ts`, `list.ts`, `switch.ts`, `return.ts`
- Test: `frontend/test/profile-cookies.test.ts`

**Interfaces:**
- Produces in `auth-cookies.ts`: `homeCookie(value: string, secure: boolean): string` (`ftm_home`, HttpOnly, `Path=/api/auth/profile`, SameSite=Lax, Max-Age 30 d); `clearHomeCookie(): string[]` (HTTP + Secure variants, same Path); `switchedMarker(secure): string` (`ftm_sw=1`, `Path=/`, NOT httpOnly, Max-Age 2 h, a UX hint only); `clearSwitchedMarker(): string[]`; `authCookies(accessToken, refreshToken, secure, switched = false)`.
- Routes (all POST except `list` GET; all read `ftm_home` from cookies): `share` reads `refresh_token` (the parent's ordinary cookie) and sets `ftm_home` (no backend call; the backend re-validates on every use); `list` proxies to `profile/list` and re-sets `ftm_home` from `home_refresh_token`; `switch` proxies `{user_id, pin}`, on 200 sets the kid's `authCookies(..., switched=true)`, `ftm_sw`, rotated `ftm_home`, returns `{success: true}`; `return` proxies `{password}`, on 200 sets ordinary parent `authCookies`, clears `ftm_sw`, keeps `ftm_home`. Backend status codes (403, 429) pass through as JSON `{success: false, error}`.
- `logout.ts`: if cookie `ftm_sw` is present clear only the ordinary cookies and redirect to `/profiles`; otherwise also `clearHomeCookie()` and `clearSwitchedMarker()` and redirect to `/login`.

- [ ] **Step 1: Write failing vitest** `profile-cookies.test.ts`: `homeCookie` contains `HttpOnly`, `Path=/api/auth/profile` and not `Path=/;`; a path-match helper test asserting `/api/auth/profile/switch` matches and `/api/auth/profile-switch` and `/api/auth/me` do not (write the small RFC 6265 matcher inside the test); `authCookies(a, r, true, true)` refresh Max-Age is 7200 and default stays 2592000; `switchedMarker` is not HttpOnly.
- [ ] **Step 2: Run** `cd frontend && npx vitest run test/profile-cookies.test.ts` → FAIL.
- [ ] **Step 3: Implement** the helpers and the five route edits/files above, following the shape of `login.ts` (`API_BASE_URL` env, manual `Set-Cookie` headers).
- [ ] **Step 4: Run** the vitest and `npm run check` → PASS.
- [ ] **Step 5: Commit** `feat(frontend): home cookie and profile switch routes`.

### Task 4: Copy, helpers and the picker UI

**Files:**
- Create: `frontend/src/lib/profileSwitch.ts`
- Create: `frontend/src/pages/profiles.astro` (public route: add `/profiles` to the middleware's public-route list; the page itself reads nothing from `access_token`)
- Modify: `frontend/src/pages/parent/settings/family.astro` (a "Share this device" section: button posts to `/api/auth/profile/share`, then navigates to `/profiles`; short text saying kids pick their profile with a PIN)
- Modify: the app's user menu or More sheet so a switched session (`ftm_sw` readable via `document.cookie`) shows "Back to parent" (opens a password sheet via `promptSheet`-style dialog from `lib/dialogs.ts`; posts to `/api/auth/profile/return`)
- Test: `frontend/test/profile-switch.test.ts`

**Interfaces:**
- Produces in `profileSwitch.ts` (bilingual ES/EN via the same `lang` helper pattern as `lib/mystery.ts`): `profileCopy(lang): {title, pickPrompt, pinTitle, wrongPin, locked, noPin, backToParent, passwordPrompt, wrongPassword, shareTitle, shareBody, shareCta}`; `isSwitchedSession(cookieHeader: string): boolean` (reads `ftm_sw`); `errorKey(status: number): "wrongPin" | "locked" | "error"` (403 → wrongPin, 429 → locked, else error); `pinPadAppend(current: string, digit: string): string` (max 4 digits, digits only).
- Picker: grid of avatars (name + color from `profile/list`); a member without PIN is disabled with `noPin`; tap → 4-digit pad (large tap targets, `data-` hooks, section tone sky) → `POST /api/auth/profile/switch` → `location.href = "/dashboard"`. A 401 from `list` (no home cookie) redirects to `/login`.

- [ ] **Step 1: Write failing vitest** for `errorKey`, `pinPadAppend` (5th digit ignored, non-digits ignored), `isSwitchedSession` (present, absent, similar-name cookie), and that both languages define every `profileCopy` key.
- [ ] **Step 2: Run** `npx vitest run test/profile-switch.test.ts` → FAIL.
- [ ] **Step 3: Implement** the lib, then the page and the two entry points. Run the visual guard (`npx vitest run test/visual-consistency.test.ts test/no-native-dialogs.test.ts test/contrast.test.ts`).
- [ ] **Step 4: Run** the full frontend suite `npx vitest run` and `npm run check && npm run build` → PASS.
- [ ] **Step 5: Commit** `feat(frontend): profile picker, share-device setting and back-to-parent`.

### Task 5: Browser check, docs and PR

**Files:**
- Modify: `CLAUDE.md` (add a "Profile switcher" row to the domain table; note the nested-path cookie rule and Redis-held PINs fail closed)
- Modify: `docs/superpowers/specs/2026-11-15-profile-switch-design.md` (route names `profile/list|switch|return`, cookie `Path=/api/auth/profile`, marker cookie `ftm_sw`)

- [ ] **Step 1: Browser verification** on a local stack (never prod): parent logs in, taps Share this device, picker shows both kids, wrong PIN shows the message, 5 wrong PINs lock, right PIN lands on the kid's dashboard, kid cannot open `/parent`, kid logout returns to the picker, Back to parent with the wrong then right password. Record what was seen.
- [ ] **Step 2: Full backend suite** in the background with a log file (never foreground; >Bash cap): `pytest tests/ -q` → green, coverage gate ≥ 70%.
- [ ] **Step 3: Update docs**, commit `docs: profile switcher as built`, push, open the PR with `--body-file`, watch CI, then wait for the user's go to merge.
