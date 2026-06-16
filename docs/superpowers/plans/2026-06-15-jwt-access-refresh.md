# JWT Access + Refresh Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single 7-day JWT with a short-lived access token (1h) + rotating refresh token (7d), revocable via a per-user `token_version`, with transparent refresh at the Astro BFF layer.

**Architecture:** Backend mints access+refresh JWTs; `token_version` on `User` enables logout-everywhere. The Astro frontend is a BFF — it owns two httpOnly cookies and transparently refreshes the access token (in `middleware.ts`, which runs before every route) using the refresh cookie. The backend keeps reading the JWT from the `Authorization` header.

**Tech Stack:** FastAPI, python-jose, SQLAlchemy/Alembic, asyncpg, Astro 5 SSR (@astrojs/node), Playwright.

**Spec:** `docs/superpowers/specs/2026-06-15-jwt-access-refresh-design.md`

**Spec correction (found in planning):** The refresh cookie is `Path=/` (not `Path=/api/auth`). Cookies are only sent to paths matching their `Path`; the middleware and proxy routes that perform transparent refresh run on non-auth paths (`/api/budget/*`, page routes), so a `/api/auth`-scoped refresh cookie would never reach them. It remains httpOnly and BFF-only, so the security delta is nil.

**Test commands:**
- Backend: `podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -q --no-cov`
- E2E: `cd e2e-tests && npm run test -- <file>`

---

## File Structure

**Backend (create):**
- `backend/migrations/versions/<rev>_add_user_token_version.py` — migration for `User.token_version`.

**Backend (modify):**
- `backend/app/core/config.py` — token TTLs + `SESSION_SECRET_KEY`.
- `backend/app/core/security.py` — token type stamping, `create_refresh_token`, typed decode.
- `backend/app/core/dependencies.py` — `get_current_user` rejects non-access tokens.
- `backend/app/models/user.py` — `token_version` column.
- `backend/app/services/auth_service.py` — return access+refresh.
- `backend/app/services/google_oauth_service.py`, `invitation_service.py` — return refresh.
- `backend/app/api/routes/auth.py` — `/refresh` endpoint, logout + reset bump version, login returns refresh.
- `backend/app/schemas/user.py` — `TokenResponse.refresh_token`.
- `backend/app/main.py` — `SessionMiddleware` uses `SESSION_SECRET_KEY`.
- `backend/.env.gcp.example` — document `SESSION_SECRET_KEY`.

**Frontend (create):**
- `frontend/src/lib/auth-cookies.ts` — single cookie-pair builder.
- `frontend/src/lib/server/refresh.ts` — server-side refresh helper (calls backend).
- `frontend/src/pages/api/auth/refresh.ts` — refresh route.

**Frontend (modify):**
- `frontend/src/middleware.ts` — refresh-on-expiry before validation.
- `frontend/src/pages/api/auth/login.ts`, `register.ts`, `oauth/google.ts`, `invitations/accept.ts` — set both cookies via the shared helper.
- `frontend/src/pages/api/auth/logout.ts` — call backend logout + clear both cookies.
- `frontend/src/pages/api/*/[...path].ts` (proxy routes) — refresh-once-on-401 retry.

**E2E (create):**
- `e2e-tests/tests/auth-refresh.spec.ts`.

---

## Phase A — Backend

### Task A1: Token TTLs + SESSION_SECRET_KEY config

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Edit config**

In `backend/app/core/config.py`, change the access TTL and add the new settings (place near the existing `ACCESS_TOKEN_EXPIRE_MINUTES` / `SECRET_KEY` lines):

```python
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour (was 10080 / 7 days)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Separate signing key for Starlette SessionMiddleware cookies so it does
    # not share the JWT signing key. Defaults to SECRET_KEY when unset so dev
    # and existing envs keep working; production .env sets a distinct value.
    SESSION_SECRET_KEY: str = ""
```

- [ ] **Step 2: Verify import still loads**

Run: `podman exec -e PYTHONPATH=/app family_app_backend python -c "from app.core.config import settings; print(settings.ACCESS_TOKEN_EXPIRE_MINUTES, settings.REFRESH_TOKEN_EXPIRE_DAYS)"`
Expected: `60 7`

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat(auth): 1h access TTL, refresh TTL, SESSION_SECRET_KEY setting"
```

---

### Task A2: `token_version` column + migration

**Files:**
- Modify: `backend/app/models/user.py`
- Create: `backend/migrations/versions/<rev>_add_user_token_version.py`
- Test: `backend/tests/test_token_version.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_token_version.py`:

```python
"""User.token_version backs refresh-token revocation."""
import pytest


@pytest.mark.asyncio
async def test_user_token_version_defaults_to_zero(db_session, test_parent_user):
    await db_session.refresh(test_parent_user)
    assert test_parent_user.token_version == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_version.py -q --no-cov`
Expected: FAIL — `AttributeError: ... 'User' ... has no attribute 'token_version'`

- [ ] **Step 3: Add the column**

In `backend/app/models/user.py`, add to the `User` model (near the other `Integer` columns like `points`):

```python
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
```

(Ensure `Integer` is imported — it already is in this model.)

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_version.py -q --no-cov`
Expected: PASS (test DB is built from `create_all`, so the column exists immediately).

- [ ] **Step 5: Generate the migration**

Run: `podman exec -e PYTHONPATH=/app family_app_backend alembic revision -m "add user token_version"`
Then edit the new file in `backend/migrations/versions/` so `upgrade()`/`downgrade()` are exactly:

```python
def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
```

Confirm `down_revision` points at the current head (run `alembic heads` first; set it to that revision id).

- [ ] **Step 6: Apply migration to the dev DB**

Run: `podman exec -e PYTHONPATH=/app family_app_backend alembic upgrade head`
Expected: applies cleanly; `alembic current` shows the new revision as head.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/user.py backend/migrations/versions/ backend/tests/test_token_version.py
git commit -m "feat(auth): add User.token_version for refresh revocation"
```

---

### Task A3: Token creation + typed decode in security.py

**Files:**
- Modify: `backend/app/core/security.py`
- Test: `backend/tests/test_token_types.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_token_types.py`:

```python
"""Access vs refresh token claims + typed decoding."""
import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from fastapi import HTTPException


def _decode_raw(token):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_access_token_is_typed_access():
    tok = create_access_token({"sub": "u1"})
    assert _decode_raw(tok)["type"] == "access"


def test_refresh_token_carries_type_and_version():
    tok = create_refresh_token("u1", version=3)
    claims = _decode_raw(tok)
    assert claims["type"] == "refresh"
    assert claims["ver"] == 3
    assert claims["sub"] == "u1"
    assert "jti" in claims


def test_decode_token_rejects_wrong_type():
    refresh = create_refresh_token("u1", version=0)
    with pytest.raises(HTTPException) as exc:
        decode_token(refresh, expected_type="access")
    assert exc.value.status_code == 401


def test_decode_token_treats_missing_type_as_access():
    # A legacy token minted without a `type` claim must still decode as access.
    legacy = jwt.encode({"sub": "u1"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    payload = decode_token(legacy, expected_type="access")
    assert payload["sub"] == "u1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_types.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'create_refresh_token'` (and `decode_token` has no `expected_type`).

- [ ] **Step 3: Implement**

In `backend/app/core/security.py`:

Add `import uuid` and `timedelta` is already imported. Update `create_access_token` to stamp the type, add `create_refresh_token`, and extend `decode_token`:

```python
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a short-lived access JWT."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(sub: str, version: int) -> str:
    """Create a long-lived refresh JWT carrying the user's token_version."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": sub,
        "ver": version,
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    """Decode a JWT. When expected_type is set, enforce the `type` claim,
    treating a missing type as 'access' (legacy 7-day tokens)."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if expected_type is not None:
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_types.py -q --no-cov`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/security.py backend/tests/test_token_types.py
git commit -m "feat(auth): type-stamp access tokens, add create_refresh_token + typed decode"
```

---

### Task A4: `get_current_user` rejects refresh tokens

**Files:**
- Modify: `backend/app/core/dependencies.py`
- Test: `backend/tests/test_token_types.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_token_types.py`:

```python
@pytest.mark.asyncio
async def test_get_current_user_rejects_refresh_token(db_session, test_parent_user):
    from app.core.dependencies import get_current_user
    refresh = create_refresh_token(str(test_parent_user.id), version=0)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=refresh, db=db_session)
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_types.py::test_get_current_user_rejects_refresh_token -q --no-cov`
Expected: FAIL — a refresh token currently decodes fine and returns the user.

- [ ] **Step 3: Implement**

In `backend/app/core/dependencies.py::get_current_user`, change the decode call:

```python
    payload = decode_token(token, expected_type="access")
```

- [ ] **Step 4: Run to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_token_types.py -q --no-cov`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/dependencies.py backend/tests/test_token_types.py
git commit -m "feat(auth): get_current_user only accepts access (or legacy) tokens"
```

---

### Task A5: `authenticate_user` returns access + refresh

**Files:**
- Modify: `backend/app/services/auth_service.py`
- Test: `backend/tests/test_auth_service.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_auth_service.py`:

```python
@pytest.mark.asyncio
async def test_authenticate_user_returns_access_and_refresh(db_session, test_parent_user):
    from app.services.auth_service import AuthService
    from app.schemas.user import UserLogin
    from app.core.security import decode_token

    user, access, refresh = await AuthService.authenticate_user(
        db_session, UserLogin(email="parent@test.com", password="password123")
    )
    assert user.id == test_parent_user.id
    assert decode_token(access).get("type") == "access"
    refresh_claims = decode_token(refresh)
    assert refresh_claims.get("type") == "refresh"
    assert refresh_claims.get("ver") == test_parent_user.token_version
```

- [ ] **Step 2: Run to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth_service.py::test_authenticate_user_returns_access_and_refresh -q --no-cov`
Expected: FAIL — `authenticate_user` returns a 2-tuple `(user, access)`.

- [ ] **Step 3: Implement**

In `backend/app/services/auth_service.py`, update the import and `authenticate_user`:

Change the import line:
```python
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token
```

Update the signature + return (the body already builds `access_token` via `create_access_token({"sub": ...})`; add the refresh and return all three):
```python
    async def authenticate_user(
        db: AsyncSession,
        login_data: UserLogin,
    ) -> tuple[User, str, str]:
        """Authenticate user and return (user, access_token, refresh_token)."""
        # ... existing lookup + password verification unchanged ...
        access_token = create_access_token(
            {"sub": str(user.id), "role": user.role.value, "family_id": str(user.family_id)}
        )
        refresh_token = create_refresh_token(str(user.id), version=user.token_version)
        return user, access_token, refresh_token
```

(Keep the existing claim shape used today; only add `create_refresh_token` and widen the return tuple. Match the existing `create_access_token({...})` payload already in the function.)

- [ ] **Step 4: Update the login route caller**

In `backend/app/api/routes/auth.py::login`, unpack three values:
```python
    user, access_token, refresh_token = await AuthService.authenticate_user(db, login_data)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )
```

- [ ] **Step 5: Run to verify it passes (test added in Step 1; TokenResponse field added in Task A8 — if running before A8, expect a schema error, do A8 first then re-run)**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth_service.py::test_authenticate_user_returns_access_and_refresh -q --no-cov`
Expected: PASS.

> NOTE: Do Task A8 (schema) before re-running the login route, since `TokenResponse(refresh_token=...)` needs the new field. The service-level test in Step 1 does not touch `TokenResponse` and passes independently.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/auth_service.py backend/app/api/routes/auth.py backend/tests/test_auth_service.py
git commit -m "feat(auth): authenticate_user issues access + refresh tokens"
```

---

### Task A8: `TokenResponse.refresh_token` schema

> (Ordered before A6/A7 because they construct token responses.)

**Files:**
- Modify: `backend/app/schemas/user.py`

- [ ] **Step 1: Add the field**

In `backend/app/schemas/user.py`, add to `TokenResponse`:
```python
    refresh_token: Optional[str] = None
```
(`Optional` is already imported in this module; if not, add `from typing import Optional`.)

- [ ] **Step 2: Verify import loads**

Run: `podman exec -e PYTHONPATH=/app family_app_backend python -c "from app.schemas.user import TokenResponse; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/user.py
git commit -m "feat(auth): add refresh_token to TokenResponse"
```

---

### Task A6: `POST /api/auth/refresh` endpoint

**Files:**
- Modify: `backend/app/api/routes/auth.py`
- Test: `backend/tests/test_refresh_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_refresh_endpoint.py`:

```python
"""POST /api/auth/refresh — exchange a valid refresh token for a new pair."""
import pytest
from httpx import AsyncClient

from app.core.security import create_refresh_token, decode_token


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_refresh_happy_path(client: AsyncClient, test_parent_user):
    refresh = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    resp = await client.post("/api/auth/refresh", headers=_bearer(refresh))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert decode_token(body["access_token"]).get("type") == "access"
    assert decode_token(body["refresh_token"]).get("type") == "refresh"


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client: AsyncClient, test_parent_user):
    from app.core.security import create_access_token
    access = create_access_token({"sub": str(test_parent_user.id)})
    resp = await client.post("/api/auth/refresh", headers=_bearer(access))
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_rejects_stale_version(client: AsyncClient, db_session, test_parent_user):
    stale = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    test_parent_user.token_version += 1
    await db_session.commit()
    resp = await client.post("/api/auth/refresh", headers=_bearer(stale))
    assert resp.status_code == 401, resp.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_refresh_endpoint.py -q --no-cov`
Expected: FAIL — 404/405 (route does not exist).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes/auth.py`, add (use the existing `oauth2_scheme` dependency to read the Bearer token, and `select`/`User` already imported in this module):

```python
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.security import oauth2_scheme


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a fresh access + refresh pair."""
    payload = decode_token(token, expected_type="refresh")
    user_id = payload.get("sub")
    ver = payload.get("ver")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is no longer valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        {"sub": str(user.id), "role": user.role.value, "family_id": str(user.family_id)}
    )
    refresh_token = create_refresh_token(str(user.id), version=user.token_version)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )
```

Add `/api/auth/refresh` to the middleware `publicRoutes` list in Task B4 (so the BFF can call it even when the access token is dead). The backend route itself stays unauthenticated-by-access (it authenticates via the refresh token).

- [ ] **Step 4: Run to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_refresh_endpoint.py -q --no-cov`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/auth.py backend/tests/test_refresh_endpoint.py
git commit -m "feat(auth): POST /api/auth/refresh (typed + token_version checked)"
```

---

### Task A7: logout + reset-password bump `token_version`

**Files:**
- Modify: `backend/app/api/routes/auth.py`
- Test: `backend/tests/test_refresh_endpoint.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_refresh_endpoint.py`:

```python
@pytest.mark.asyncio
async def test_logout_invalidates_refresh(client: AsyncClient, db_session, test_parent_user):
    refresh = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    # Authenticate logout with a valid access token.
    from app.core.security import create_access_token
    access = create_access_token({"sub": str(test_parent_user.id)})
    out = await client.post("/api/auth/logout", headers=_bearer(access))
    assert out.status_code == 200, out.text
    # The pre-logout refresh token must now be rejected.
    resp = await client.post("/api/auth/refresh", headers=_bearer(refresh))
    assert resp.status_code == 401, resp.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_refresh_endpoint.py::test_logout_invalidates_refresh -q --no-cov`
Expected: FAIL — logout is a no-op; the old refresh still works.

- [ ] **Step 3: Implement**

Replace the existing `logout` in `backend/app/api/routes/auth.py`:

```python
@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log out everywhere: bump token_version so all refresh tokens die."""
    current_user.token_version += 1
    await db.commit()
    return {"message": "Logged out successfully."}
```

In `reset_password`, after a successful reset, bump the version on the affected user (the `EmailService.reset_password` returns the user):
```python
    user = await EmailService.reset_password(db, token, new_hash)
    if not user:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset password.")
    user.token_version += 1
    await db.commit()
    return {"message": "Password reset successfully. You can now log in."}
```

- [ ] **Step 4: Run to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_refresh_endpoint.py -q --no-cov`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/auth.py backend/tests/test_refresh_endpoint.py
git commit -m "feat(auth): logout + password-reset bump token_version (logout-everywhere)"
```

---

### Task A9: OAuth + invitation return refresh; SessionMiddleware key; env example

**Files:**
- Modify: `backend/app/services/google_oauth_service.py`, `backend/app/services/invitation_service.py`, `backend/app/main.py`, `backend/.env.gcp.example`
- Test: `backend/tests/test_google_oauth_audiences.py` (verify existing still passes)

- [ ] **Step 1: Return refresh from OAuth + invitations**

In `google_oauth_service.py` and `invitation_service.py`, wherever `create_access_token(...)` is called and a token is returned to the route, also create a refresh token and include it. Import `create_refresh_token`. Each call site that currently returns `(user, access_token)` (or sets `access_token` on a response) becomes `(user, access_token, create_refresh_token(str(user.id), version=user.token_version))`, and the corresponding route in `auth.py`/`oauth.py`/`invitations.py` puts it in `TokenResponse.refresh_token`.

(Exact line numbers: `google_oauth_service.py:135` and `:202`; `invitation_service.py` — its `create_access_token` call. Update each return + its caller.)

- [ ] **Step 2: SessionMiddleware uses SESSION_SECRET_KEY**

In `backend/app/main.py` (the `SessionMiddleware` registration):
```python
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY or settings.SECRET_KEY,
    ...
)
```

- [ ] **Step 3: Document the env var**

In `backend/.env.gcp.example`, add:
```
# Distinct signing key for session cookies (do NOT reuse SECRET_KEY).
SESSION_SECRET_KEY=
```

- [ ] **Step 4: Run OAuth + auth suites**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_google_oauth_audiences.py tests/test_auth.py tests/test_email_auth.py -q --no-cov`
Expected: PASS (no regressions; update any test that asserts the old 2-tuple).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/google_oauth_service.py backend/app/services/invitation_service.py backend/app/main.py backend/.env.gcp.example backend/tests/
git commit -m "feat(auth): OAuth/invitation issue refresh; split SessionMiddleware key"
```

---

### Task A10: Backend full-suite regression

- [ ] **Step 1: Run the whole suite**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q --no-cov -p no:cacheprovider`
Expected: all green except the known 10 xfail / 1 xpass baseline. Fix any test that hard-codes the old 7-day TTL or the 2-tuple `authenticate_user` return.

- [ ] **Step 2: Commit any test fixups**

```bash
git add backend/tests/
git commit -m "test(auth): update fixtures for access+refresh return shape"
```

---

## Phase B — Frontend (BFF)

### Task B1: Shared cookie-pair helper

**Files:**
- Create: `frontend/src/lib/auth-cookies.ts`

- [ ] **Step 1: Create the helper**

`frontend/src/lib/auth-cookies.ts`:

```ts
const ACCESS_MAX_AGE = 60 * 60;            // 1 hour
const REFRESH_MAX_AGE = 60 * 60 * 24 * 7;  // 7 days

function buildCookie(
    name: string,
    value: string,
    opts: { maxAge: number; httpOnly?: boolean; secure: boolean }
): string {
    let c = `${name}=${encodeURIComponent(value)}`;
    c += "; Path=/";
    if (opts.httpOnly) c += "; HttpOnly";
    if (opts.secure) c += "; Secure";
    c += "; SameSite=Lax";
    c += `; Max-Age=${opts.maxAge}`;
    return c;
}

/** Set-Cookie header values for the access+refresh pair. Both httpOnly,
 *  Path=/ so the middleware/proxies (which run on every route) can read the
 *  refresh cookie to mint a fresh access token. */
export function authCookies(accessToken: string, refreshToken: string, secure: boolean): string[] {
    return [
        buildCookie("access_token", accessToken, { maxAge: ACCESS_MAX_AGE, httpOnly: true, secure }),
        buildCookie("refresh_token", refreshToken, { maxAge: REFRESH_MAX_AGE, httpOnly: true, secure }),
    ];
}

/** Set-Cookie header values that clear both auth cookies (HTTP + HTTPS). */
export function clearAuthCookies(): string[] {
    return [
        "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure",
        "refresh_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        "refresh_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure",
    ];
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
Expected: no new errors from this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/auth-cookies.ts
git commit -m "feat(auth): shared access+refresh cookie helper"
```

---

### Task B2: Set both cookies on login/register/oauth/invitation

**Files:**
- Modify: `frontend/src/pages/api/auth/login.ts`, `register.ts`, `oauth/google.ts`, `invitations/accept.ts`

- [ ] **Step 1: login.ts**

In `frontend/src/pages/api/auth/login.ts`, import the helper and replace the single `tokenCookie` build with the pair. After `const result: LoginResponse = await response.json();`:

```ts
import { authCookies } from "../../../lib/auth-cookies";
// ...
const cookies = authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV);
```

Then everywhere a `Set-Cookie` was appended with `tokenCookie`, append each entry of `cookies` instead:
```ts
for (const c of cookies) headers.append("Set-Cookie", c);
if (uiRoleCookie) headers.append("Set-Cookie", uiRoleCookie);
```
(Keep the `ui_role` logic. `LoginResponse` type gains `refresh_token` — see Step 5.)

- [ ] **Step 2: register.ts** — same change (replace its `buildCookie("access_token", ...)` with `authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV)`; append both).

- [ ] **Step 3: oauth/google.ts** — same change.

- [ ] **Step 4: invitations/accept.ts** — same change.

- [ ] **Step 5: Add refresh_token to the LoginResponse type**

In `frontend/src/types/api.ts`, add `refresh_token: string;` (or `?: string`) to `LoginResponse`.

- [ ] **Step 6: Type-check + manual login smoke**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
Expected: no new errors. (Functional login verified in Phase C / verify skill.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/api/auth/login.ts frontend/src/pages/api/auth/register.ts frontend/src/pages/api/oauth/google.ts frontend/src/pages/api/invitations/accept.ts frontend/src/types/api.ts
git commit -m "feat(auth): set access+refresh cookies on all auth entry points"
```

---

### Task B3: Server-side refresh helper + `/api/auth/refresh` route

**Files:**
- Create: `frontend/src/lib/server/refresh.ts`, `frontend/src/pages/api/auth/refresh.ts`

- [ ] **Step 1: Refresh helper**

`frontend/src/lib/server/refresh.ts`:

```ts
import { authCookies } from "../auth-cookies";

const API = () => process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

export interface RefreshResult {
    ok: boolean;
    accessToken?: string;
    setCookies?: string[];
}

/** Exchange a refresh token for a new pair by calling the backend.
 *  Returns the new access token + Set-Cookie header values on success. */
export async function refreshAccessToken(refreshToken: string): Promise<RefreshResult> {
    if (!refreshToken) return { ok: false };
    const resp = await fetch(`${API()}/api/auth/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${refreshToken}` },
    });
    if (!resp.ok) return { ok: false };
    const body = await resp.json();
    return {
        ok: true,
        accessToken: body.access_token,
        setCookies: authCookies(body.access_token, body.refresh_token, !import.meta.env.DEV),
    };
}

/** Read a cookie value from a raw Cookie header. */
export function readCookie(cookieHeader: string, name: string): string | undefined {
    const m = cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
    return m ? decodeURIComponent(m[1]) : undefined;
}
```

- [ ] **Step 2: Refresh route**

`frontend/src/pages/api/auth/refresh.ts`:

```ts
import type { APIRoute } from "astro";
import { refreshAccessToken } from "../../../lib/server/refresh";

export const POST: APIRoute = async ({ cookies }) => {
    const refreshToken = cookies.get("refresh_token")?.value ?? "";
    const result = await refreshAccessToken(refreshToken);
    if (!result.ok) {
        return new Response(JSON.stringify({ ok: false }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    const headers = new Headers({ "Content-Type": "application/json" });
    for (const c of result.setCookies!) headers.append("Set-Cookie", c);
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers });
};
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/server/refresh.ts frontend/src/pages/api/auth/refresh.ts
git commit -m "feat(auth): BFF refresh helper + /api/auth/refresh route"
```

---

### Task B4: Middleware refresh-on-expiry

**Files:**
- Modify: `frontend/src/middleware.ts`

- [ ] **Step 1: Add a local exp check + refresh before the auth guard**

In `frontend/src/middleware.ts`:

(a) Add `/api/auth/refresh` to `publicRoutes`.

(b) Add a helper near the top of the module:
```ts
function isExpired(jwt: string | undefined): boolean {
    if (!jwt) return true;
    const parts = jwt.split(".");
    if (parts.length !== 3) return true;
    try {
        const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
        if (!payload.exp) return true;
        // Refresh 30s early to avoid edge races.
        return Date.now() / 1000 >= payload.exp - 30;
    } catch {
        return true;
    }
}
```

(c) Right after the existing `const token = cookies.get("access_token")?.value;` (the protected-route block) and BEFORE the "if (!token) redirect" logic, attempt a refresh when the access token is missing/expired but a refresh cookie exists:
```ts
let accessToken = cookies.get("access_token")?.value;
const refreshToken = cookies.get("refresh_token")?.value;
let refreshedSetCookies: string[] | undefined;

if (isExpired(accessToken) && refreshToken) {
    const { refreshAccessToken } = await import("./lib/server/refresh");
    const r = await refreshAccessToken(refreshToken);
    if (r.ok) {
        accessToken = r.accessToken;
        refreshedSetCookies = r.setCookies;
        // Make the fresh token visible to this same request's downstream logic.
        cookies.set("access_token", r.accessToken!, { path: "/", httpOnly: true, sameSite: "lax", secure: !import.meta.env.DEV, maxAge: 3600 });
    }
}
```
Then use `accessToken` in place of `token` for the remaining missing-token / `/api/auth/me` validation logic. If `accessToken` is still missing/invalid → existing redirect/401 path, but also clear the refresh cookie there (append `clearAuthCookies()` to the response, import it).

(d) Ensure the final `const response = await next();` path appends `refreshedSetCookies` (if set) so the browser stores the rotated cookies:
```ts
const response = await next();
if (refreshedSetCookies) for (const c of refreshedSetCookies) response.headers.append("Set-Cookie", c);
return response;
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/middleware.ts
git commit -m "feat(auth): middleware transparently refreshes expired access tokens"
```

---

### Task B5: Proxy routes refresh-once-on-401

**Files:**
- Modify: each `frontend/src/pages/api/*/[...path].ts`

- [ ] **Step 1: Add a shared retry wrapper**

In `frontend/src/lib/server/refresh.ts`, add:
```ts
/** If a backend response is 401 and a refresh token is present, refresh once
 *  and let the caller retry with the new access token. Returns the new token
 *  + Set-Cookie list, or null if refresh isn't possible. */
export async function tryRefreshFor401(
    status: number,
    cookieHeader: string
): Promise<{ accessToken: string; setCookies: string[] } | null> {
    if (status !== 401) return null;
    const refreshToken = readCookie(cookieHeader, "refresh_token");
    if (!refreshToken) return null;
    const r = await refreshAccessToken(refreshToken);
    if (!r.ok) return null;
    return { accessToken: r.accessToken!, setCookies: r.setCookies! };
}
```

- [ ] **Step 2: Wire one proxy route, then replicate**

In `frontend/src/pages/api/budget/[...path].ts` (the canonical proxy), after the first backend fetch, if the response is 401, call `tryRefreshFor401`, and on success re-issue the backend fetch with the new `Authorization: Bearer <accessToken>`, then append `setCookies` to the returned response. Replicate the identical block in every other `*/[...path].ts` proxy (`gigs`, `calendar`, `chat`, `dm`, `jarvis`, `meals`, `kiosk`, `task-templates`, `subscriptions`, `analytics`). Since these files are near-identical, the cleanest path is to extract the proxy body into a shared `frontend/src/lib/server/proxy.ts` and have each route call it — do that if the files already share a copy-pasted shape.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/server/refresh.ts frontend/src/pages/api/
git commit -m "feat(auth): proxy routes refresh once on backend 401 and retry"
```

---

### Task B6: Logout calls backend + clears both cookies

**Files:**
- Modify: `frontend/src/pages/api/auth/logout.ts`

- [ ] **Step 1: Implement**

```ts
import type { APIRoute } from "astro";
import { clearAuthCookies } from "../../../lib/auth-cookies";

export const POST: APIRoute = async ({ cookies }) => {
    // Bump token_version server-side (logout-everywhere) before clearing cookies.
    const access = cookies.get("access_token")?.value;
    if (access) {
        const api = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
        try {
            await fetch(`${api}/api/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${access}` } });
        } catch { /* best-effort; still clear cookies below */ }
    }
    const headers = new Headers({ Location: "/login" });
    for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0");
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure");
    return new Response(null, { status: 302, headers });
};
```

- [ ] **Step 2: Type-check + commit**

Run: `cd frontend && npx astro check 2>&1 | tail -5`
```bash
git add frontend/src/pages/api/auth/logout.ts
git commit -m "feat(auth): logout bumps server token_version + clears both cookies"
```

---

## Phase C — E2E + verification

### Task C1: E2E — transparent refresh + logout revocation

**Files:**
- Create: `e2e-tests/tests/auth-refresh.spec.ts`

- [ ] **Step 1: Write the E2E test**

`e2e-tests/tests/auth-refresh.spec.ts` (follow the existing suite's login helper + base URL conventions):

```ts
import { test, expect } from "@playwright/test";
import { login } from "./helpers"; // use the suite's existing login helper

test("expired access token is transparently refreshed", async ({ page, context }) => {
    await login(page); // lands authenticated on /dashboard
    // Force the access token to look expired by deleting only it; refresh cookie remains.
    const cookies = await context.cookies();
    const others = cookies.filter((c) => c.name !== "access_token");
    await context.clearCookies();
    await context.addCookies(others);
    // Navigate to a protected page — middleware should refresh, not bounce to /login.
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard/);
    const after = await context.cookies();
    expect(after.find((c) => c.name === "access_token")).toBeTruthy();
});

test("logout invalidates the refresh token", async ({ page, context }) => {
    await login(page);
    const before = await context.cookies();
    const refresh = before.find((c) => c.name === "refresh_token")!.value;
    await page.request.post("/api/auth/logout");
    // Re-plant the old refresh cookie and try to refresh — backend must 401.
    await context.addCookies([{ name: "refresh_token", value: refresh, url: page.url() }]);
    const resp = await page.request.post("/api/auth/refresh");
    expect(resp.status()).toBe(401);
});
```

- [ ] **Step 2: Run E2E (requires the dev stack up + frontend rebuilt)**

Run: `cd e2e-tests && npm run test -- auth-refresh.spec.ts`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add e2e-tests/tests/auth-refresh.spec.ts
git commit -m "test(e2e): transparent refresh + logout revocation"
```

---

### Task C2: Manual verification via the `verify` skill

- [ ] **Step 1:** Rebuild the frontend image + bring the stack up; log in through the browser; confirm normal navigation works, then wait past 1h (or temporarily set `ACCESS_TOKEN_EXPIRE_MINUTES=1` in a scratch env) and confirm a protected page still loads without a login bounce, and that logout from one session blocks refresh.

- [ ] **Step 2:** Confirm a legacy 7-day `access_token` cookie (mint one with the old TTL + no `type`) still authenticates (backward-compat grace).

---

## Self-Review

**Spec coverage:** access(1h)+refresh(7d) → A1/A3/A5; token_version revocation → A2/A6/A7; /auth/refresh → A6; rotation → A6 (issues new pair); backward-compat grace → A3/A4 (missing type = access); SESSION_SECRET_KEY split → A1/A9; BFF two-cookie + refresh + proxy retry + logout → B1–B6; tests → A2/A3/A4/A5/A6/A7 + C1. All spec sections covered.

**Placeholder scan:** Proxy-route replication (B5) names the exact routes and recommends extracting `proxy.ts`; OAuth/invitation edits (A9) cite the call-site line numbers. No "TBD"/"handle edge cases".

**Type consistency:** `authenticate_user` → 3-tuple (A5) consumed in login (A5) and asserted (A5 test); `create_refresh_token(sub, version)` signature used identically in A3/A5/A6; `TokenResponse.refresh_token` (A8) used by A5/A6/A9; `authCookies(access, refresh, secure)` / `clearAuthCookies()` used consistently in B1/B2/B3/B6; `refreshAccessToken`/`readCookie`/`tryRefreshFor401` defined in B3/B5 and used in B4/B5.
