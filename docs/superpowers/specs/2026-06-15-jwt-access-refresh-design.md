# JWT Access + Refresh Tokens — Design

**Date:** 2026-06-15
**Status:** Approved (design); pending implementation
**Audit item:** Bucket 1, #4 (HIGH) — from `docs/audit/2026-06-04/05-verified-prioritized.md`

## Problem

Today the app issues a single JWT (`access_token`) with a **7-day** lifetime
(`ACCESS_TOKEN_EXPIRE_MINUTES = 10080`, `backend/app/core/config.py:33`) and **no
revocation** — `POST /api/auth/logout` (`backend/app/api/routes/auth.py:234`) is a
no-op that returns a message; the token stays valid for the full 7 days after
"logout". Separately, `SessionMiddleware` reuses `settings.SECRET_KEY`
(`backend/app/main.py:165`) for cookie signing — the same key that signs JWTs (crypto
hygiene: one key, two purposes).

A leaked 7-day token is usable for a week with no kill switch.

## Goal

- Short-lived **access** token (1h) + longer **refresh** token (7d, rotating).
- Real revocation on logout and password reset (logout-everywhere).
- Separate signing key for `SessionMiddleware`.
- No forced mass logout on deploy; no new infra dependency (no Redis-for-auth).

## Architecture context (why this is small)

The frontend is a **Backend-For-Frontend (BFF)**. The browser never holds the JWT:

- Astro server routes (`frontend/src/pages/api/auth/*.ts`) set an **httpOnly**
  `access_token` cookie. The 4 setters duplicate a `buildCookie()` helper
  (`login.ts`, `register.ts`, `oauth/google.ts`, `invitations/accept.ts`).
- All browser → backend API calls funnel through Astro proxy routes
  (`frontend/src/pages/api/*/[...path].ts`) which read the httpOnly cookie
  server-side and inject `Authorization: Bearer <token>`. SSR pages read
  `Astro.cookies.get("access_token")` and pass it to `lib/api.ts::apiFetch`.
- `middleware.ts` guards protected routes: for `/api/*` it validates the token by
  calling backend `/api/auth/me`; on 401/403 it deletes the cookie; on 5xx it
  returns 503 without deleting.
- Backend `get_current_user` (`backend/app/core/dependencies.py:14`) reads the token
  from the `Authorization` header via `oauth2_scheme`, decodes it, uses `sub` as the
  user id. The backend never reads a cookie for the JWT.

Because the refresh token is httpOnly and only ever travels between the Astro
server and the backend (never to browser JS), XSS cannot exfiltrate it. Refresh
logic centralizes at the BFF layer (middleware + proxy routes).

## Design

### Token model

| Token   | TTL | Claims |
|---------|-----|--------|
| access  | 60 min | `{sub, role, family_id, type:"access", exp}` |
| refresh | 7 days | `{sub, ver, type:"refresh", jti, exp}` |

- `jti` (uuid4) is for log correlation only — **not** stored.
- `ver` is the user's `token_version` at issue time.

### Revocation: `token_version` column

- New column `User.token_version: int` (NOT NULL, default 0). One Alembic migration.
- The refresh token embeds `ver = user.token_version`.
- `POST /api/auth/refresh` rejects the refresh token if `ver != user.token_version`.
- **Logout** and **password-reset** do `user.token_version += 1` → every existing
  refresh token for that user is instantly invalid (logout-everywhere). No Redis,
  no per-token store.

### Rotation

Each successful `/api/auth/refresh` issues a **new access token AND a new refresh
token** (sliding 7-day window), both stamped with the current `token_version`. The
prior refresh token remains valid until its own `exp` or until `token_version` is
bumped — there is no per-token invalidation (that was the declined Redis option).

### Backward compatibility (no mass logout on deploy)

Existing 7-day `access_token` cookies in the wild have no `type` claim.
`get_current_user` accepts `type in {"access", None}` — a missing `type` is treated
as a legacy access token. New logins immediately get the access+refresh pair; legacy
tokens expire within ≤7 days naturally. (A later change can enforce `type=="access"`
strictly once legacy tokens have aged out.)

### Session key split

Add `SESSION_SECRET_KEY` setting. `SessionMiddleware` uses it. It **defaults to
`SECRET_KEY`** when unset so dev/existing envs don't break; production `.env` sets a
distinct value. (`.env.gcp.example` updated to include it.)

## Components & changes

### Backend

- `core/config.py`: `ACCESS_TOKEN_EXPIRE_MINUTES` → `60`; add
  `REFRESH_TOKEN_EXPIRE_DAYS = 7`, `SESSION_SECRET_KEY: str = ""`.
- `core/security.py`:
  - `create_access_token(data)` adds `type:"access"`.
  - new `create_refresh_token(sub: str, version: int) -> str` (type:"refresh", ver,
    jti, 7d).
  - `decode_token(token, expected_type: str | None = None)` — when
    `expected_type` set, raise 401 on mismatch (treating missing type as "access").
- `core/dependencies.py::get_current_user`: decode with `expected_type="access"`
  (which permits legacy no-type tokens).
- `models/user.py`: `token_version` column + Alembic migration
  (`backend/migrations/versions/`).
- `services/auth_service.py`: `authenticate_user` returns `(user, access, refresh)`.
- `services/google_oauth_service.py`, `services/invitation_service.py`: return a
  refresh token alongside access.
- `api/routes/auth.py`:
  - `login` / oauth / invitation responses include `refresh_token`.
  - **new `POST /api/auth/refresh`** — input: refresh token (from `Authorization:
    Bearer` supplied by the BFF refresh route); validates sig + exp + `type=="refresh"`
    + `ver == user.token_version`; returns new `{access_token, refresh_token}`.
  - `logout` (now takes db): `user.token_version += 1`, commit.
  - `reset-password`: bump `token_version` on the affected user.
- `schemas`: `TokenResponse` (+ refresh response schema) gains `refresh_token`.
- `main.py`: `SessionMiddleware(secret_key=settings.SESSION_SECRET_KEY or settings.SECRET_KEY)`.

### Frontend (BFF)

- New `lib/auth-cookies.ts`: single helper that sets BOTH httpOnly cookies —
  `access_token` (Max-Age 3600) and `refresh_token` (Max-Age 604800, `Path=/api/auth`
  scope so it's only sent to auth routes). Replaces the 4 `buildCookie()` copies in
  `login.ts`, `register.ts`, `oauth/google.ts`, `invitations/accept.ts`.
- New `pages/api/auth/refresh.ts`: reads the `refresh_token` cookie, calls backend
  `POST /api/auth/refresh` (Bearer = refresh token), sets the new cookie pair, returns
  `{ok}`.
- `middleware.ts`: add a refresh step **before** the existing validation. Cheaply
  read the access token's `exp` (base64-decode payload, no signature check — backend
  still verifies) — if absent or expired/near-expiry, call the refresh route using the
  `refresh_token` cookie and set a fresh `access_token` before continuing. The
  existing `/api/auth/me` validation + `context.locals.user`/`plan` population for
  `/api/*` routes is unchanged. On refresh failure → delete both cookies → redirect
  `/login` (pages) or 401 (api).
- Proxy routes (`pages/api/*/[...path].ts`): shared helper — on a backend 401, call
  the refresh route once, then retry the original request with the new token; if
  refresh fails, surface 401.
- `pages/api/auth/logout.ts`: call backend `/api/auth/logout` (to bump
  `token_version`) and clear BOTH cookies.

## Data flow

1. **Login** → backend returns `{access_token(1h), refresh_token(7d)}` → BFF sets two
   httpOnly cookies.
2. **Normal request** → access token valid → proxy/SSR attaches it → backend serves.
3. **Access expired** → middleware (page) or proxy (api 401) calls
   `/api/auth/refresh` with the refresh cookie → backend checks `ver` → returns a new
   pair → BFF sets cookies → request proceeds. Transparent to the user.
4. **Logout / password reset** → `token_version++` → all refresh tokens fail the
   `ver` check → next refresh attempt 401 → user re-authenticates.

## Error handling

- Refresh with wrong `type`, bad signature, expired, or stale `ver` → 401 from
  `/api/auth/refresh`; BFF clears cookies and redirects to `/login`.
- Backend 5xx during refresh → BFF surfaces 503 without clearing cookies (mirrors the
  existing middleware policy so a deploy blip doesn't log everyone out).
- Refresh-loop guard: the BFF attempts refresh at most once per request.

## Testing

### Backend (pytest, TDD)

- `create_access_token` stamps `type:"access"`; `create_refresh_token` stamps
  `type:"refresh"` + `ver` + 7d exp.
- `get_current_user` accepts access + legacy(no-type); rejects a refresh token.
- `POST /api/auth/refresh`: happy path returns a new pair; rejects wrong-type token,
  expired token, and stale `ver` (after a `token_version` bump).
- `logout` increments `token_version` and invalidates outstanding refresh tokens
  (subsequent `/refresh` → 401).
- password-reset bumps `token_version`.

### E2E (Playwright)

- Expired access + valid refresh → protected page loads with no `/login` bounce, and
  a new `access_token` cookie is set.
- Logout → a saved refresh token can no longer mint an access token (`/refresh` 401).

## Out of scope / non-goals

- Per-token (single-session) revocation and refresh-reuse theft detection (the Redis
  `jti`-store option) — explicitly declined.
- Migrating the backend to read the JWT from a cookie — it continues to read the
  `Authorization` header (the BFF supplies it).
- Touching the `ui_role` cookie or the SSR theming flow.

## Files touched (summary)

Backend: `config.py`, `security.py`, `dependencies.py`, `models/user.py`, a new
migration, `services/auth_service.py`, `services/google_oauth_service.py`,
`services/invitation_service.py`, `api/routes/auth.py`, `schemas` (token), `main.py`,
`.env.gcp.example`.

Frontend: new `lib/auth-cookies.ts`, new `pages/api/auth/refresh.ts`, `middleware.ts`,
`pages/api/auth/login.ts`, `register.ts`, `oauth/google.ts`, `invitations/accept.ts`,
`logout.ts`, and the proxy routes `pages/api/*/[...path].ts`.
