# Super-Admin Dashboard (Phase 0+1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-tenant operator surface — a super-admin identity, an append-only operator audit log, a families directory, per-family read-only support views, and ten bounded write actions — so a support case can be diagnosed and fixed without SSH-ing to the production host.

**Architecture:** A `require_superadmin` FastAPI dependency (DB flag **AND** env allowlist, both required, 404 on failure) guards a new `/api/admin/*` router. Admin routes take `family_id` as an explicit path parameter and read through two dedicated cross-tenant services, leaving `BaseFamilyService`'s isolation untouched. The UI is an `/admin/*` route group inside the existing Astro app, reached through a same-origin proxy, behind a Cloudflare Access path policy.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic · PostgreSQL 15 · pytest/pytest-asyncio · Astro 5 SSR · Tailwind CSS v4

**Spec:** `docs/superpowers/specs/2026-07-26-super-admin-dashboard-design.md`

---

## Global Constraints

- **Never relax `family_id` filtering in existing services.** `BaseFamilyService` and every existing family-scoped service are off-limits. Cross-tenant reads live only in `app/services/admin/`.
- **Admin routes must never use `verify_family_id` or `get_family_user`** (`app/core/dependencies.py:198`, `:163`) — both hard-compare against `current_user.family_id` and would reject every admin request.
- **Every rejection from the admin surface is HTTP 404**, never 403. A 403 confirms the route exists.
- **Every mutating admin route writes exactly one `operator_audit_log` row in the same transaction as the mutation.** No unaudited mutations.
- **`users.role` and `family_invitations.role` are PG enums storing UPPERCASE** (`'PARENT'`, `'CHILD'`, `'TEEN'`) while the Python enum *values* are lowercase. Always compare using the `UserRole` enum member (e.g. `User.role == UserRole.PARENT`), never a raw string.
- **Every count filters `deleted_at IS NULL`** on both `families` and `users`. `is_active` is a separate, older flag and is not a substitute.
- **All datetimes must be timezone-aware.** `ruff` enforces DTZ; use `datetime.now(timezone.utc)`.
- **Ruff is zero-tolerance in CI:** `cd backend && ruff check app` must pass. Config: `backend/ruff.toml`.
- **Admin UI copy is EN-only**, in a page-local `const T = {...}` dict. Do **not** add keys to `frontend/src/lib/i18n.ts`.
- **No new frontend dependencies.** `package.json` has six deps and the prod CSP (`script-src 'self' 'unsafe-inline'`, `connect-src 'self'`) blocks CDN scripts. No charts in Phase 1 — numbers and tables only.
- **Admin shell wraps `Layout.astro` directly.** Never `PageLayout.astro` or `BudgetShell.astro` — their `BottomNav` is hard-wired with no opt-out prop.
- Run tests with: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/<file> -v`. When podman is down, the bare-metal fallback is `cd backend && DATABASE_URL=... .venv/bin/pytest --no-cov tests/<file> -v` (see `MEMORY.md → Local tests sin podman`).
- Migration chain head at plan time is `drop_budget_sync_state`. Tasks 1→2→3 extend it in that order.

### Two deliberate deviations from the spec

1. **Spec §3.2 says admin routes open a short-lived `AsyncSessionLocal` rather than `Depends(get_db)`.** This plan uses `Depends(get_db)`. The `AsyncSessionLocal` pattern exists in `internal/metrics.py` because Prometheus scrapes it every 15s and a slow scrape must not hold a pooled connection; admin routes are low-frequency and authenticated, and — decisively — `tests/conftest.py` overrides `get_db` only, so a route bypassing it would silently run against the *dev* database during tests. Testability wins.
2. **Spec §3.5 gives `operator_audit_log.actor_user_id` an FK to `users`.** This plan omits the FK, matching the target columns. Same rationale: an audit row must outlive every row it references, including the operator's own account.

---

## File Structure

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/models/operator_audit.py` | `OperatorAuditLog` model |
| `backend/app/services/admin/__init__.py` | package marker |
| `backend/app/services/admin/operator_audit_service.py` | staging + redaction of audit rows |
| `backend/app/services/admin/admin_lookup_service.py` | family/user search + directory listing |
| `backend/app/services/admin/admin_read_service.py` | platform pulse + per-family aggregate reads |
| `backend/app/services/admin/admin_action_service.py` | the ten operator actions |
| `backend/app/schemas/admin.py` | admin response/request schemas |
| `backend/app/api/routes/admin/__init__.py` | admin router assembly |
| `backend/app/api/routes/admin/overview.py` | platform pulse, billing review, deletions, audit |
| `backend/app/api/routes/admin/families.py` | directory + family detail |
| `backend/app/api/routes/admin/actions.py` | operator actions |
| `backend/migrations/versions/2026_07_26_superadmin_flag.py` | migration 1 |
| `backend/migrations/versions/2026_07_26_operator_audit_log.py` | migration 2 |
| `backend/migrations/versions/2026_07_26_user_last_seen_at.py` | migration 3 |
| `backend/tests/test_admin_authz.py` | authorization matrix + isolation |
| `backend/tests/test_admin_reads.py` | directory, detail, pulse correctness |
| `backend/tests/test_admin_actions.py` | each operator action + its audit row |
| `backend/tests/test_family_suspension.py` | `is_active` enforcement |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/core/config.py` | `SUPERADMIN_EMAILS`, `LAST_SEEN_THROTTLE_MINUTES` |
| `backend/app/core/dependencies.py` | `require_superadmin`, `_touch_last_seen`, suspension check |
| `backend/app/models/user.py` | `is_superadmin`, `last_seen_at` |
| `backend/app/schemas/user.py` | `is_superadmin` on `UserResponse` |
| `backend/app/api/routes/auth.py` | `/me` returns `is_superadmin` |
| `backend/app/services/auth_service.py` | `authenticate_user` rejects suspended families |
| `backend/app/services/family_deletion_service.py` | `cancel_deletion` |
| `backend/app/main.py` | register admin router |
| `backend/tests/conftest.py` | superadmin fixtures |

**Frontend — created**

| File | Responsibility |
|---|---|
| `frontend/src/pages/api/admin/[...path].ts` | same-origin proxy to `/api/admin/*` |
| `frontend/src/components/ui/AdminShell.astro` | wide-container admin chrome, no BottomNav |
| `frontend/src/pages/admin/index.astro` | platform pulse |
| `frontend/src/pages/admin/families.astro` | directory + search |
| `frontend/src/pages/admin/families/[id].astro` | family detail + actions |
| `frontend/src/pages/admin/billing-review.astro` | needs-review queue |
| `frontend/src/pages/admin/deletions.astro` | pending-purge queue |
| `frontend/src/pages/admin/audit.astro` | global audit log |

**Frontend — modified:** `frontend/src/middleware.ts` (fail-closed `/admin` guard), `frontend/src/env.d.ts` (add `is_superadmin` to the `User` type).

---

## Task 1: Superadmin identity and the `require_superadmin` dependency

**Files:**
- Create: `backend/migrations/versions/2026_07_26_superadmin_flag.py`
- Modify: `backend/app/models/user.py:47`
- Modify: `backend/app/core/config.py:219`, `:242`
- Modify: `backend/app/core/dependencies.py:1-11`, `:65`
- Modify: `backend/tests/conftest.py:266`
- Test: `backend/tests/test_admin_authz.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `require_superadmin(current_user: User = Depends(get_current_user)) -> User`; `settings.superadmin_emails_set -> frozenset[str]`; `User.is_superadmin: bool`; pytest fixtures `test_superadmin_user`, `superadmin_headers`, `allowlist_superadmin`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_admin_authz.py`:

```python
"""Authorization matrix for the super-admin surface.

The rule under test: an operator needs BOTH users.is_superadmin AND an email
in SUPERADMIN_EMAILS. Either alone is insufficient, and every failure mode
must return 404 (not 403) so the surface is not discoverable.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import require_superadmin
from app.models.user import User


@pytest.mark.asyncio
async def test_require_superadmin_accepts_flag_and_allowlist(
    client: AsyncClient, superadmin_headers: dict
):
    resp = await client.get("/api/admin/ping", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_require_superadmin_rejects_flag_without_allowlist(
    client: AsyncClient, db_session, test_superadmin_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", [])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "superadmin@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_allowlist_without_flag(
    client: AsyncClient, db_session, test_parent_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", ["parent@test.com"])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_plain_parent(
    client: AsyncClient, auth_headers: dict, allowlist_superadmin
):
    resp = await client.get("/api/admin/ping", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_anonymous(client: AsyncClient):
    resp = await client.get("/api/admin/ping")
    assert resp.status_code == 401
```

Add the fixtures to `backend/tests/conftest.py`, immediately after the `auth_headers` fixture (line 265):

```python
@pytest_asyncio.fixture
def allowlist_superadmin(monkeypatch):
    """Put superadmin@test.com on the operator allowlist for one test.

    settings is a module-level singleton; monkeypatch restores the original
    list at teardown so the allowlist never leaks between tests.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", ["superadmin@test.com"])
    return ["superadmin@test.com"]


@pytest_asyncio.fixture
async def test_superadmin_user(db_session: AsyncSession, test_family):
    """A platform operator. Belongs to test_family, but admin routes must
    never rely on that — they read other families by explicit family_id."""
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    user = User(
        email="superadmin@test.com",
        password_hash=get_password_hash("password123"),
        name="Test Superadmin",
        role=UserRole.PARENT,
        family_id=test_family.id,
        email_verified=True,
        is_superadmin=True,
        points=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superadmin_headers(
    client: AsyncClient, test_superadmin_user, allowlist_superadmin
) -> dict:
    """Authorization headers for a fully-empowered operator."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "superadmin@test.com", "password": "password123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_authz.py -v`

Expected: collection error or failures — `cannot import name 'require_superadmin' from 'app.core.dependencies'`.

- [ ] **Step 3: Add the migration**

Create `backend/migrations/versions/2026_07_26_superadmin_flag.py`:

```python
"""Add users.is_superadmin — the platform-operator flag.

Half of the super-admin gate: a user is an operator only when this column is
true AND their email appears in the SUPERADMIN_EMAILS env allowlist. Split
deliberately so neither a stolen database dump nor an env edit alone is
sufficient to mint an operator.

Revision ID: superadmin_flag
Revises: drop_budget_sync_state
"""
import sqlalchemy as sa
from alembic import op

revision = "superadmin_flag"
down_revision = "drop_budget_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
```

- [ ] **Step 4: Add the model column**

In `backend/app/models/user.py`, immediately after the `is_active` column (line 47):

```python
    is_active = Column(Boolean, default=True, nullable=False)
    # Platform-operator flag. NOT a family role — it grants cross-tenant read
    # and a bounded set of write actions through /api/admin/*. Insufficient on
    # its own: require_superadmin also demands the email be listed in
    # settings.SUPERADMIN_EMAILS. There is deliberately no UI to set this;
    # it is granted by a one-off UPDATE on the production host.
    is_superadmin = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )
```

- [ ] **Step 5: Add the setting**

In `backend/app/core/config.py`, immediately after `INTERNAL_API_TOKEN` (line 219):

```python
    INTERNAL_API_TOKEN: str = ""

    # Platform-operator allowlist (comma-separated emails). A user is a
    # super-admin only when users.is_superadmin is true AND their email is
    # listed here. Empty — the default in local dev and CI — makes the entire
    # /api/admin surface unreachable by anyone. It fails closed.
    SUPERADMIN_EMAILS: Union[List[str], str] = []
```

And immediately after the `parse_google_client_ids` validator (line 242):

```python
    @field_validator('SUPERADMIN_EMAILS', mode='before')
    @classmethod
    def parse_superadmin_emails(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [e.strip().lower() for e in v.split(',') if e.strip()]
        return [str(e).strip().lower() for e in v if str(e).strip()]
```

And immediately after the `email_link_base` property (line 173):

```python
    @property
    def superadmin_emails_set(self) -> frozenset[str]:
        """Normalized operator allowlist. Lower-cased at parse time so the
        membership test is a plain lookup on an already-lowered email."""
        return frozenset(self.SUPERADMIN_EMAILS)
```

- [ ] **Step 6: Add the dependency**

In `backend/app/core/dependencies.py`, add to the imports at line 10:

```python
from app.core.config import settings
```

And insert immediately after `require_parent_role` (line 65):

```python
def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Platform operator. Requires BOTH the DB flag and the env allowlist.

    Rejects with 404 rather than 403 so the admin surface is not
    discoverable — a 403 confirms the route exists. Both conditions are
    required on purpose: the DB flag alone would let a stolen dump mint an
    operator, and the allowlist alone would hand platform powers to anyone
    who gains control of a listed mailbox.
    """
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
    if (current_user.email or "").lower() not in settings.superadmin_emails_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
    return current_user
```

- [ ] **Step 7: Add the temporary ping route so the matrix has a target**

Create `backend/app/api/routes/admin/__init__.py`:

```python
"""Cross-tenant operator surface.

Every route here is guarded by require_superadmin and takes family_id as an
explicit path parameter. Nothing in this package may use verify_family_id or
get_family_user — both compare against the caller's own family_id and would
reject every admin request.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import require_superadmin
from app.models.user import User

router = APIRouter()


@router.get("/ping")
async def ping(_operator: User = Depends(require_superadmin)) -> dict:
    """Liveness probe for the admin surface. Exists so the authorization
    matrix has a stable, side-effect-free target."""
    return {"ok": True}
```

In `backend/app/main.py`, after the gigs router registration (line 362):

```python
from app.api.routes.admin import router as admin_router  # noqa: E402
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_authz.py -v`

Expected: 5 passed.

- [ ] **Step 9: Verify the migration round-trips and lint passes**

```bash
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
cd backend && ruff check app
```

Expected: all succeed, ruff reports no issues.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/user.py backend/app/core/config.py \
  backend/app/core/dependencies.py backend/app/api/routes/admin/__init__.py \
  backend/app/main.py backend/migrations/versions/2026_07_26_superadmin_flag.py \
  backend/tests/conftest.py backend/tests/test_admin_authz.py
git commit -m "feat(admin): superadmin identity and require_superadmin dependency"
```

---

## Task 2: Operator audit log

**Files:**
- Create: `backend/app/models/operator_audit.py`
- Create: `backend/app/services/admin/__init__.py`
- Create: `backend/app/services/admin/operator_audit_service.py`
- Create: `backend/migrations/versions/2026_07_26_operator_audit_log.py`
- Test: `backend/tests/test_admin_actions.py`

**Interfaces:**
- Consumes: `User.is_superadmin` (Task 1).
- Produces: `OperatorAuditLog` model; `OperatorAuditService.record(db, *, actor, action, target_family_id=None, target_user_id=None, params=None, result="ok", error=None) -> OperatorAuditLog` (stages, does **not** commit).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_admin_actions.py`:

```python
"""Operator actions and their audit trail."""

import pytest
from sqlalchemy import select

from app.models.operator_audit import OperatorAuditLog
from app.services.admin.operator_audit_service import OperatorAuditService


@pytest.mark.asyncio
async def test_audit_record_stages_without_committing(
    db_session, test_superadmin_user, test_family
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="family.suspend",
        target_family_id=test_family.id,
        params={"reason": "abuse"},
    )
    # Not committed yet — a rollback must erase it entirely.
    await db_session.rollback()
    rows = (await db_session.execute(select(OperatorAuditLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_audit_record_persists_on_commit(
    db_session, test_superadmin_user, test_family
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="family.suspend",
        target_family_id=test_family.id,
        params={"reason": "abuse"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(OperatorAuditLog))).scalar_one()
    assert row.action == "family.suspend"
    assert row.actor_email == "superadmin@test.com"
    assert row.actor_user_id == test_superadmin_user.id
    assert row.target_family_id == test_family.id
    assert row.result == "ok"
    assert row.params == {"reason": "abuse"}


@pytest.mark.asyncio
async def test_audit_record_redacts_secret_params(
    db_session, test_superadmin_user
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="user.password_reset",
        params={"password": "hunter2", "token": "abc", "email": "a@b.com"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(OperatorAuditLog))).scalar_one()
    assert row.params["password"] == "***"
    assert row.params["token"] == "***"
    assert row.params["email"] == "a@b.com"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -v`

Expected: `ModuleNotFoundError: No module named 'app.models.operator_audit'`.

- [ ] **Step 3: Add the model**

Create `backend/app/models/operator_audit.py`:

```python
"""Append-only record of every platform-operator action.

Deliberately carries NO foreign keys. An audit row must outlive every row it
references: a FK with ON DELETE CASCADE would erase the record of a family
deletion at purge time, and one without a delete rule would block the purge
sweep outright. actor_email is denormalized for the same reason.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class OperatorAuditLog(Base):
    """One row per attempted operator action, successful or not."""

    __tablename__ = "operator_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id = Column(UUID(as_uuid=True), nullable=False)
    actor_email = Column(String(255), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    target_family_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    target_user_id = Column(UUID(as_uuid=True), nullable=True)
    params = Column(JSONB, nullable=True)
    result = Column(String(16), nullable=False, default="ok")
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self):
        return (
            f"<OperatorAuditLog(action={self.action}, "
            f"actor={self.actor_email}, result={self.result})>"
        )
```

Register it for metadata discovery — in `backend/app/models/__init__.py`, add alongside the other model imports:

```python
from app.models.operator_audit import OperatorAuditLog  # noqa: F401
```

- [ ] **Step 4: Add the migration**

Create `backend/migrations/versions/2026_07_26_operator_audit_log.py`:

```python
"""Create operator_audit_log — append-only trail of platform-operator actions.

No foreign keys by design: the row must survive the purge of the family and
the deletion of the operator account it describes.

Revision ID: operator_audit_log
Revises: superadmin_flag
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "operator_audit_log"
down_revision = "superadmin_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_audit_log",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_family_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column(
            "result", sa.String(length=16), nullable=False, server_default="ok"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_operator_audit_log_action", "operator_audit_log", ["action"]
    )
    op.create_index(
        "ix_operator_audit_log_target_family_id",
        "operator_audit_log",
        ["target_family_id"],
    )
    op.create_index(
        "ix_operator_audit_log_created_at", "operator_audit_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_operator_audit_log_created_at", "operator_audit_log")
    op.drop_index("ix_operator_audit_log_target_family_id", "operator_audit_log")
    op.drop_index("ix_operator_audit_log_action", "operator_audit_log")
    op.drop_table("operator_audit_log")
```

- [ ] **Step 5: Add the service**

Create `backend/app/services/admin/__init__.py` (empty file), then `backend/app/services/admin/operator_audit_service.py`:

```python
"""Staging of operator audit rows."""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operator_audit import OperatorAuditLog
from app.models.user import User

# Parameter names whose values must never reach the audit log verbatim.
_SECRET_KEYS = frozenset(
    {"password", "new_password", "token", "secret", "access_token", "refresh_token"}
)


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """Replace secret-looking values with a fixed marker.

    The audit log is read by a human during incident review; a leaked token
    or password in it would be a second incident.
    """
    return {
        k: ("***" if k.lower() in _SECRET_KEYS else v) for k, v in params.items()
    }


class OperatorAuditService:
    """Writes the append-only operator trail."""

    @staticmethod
    def record(
        db: AsyncSession,
        *,
        actor: User,
        action: str,
        target_family_id: Optional[UUID] = None,
        target_user_id: Optional[UUID] = None,
        params: Optional[dict[str, Any]] = None,
        result: str = "ok",
        error: Optional[str] = None,
    ) -> OperatorAuditLog:
        """Stage an audit row on the CALLER'S session.

        Deliberately does not commit. The row must land in the same
        transaction as the mutation it describes, so a rolled-back mutation
        cannot leave an "ok" audit row behind, and a committed mutation
        cannot go unrecorded.
        """
        row = OperatorAuditLog(
            actor_user_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_family_id=target_family_id,
            target_user_id=target_user_id,
            params=_redact(params or {}),
            result=result,
            error=error,
        )
        db.add(row)
        return row
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -v`

Expected: 3 passed.

- [ ] **Step 7: Verify migration round-trip**

```bash
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
cd backend && ruff check app
```

Expected: all succeed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/operator_audit.py backend/app/models/__init__.py \
  backend/app/services/admin/ \
  backend/migrations/versions/2026_07_26_operator_audit_log.py \
  backend/tests/test_admin_actions.py
git commit -m "feat(admin): append-only operator audit log"
```

---

## Task 3: `users.last_seen_at`

**Files:**
- Create: `backend/migrations/versions/2026_07_26_user_last_seen_at.py`
- Modify: `backend/app/models/user.py:123`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/dependencies.py:14-55`
- Test: `backend/tests/test_admin_reads.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `User.last_seen_at: datetime | None`, stamped by `get_current_user`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_admin_reads.py`:

```python
"""Admin read surfaces and the instrumentation they depend on."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.user import User


@pytest.mark.asyncio
async def test_last_seen_at_stamped_on_authenticated_request(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at is not None


@pytest.mark.asyncio
async def test_last_seen_at_not_rewritten_within_throttle_window(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    first = test_parent_user.last_seen_at

    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at == first


@pytest.mark.asyncio
async def test_last_seen_at_rewritten_once_throttle_elapses(
    client, db_session, auth_headers, test_parent_user
):
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    test_parent_user.last_seen_at = stale
    await db_session.commit()

    await client.get("/api/auth/me", headers=auth_headers)
    refreshed = (
        await db_session.execute(
            select(User).where(User.id == test_parent_user.id)
        )
    ).scalar_one()
    assert refreshed.last_seen_at > stale
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -v`

Expected: `AttributeError: 'User' object has no attribute 'last_seen_at'`.

- [ ] **Step 3: Add the migration**

Create `backend/migrations/versions/2026_07_26_user_last_seen_at.py`:

```python
"""Add users.last_seen_at — throttled activity stamp.

The single prerequisite for DAU/WAU, retention, dormant-tenant detection and
every "is this family alive?" answer in the support console. Recorded now
because activity history that is not captured cannot be reconstructed later.

Revision ID: user_last_seen_at
Revises: operator_audit_log
"""
import sqlalchemy as sa
from alembic import op

revision = "user_last_seen_at"
down_revision = "operator_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
```

- [ ] **Step 4: Add the model column and the setting**

In `backend/app/models/user.py`, immediately after `deleted_at` (line 123):

```python
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Throttled activity stamp, written by get_current_user at most once per
    # settings.LAST_SEEN_THROTTLE_MINUTES. Best-effort: a failed write never
    # fails the request. Not indexed — the admin directory reaches it via
    # family_id, and a per-user index would cost every request a write to it.
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
```

In `backend/app/core/config.py`, immediately after `SUPERADMIN_EMAILS`:

```python
    # Minimum gap between users.last_seen_at writes for one user. Guards the
    # hot path: without it every authenticated request would issue an UPDATE.
    LAST_SEEN_THROTTLE_MINUTES: int = 15
```

- [ ] **Step 5: Stamp it from `get_current_user`**

In `backend/app/core/dependencies.py`, extend the imports at lines 1-3:

```python
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone
```

Replace the final `return user` of `get_current_user` (line 55) with:

```python
    await _touch_last_seen(db, user)

    return user


async def _touch_last_seen(db: AsyncSession, user: User) -> None:
    """Throttled, best-effort activity stamp.

    Issued as a targeted UPDATE rather than an ORM flush so it cannot drag
    unrelated pending state into the write. Any failure is swallowed: an
    instrumentation write must never break the request it is measuring.
    """
    now = datetime.now(timezone.utc)
    throttle = timedelta(minutes=settings.LAST_SEEN_THROTTLE_MINUTES)
    if user.last_seen_at is not None and now - user.last_seen_at < throttle:
        return
    try:
        await db.execute(
            update(User).where(User.id == user.id).values(last_seen_at=now)
        )
        await db.commit()
        user.last_seen_at = now
    except Exception:
        await db.rollback()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -v`

Expected: 3 passed.

- [ ] **Step 7: Run the full auth suite to confirm nothing regressed**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth.py -v`

Expected: all pass. The new commit inside `get_current_user` runs before route logic, so no route's transaction is affected.

- [ ] **Step 8: Verify migration round-trip and lint**

```bash
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
cd backend && ruff check app
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/user.py backend/app/core/config.py \
  backend/app/core/dependencies.py \
  backend/migrations/versions/2026_07_26_user_last_seen_at.py \
  backend/tests/test_admin_reads.py
git commit -m "feat(admin): throttled users.last_seen_at activity stamp"
```

---

## Task 4: Platform pulse endpoint

**Files:**
- Create: `backend/app/services/admin/admin_read_service.py`
- Create: `backend/app/api/routes/admin/overview.py`
- Modify: `backend/app/api/routes/admin/__init__.py`
- Test: `backend/tests/test_admin_reads.py`

**Interfaces:**
- Consumes: `require_superadmin` (Task 1).
- Produces: `AdminReadService.platform_pulse(db: AsyncSession) -> dict`; `GET /api/admin/overview`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_reads.py`:

```python
@pytest.mark.asyncio
async def test_platform_pulse_counts_exclude_soft_deleted(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    from app.models.family import Family

    gone = Family(name="Closed Family", deleted_at=datetime.now(timezone.utc))
    db_session.add(gone)
    await db_session.commit()

    resp = await client.get("/api/admin/overview", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["families_total"] == 1
    assert body["families_pending_purge"] == 1
    assert body["users_total"] >= 1


@pytest.mark.asyncio
async def test_platform_pulse_rejects_non_operator(client, auth_headers):
    resp = await client.get("/api/admin/overview", headers=auth_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -k pulse -v`

Expected: FAIL — 404 for the operator too, because the route does not exist.

- [ ] **Step 3: Write the read service**

Create `backend/app/services/admin/admin_read_service.py`:

```python
"""Cross-tenant aggregate reads for the operator console.

Every query here deliberately spans families. It exists as a separate module
precisely so BaseFamilyService's family_id filters are never relaxed — that
would silently widen roughly fifty family-scoped services.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AWebhookDelivery
from app.models.budget import BudgetReceiptDraft
from app.models.family import Family
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.user import APPROVAL_PENDING, User

# Subscription statuses that represent a live entitlement backed by PayPal.
# 'past_due' and 'payment_failed' are inside the billing grace window and are
# still paying customers. Anything without a paypal_subscription_id is a comp
# or a free row and must not be counted as revenue.
PAYING_STATUSES = ("active", "past_due", "payment_failed")


class AdminReadService:
    """Read-only aggregates. Never mutates."""

    @staticmethod
    async def platform_pulse(db: AsyncSession) -> dict:
        """One-screen platform state. All counts exclude soft-deleted rows."""
        families_total = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_(None))
        )
        families_suspended = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_(None), Family.is_active.is_(False))
        )
        families_pending_purge = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_not(None))
        )
        users_total = await db.scalar(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
        users_verified = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.email_verified.is_(True))
        )
        users_pending_approval = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.deleted_at.is_(None),
                User.approval_status == APPROVAL_PENDING,
            )
        )
        billing_needs_review = await db.scalar(
            select(func.count())
            .select_from(FamilySubscription)
            .where(FamilySubscription.needs_review.is_(True))
        )
        receipt_drafts_pending = await db.scalar(
            select(func.count())
            .select_from(BudgetReceiptDraft)
            .where(BudgetReceiptDraft.status == "pending")
        )
        overdue_assignments = await db.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .where(TaskAssignment.status == AssignmentStatus.OVERDUE)
        )

        return {
            "families_total": int(families_total or 0),
            "families_suspended": int(families_suspended or 0),
            "families_pending_purge": int(families_pending_purge or 0),
            "users_total": int(users_total or 0),
            "users_verified": int(users_verified or 0),
            "users_pending_approval": int(users_pending_approval or 0),
            "billing_needs_review": int(billing_needs_review or 0),
            "receipt_drafts_pending": int(receipt_drafts_pending or 0),
            "overdue_assignments": int(overdue_assignments or 0),
            "mrr": await AdminReadService.current_state_mrr(db),
            "a2a": await AdminReadService.a2a_health(db),
        }

    @staticmethod
    async def current_state_mrr(db: AsyncSession) -> list[dict]:
        """Monthly recurring revenue implied by TODAY'S subscription rows.

        Not a time series and not reconstructible history: family_subscriptions
        holds one row per family, mutated in place, and plan prices are mutable
        list prices. Reported per currency — there is no stored FX rate, so a
        single summed figure would be fiction.
        """
        rows = (
            await db.execute(
                select(
                    SubscriptionPlan.currency,
                    SubscriptionPlan.name,
                    FamilySubscription.billing_cycle,
                    SubscriptionPlan.price_monthly_cents,
                    SubscriptionPlan.price_annual_cents,
                    func.count().label("n"),
                )
                .select_from(FamilySubscription)
                .join(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .where(
                    FamilySubscription.status.in_(PAYING_STATUSES),
                    FamilySubscription.paypal_subscription_id.is_not(None),
                    SubscriptionPlan.name != "free",
                )
                .group_by(
                    SubscriptionPlan.currency,
                    SubscriptionPlan.name,
                    FamilySubscription.billing_cycle,
                    SubscriptionPlan.price_monthly_cents,
                    SubscriptionPlan.price_annual_cents,
                )
            )
        ).all()

        per_currency: dict[str, dict] = {}
        for currency, plan_name, cycle, monthly, annual, n in rows:
            bucket = per_currency.setdefault(
                currency, {"currency": currency, "cents": 0, "subscriptions": 0}
            )
            unit = annual // 12 if cycle == "annual" else monthly
            bucket["cents"] += unit * n
            bucket["subscriptions"] += n
        return sorted(per_currency.values(), key=lambda b: b["currency"])

    @staticmethod
    async def a2a_health(db: AsyncSession) -> dict:
        """Outbound bank-matcher webhook delivery health."""
        now = datetime.now(timezone.utc)
        by_status = dict(
            (
                await db.execute(
                    select(A2AWebhookDelivery.status, func.count()).group_by(
                        A2AWebhookDelivery.status
                    )
                )
            ).all()
        )
        overdue_retries = await db.scalar(
            select(func.count())
            .select_from(A2AWebhookDelivery)
            .where(
                A2AWebhookDelivery.status == "pending",
                A2AWebhookDelivery.next_retry_at.is_not(None),
                A2AWebhookDelivery.next_retry_at < now,
            )
        )
        oldest_pending = await db.scalar(
            select(func.min(A2AWebhookDelivery.created_at)).where(
                A2AWebhookDelivery.status == "pending"
            )
        )
        return {
            "by_status": {k: int(v) for k, v in by_status.items()},
            "overdue_retries": int(overdue_retries or 0),
            "oldest_pending_at": (
                oldest_pending.isoformat() if oldest_pending else None
            ),
        }
```

- [ ] **Step 4: Write the route**

Create `backend/app/api/routes/admin/overview.py`:

```python
"""Platform-wide operator reads."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_read_service import AdminReadService

router = APIRouter()


@router.get("/overview")
async def platform_overview(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-screen platform state: tenants, users, billing, queues."""
    return await AdminReadService.platform_pulse(db)
```

Wire it in `backend/app/api/routes/admin/__init__.py` — add the import and include after the `ping` route:

```python
from app.api.routes.admin import overview  # noqa: E402

router.include_router(overview.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -v`

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/admin/admin_read_service.py \
  backend/app/api/routes/admin/ backend/tests/test_admin_reads.py
git commit -m "feat(admin): platform pulse overview endpoint"
```

---

## Task 5: Family directory and search

**Files:**
- Create: `backend/app/services/admin/admin_lookup_service.py`
- Create: `backend/app/api/routes/admin/families.py`
- Modify: `backend/app/api/routes/admin/__init__.py`
- Test: `backend/tests/test_admin_reads.py`

**Interfaces:**
- Consumes: `AdminReadService.PAYING_STATUSES` is not needed here; `require_superadmin`.
- Produces: `AdminLookupService.search_families(db, *, q=None, include_deleted=False, limit=50, offset=0) -> dict` returning `{"total": int, "items": list[dict]}`; `GET /api/admin/families?q=&include_deleted=&limit=&offset=`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_reads.py`:

```python
@pytest.mark.asyncio
async def test_family_directory_lists_active_families(
    client, superadmin_headers, test_family, test_parent_user
):
    resp = await client.get("/api/admin/families", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["name"] == "Test Family"
    assert row["member_count"] >= 1
    assert row["deleted_at"] is None


@pytest.mark.asyncio
async def test_family_directory_search_by_member_email(
    client, superadmin_headers, test_family, test_parent_user
):
    resp = await client.get(
        "/api/admin/families?q=parent@test.com", headers=superadmin_headers
    )
    assert resp.json()["total"] == 1

    resp = await client.get(
        "/api/admin/families?q=nobody@example.com", headers=superadmin_headers
    )
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_family_directory_search_by_join_code(
    client, db_session, superadmin_headers, test_family
):
    test_family.join_code = "ABC234"
    await db_session.commit()
    resp = await client.get(
        "/api/admin/families?q=abc234", headers=superadmin_headers
    )
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_family_directory_excludes_deleted_unless_requested(
    client, db_session, superadmin_headers, test_family
):
    from app.models.family import Family

    gone = Family(name="Closed", deleted_at=datetime.now(timezone.utc))
    db_session.add(gone)
    await db_session.commit()

    resp = await client.get("/api/admin/families", headers=superadmin_headers)
    assert resp.json()["total"] == 1

    resp = await client.get(
        "/api/admin/families?include_deleted=true", headers=superadmin_headers
    )
    assert resp.json()["total"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -k directory -v`

Expected: FAIL — 404, route missing.

- [ ] **Step 3: Write the lookup service**

Create `backend/app/services/admin/admin_lookup_service.py`:

```python
"""Family and user lookup for the operator console."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import User


def _as_uuid(value: str) -> Optional[UUID]:
    """Parse a search term as a UUID, or None when it isn't one."""
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


class AdminLookupService:
    """Cross-tenant search. Read-only."""

    @staticmethod
    async def search_families(
        db: AsyncSession,
        *,
        q: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Directory of families, newest first.

        ``q`` matches a family name, a join code, a family id, or the email of
        any member — the four things a support email actually contains.
        Soft-deleted families are excluded unless explicitly requested.
        """
        conditions = []
        if not include_deleted:
            conditions.append(Family.deleted_at.is_(None))

        if q:
            needle = q.strip().lower()
            like = f"%{needle}%"
            member_match = (
                select(User.family_id)
                .where(func.lower(User.email).like(like))
                .scalar_subquery()
            )
            terms = [
                func.lower(Family.name).like(like),
                func.lower(Family.join_code).like(like),
                Family.id.in_(member_match),
            ]
            as_uuid = _as_uuid(needle)
            if as_uuid is not None:
                terms.append(Family.id == as_uuid)
            conditions.append(or_(*terms))

        total = await db.scalar(
            select(func.count()).select_from(Family).where(*conditions)
        )

        member_counts = (
            select(User.family_id, func.count().label("member_count"))
            .where(User.deleted_at.is_(None))
            .group_by(User.family_id)
            .subquery()
        )
        last_seen = (
            select(
                User.family_id,
                func.max(User.last_seen_at).label("last_seen_at"),
            )
            .group_by(User.family_id)
            .subquery()
        )

        rows = (
            await db.execute(
                select(
                    Family,
                    SubscriptionPlan.name,
                    FamilySubscription.status,
                    member_counts.c.member_count,
                    last_seen.c.last_seen_at,
                )
                .select_from(Family)
                .outerjoin(
                    FamilySubscription,
                    FamilySubscription.family_id == Family.id,
                )
                .outerjoin(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .outerjoin(member_counts, member_counts.c.family_id == Family.id)
                .outerjoin(last_seen, last_seen.c.family_id == Family.id)
                .where(*conditions)
                .order_by(Family.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        return {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(fam.id),
                    "name": fam.name,
                    "plan": plan_name or "free",
                    "subscription_status": sub_status,
                    "is_active": fam.is_active,
                    "member_count": int(member_count or 0),
                    "created_at": fam.created_at.isoformat(),
                    "deleted_at": (
                        fam.deleted_at.isoformat() if fam.deleted_at else None
                    ),
                    "last_seen_at": (
                        last.isoformat() if last else None
                    ),
                    "join_code": fam.join_code,
                }
                for fam, plan_name, sub_status, member_count, last in rows
            ],
        }
```

- [ ] **Step 4: Write the route**

Create `backend/app/api/routes/admin/families.py`:

```python
"""Per-family operator reads."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_lookup_service import AdminLookupService

router = APIRouter()


@router.get("/families")
async def list_families(
    q: Optional[str] = Query(None, description="name, join code, id, or member email"),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Family directory with search."""
    return await AdminLookupService.search_families(
        db, q=q, include_deleted=include_deleted, limit=limit, offset=offset
    )
```

Register it in `backend/app/api/routes/admin/__init__.py`:

```python
from app.api.routes.admin import families  # noqa: E402

router.include_router(families.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -v`

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/admin/admin_lookup_service.py \
  backend/app/api/routes/admin/families.py \
  backend/app/api/routes/admin/__init__.py backend/tests/test_admin_reads.py
git commit -m "feat(admin): family directory with search"
```

---

## Task 6: Family detail read

**Files:**
- Modify: `backend/app/services/admin/admin_read_service.py`
- Modify: `backend/app/api/routes/admin/families.py`
- Test: `backend/tests/test_admin_reads.py`, `backend/tests/test_admin_authz.py`

**Interfaces:**
- Consumes: `AdminReadService` (Task 4).
- Produces: `AdminReadService.family_detail(db, family_id: UUID) -> dict` with keys `overview`, `members`, `economy`, `tasks`, `budget`, `billing`, `integrations`; `GET /api/admin/families/{family_id}`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_reads.py`:

```python
@pytest.mark.asyncio
async def test_family_detail_returns_all_tabs(
    client, superadmin_headers, test_family, test_parent_user, test_child_user
):
    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=superadmin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {
        "overview",
        "members",
        "economy",
        "tasks",
        "budget",
        "billing",
        "integrations",
    }
    assert body["overview"]["name"] == "Test Family"
    # enabled_modules is NULL on a fresh family, which means ALL modules on.
    assert body["overview"]["enabled_modules"] is None
    emails = {m["email"] for m in body["members"]}
    assert {"parent@test.com", "child@test.com"} <= emails


@pytest.mark.asyncio
async def test_family_detail_members_report_uppercase_enum_roles(
    client, superadmin_headers, test_family, test_parent_user
):
    """Regression guard: users.role is a PG enum storing 'PARENT'. A query
    comparing to the lowercase Python value silently returns nothing."""
    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=superadmin_headers
    )
    roles = {m["role"] for m in resp.json()["members"]}
    assert "parent" in roles


@pytest.mark.asyncio
async def test_family_detail_404_for_unknown_family(client, superadmin_headers):
    from uuid import uuid4

    resp = await client.get(
        f"/api/admin/families/{uuid4()}", headers=superadmin_headers
    )
    assert resp.status_code == 404
```

Append to `backend/tests/test_admin_authz.py`:

```python
@pytest.mark.asyncio
async def test_family_detail_never_leaks_other_family_members(
    client, db_session, superadmin_headers, test_family
):
    """The operator asks for family A and gets ONLY family A."""
    from app.core.security import get_password_hash
    from app.models.family import Family
    from app.models.user import User, UserRole

    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    db_session.add(
        User(
            email="outsider@test.com",
            password_hash=get_password_hash("password123"),
            name="Outsider",
            role=UserRole.PARENT,
            family_id=other.id,
            email_verified=True,
        )
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=superadmin_headers
    )
    emails = {m["email"] for m in resp.json()["members"]}
    assert "outsider@test.com" not in emails


@pytest.mark.asyncio
async def test_family_detail_rejects_parent_of_that_family(
    client, auth_headers, test_family, allowlist_superadmin
):
    """A parent cannot read their OWN family through the admin surface."""
    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=auth_headers
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py tests/test_admin_authz.py -v`

Expected: the new tests fail with 404 (route missing).

- [ ] **Step 3: Add `family_detail` to the read service**

Append to `backend/app/services/admin/admin_read_service.py` (extend the imports first):

```python
from uuid import UUID

from fastapi import HTTPException, status

from app.models.budget import BudgetAccount, BudgetTransaction
from app.models.cash_transaction import CashTransaction
from app.models.a2a import FamilyA2AWebhook
```

```python
    @staticmethod
    async def family_detail(db: AsyncSession, family_id: UUID) -> dict:
        """Everything the support console shows for one family.

        Metadata only — no message bodies, no images, no chat, no DMs. Those
        wait for the moderation phase, which owns the redaction and consent
        design.
        """
        family = await db.scalar(select(Family).where(Family.id == family_id))
        if family is None:
            # 404 here is indistinguishable from the 404 a non-operator gets,
            # which is the point.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
            )

        members = (
            await db.execute(
                select(User)
                .where(User.family_id == family_id)
                .order_by(User.created_at.asc())
            )
        ).scalars().all()

        assignment_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.status, func.count())
                    .where(TaskAssignment.family_id == family_id)
                    .group_by(TaskAssignment.status)
                )
            ).all()
        )

        account_count = await db.scalar(
            select(func.count())
            .select_from(BudgetAccount)
            .where(
                BudgetAccount.family_id == family_id,
                BudgetAccount.deleted_at.is_(None),
            )
        )
        transaction_count = await db.scalar(
            select(func.count())
            .select_from(BudgetTransaction)
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
        drafts_pending = await db.scalar(
            select(func.count())
            .select_from(BudgetReceiptDraft)
            .where(
                BudgetReceiptDraft.family_id == family_id,
                BudgetReceiptDraft.status == "pending",
            )
        )

        sub_row = (
            await db.execute(
                select(FamilySubscription, SubscriptionPlan)
                .outerjoin(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .where(FamilySubscription.family_id == family_id)
            )
        ).first()

        webhook = await db.scalar(
            select(FamilyA2AWebhook).where(
                FamilyA2AWebhook.family_id == family_id
            )
        )
        deliveries = dict(
            (
                await db.execute(
                    select(A2AWebhookDelivery.status, func.count())
                    .where(A2AWebhookDelivery.family_id == family_id)
                    .group_by(A2AWebhookDelivery.status)
                )
            ).all()
        )

        recent_cash = (
            await db.execute(
                select(CashTransaction)
                .where(CashTransaction.family_id == family_id)
                .order_by(CashTransaction.created_at.desc())
                .limit(20)
            )
        ).scalars().all()

        return {
            "overview": {
                "id": str(family.id),
                "name": family.name,
                "timezone": family.timezone,
                "is_active": family.is_active,
                "created_at": family.created_at.isoformat(),
                "deleted_at": (
                    family.deleted_at.isoformat() if family.deleted_at else None
                ),
                "purge_after": (
                    (family.deleted_at + timedelta(days=30)).isoformat()
                    if family.deleted_at
                    else None
                ),
                "join_code": family.join_code,
                "referral_code": family.referral_code,
                "referral_bonus_until": (
                    family.referral_bonus_until.isoformat()
                    if family.referral_bonus_until
                    else None
                ),
                # NULL means ALL modules on, not none. Rendered verbatim so
                # the UI can say so explicitly rather than showing "0 modules".
                "enabled_modules": family.enabled_modules,
                "point_value_cents": family.point_value_cents,
                "gig_term": family.gig_term,
                "ai_processing_consent": family.ai_processing_consent,
                "ai_processing_consent_at": (
                    family.ai_processing_consent_at.isoformat()
                    if family.ai_processing_consent_at
                    else None
                ),
                "onboarding": {
                    "child_invited": family.onboarding_child_invited,
                    "task_created": family.onboarding_task_created,
                    "reward_created": family.onboarding_reward_created,
                    "points_awarded": family.onboarding_points_awarded,
                    "dismissed": family.onboarding_dismissed,
                },
            },
            "members": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "name": u.name,
                    "role": u.role.value,
                    "is_active": u.is_active,
                    "email_verified": u.email_verified,
                    "approval_status": u.approval_status,
                    "oauth_provider": u.oauth_provider,
                    "points": u.points,
                    "cash_cents": u.cash_cents,
                    "last_seen_at": (
                        u.last_seen_at.isoformat() if u.last_seen_at else None
                    ),
                    "created_at": u.created_at.isoformat(),
                    "deleted_at": (
                        u.deleted_at.isoformat() if u.deleted_at else None
                    ),
                }
                for u in members
            ],
            "economy": {
                "recent_cash_transactions": [
                    {
                        "id": str(tx.id),
                        "user_id": str(tx.user_id),
                        "type": tx.type.value,
                        "amount_cents": tx.amount_cents,
                        "balance_after": tx.balance_after,
                        "jar": tx.jar,
                        "week_of": tx.week_of.isoformat() if tx.week_of else None,
                        "created_at": tx.created_at.isoformat(),
                    }
                    for tx in recent_cash
                ],
            },
            "tasks": {
                "by_status": {
                    s.value if hasattr(s, "value") else str(s): int(n)
                    for s, n in assignment_counts.items()
                },
            },
            "budget": {
                "account_count": int(account_count or 0),
                "transaction_count": int(transaction_count or 0),
                "receipt_drafts_pending": int(drafts_pending or 0),
            },
            "billing": (
                {
                    "plan": sub_row[1].name if sub_row[1] else None,
                    "currency": sub_row[1].currency if sub_row[1] else None,
                    "status": sub_row[0].status,
                    "billing_cycle": sub_row[0].billing_cycle,
                    "paypal_subscription_id": sub_row[0].paypal_subscription_id,
                    "current_period_end": (
                        sub_row[0].current_period_end.isoformat()
                        if sub_row[0].current_period_end
                        else None
                    ),
                    "cancel_at_period_end": sub_row[0].cancel_at_period_end,
                    "payment_failure_at": (
                        sub_row[0].payment_failure_at.isoformat()
                        if sub_row[0].payment_failure_at
                        else None
                    ),
                    "needs_review": sub_row[0].needs_review,
                    "review_reason": sub_row[0].review_reason,
                }
                if sub_row
                else None
            ),
            "integrations": {
                "a2a_webhook": (
                    {
                        "enabled": webhook.enabled,
                        "failure_count": webhook.failure_count,
                        "last_success_at": (
                            webhook.last_success_at.isoformat()
                            if webhook.last_success_at
                            else None
                        ),
                        "last_error": webhook.last_error,
                    }
                    if webhook
                    else None
                ),
                "deliveries_by_status": {
                    k: int(v) for k, v in deliveries.items()
                },
            },
        }
```

Add `timedelta` to the datetime import at the top of the file:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Add the route**

Append to `backend/app/api/routes/admin/families.py` (add `from uuid import UUID` and the read-service import):

```python
@router.get("/families/{family_id}")
async def family_detail(
    family_id: UUID,
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full support view of one family. Metadata only — never content."""
    return await AdminReadService.family_detail(db, family_id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py tests/test_admin_authz.py -v`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/admin/admin_read_service.py \
  backend/app/api/routes/admin/families.py \
  backend/tests/test_admin_reads.py backend/tests/test_admin_authz.py
git commit -m "feat(admin): per-family support detail view"
```

---

## Task 7: Billing-review, deletions, and audit-log reads

**Files:**
- Modify: `backend/app/services/admin/admin_read_service.py`
- Modify: `backend/app/api/routes/admin/overview.py`
- Test: `backend/tests/test_admin_reads.py`

**Interfaces:**
- Consumes: `AdminReadService` (Tasks 4, 6), `OperatorAuditLog` (Task 2).
- Produces: `AdminReadService.billing_review_queue(db) -> list[dict]`; `AdminReadService.pending_purge_queue(db) -> list[dict]`; `AdminReadService.audit_log(db, *, family_id=None, action=None, limit=100, offset=0) -> dict`; routes `GET /api/admin/billing-review`, `GET /api/admin/deletions`, `GET /api/admin/audit`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_reads.py`:

```python
@pytest.mark.asyncio
async def test_billing_review_queue_lists_flagged_subscriptions(
    client, db_session, superadmin_headers, test_family
):
    from app.models.subscription import FamilySubscription, SubscriptionPlan

    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        currency="USD",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={},
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)

    db_session.add(
        FamilySubscription(
            family_id=test_family.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            status="active",
            paypal_subscription_id="I-TEST",
            needs_review=True,
            review_reason="refund received",
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/admin/billing-review", headers=superadmin_headers
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["review_reason"] == "refund received"
    assert rows[0]["family_name"] == "Test Family"


@pytest.mark.asyncio
async def test_deletions_queue_shows_purge_date(
    client, db_session, superadmin_headers
):
    from app.models.family import Family

    closed_at = datetime.now(timezone.utc)
    db_session.add(Family(name="Closing", deleted_at=closed_at))
    await db_session.commit()

    resp = await client.get("/api/admin/deletions", headers=superadmin_headers)
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Closing"
    assert rows[0]["purge_after"] is not None


@pytest.mark.asyncio
async def test_audit_log_read_is_filterable(
    client, db_session, superadmin_headers, test_superadmin_user, test_family
):
    from app.services.admin.operator_audit_service import OperatorAuditService

    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="family.suspend",
        target_family_id=test_family.id,
    )
    OperatorAuditService.record(
        db_session, actor=test_superadmin_user, action="user.password_reset"
    )
    await db_session.commit()

    resp = await client.get("/api/admin/audit", headers=superadmin_headers)
    assert resp.json()["total"] == 2

    resp = await client.get(
        "/api/admin/audit?action=family.suspend", headers=superadmin_headers
    )
    assert resp.json()["total"] == 1

    resp = await client.get(
        f"/api/admin/audit?family_id={test_family.id}",
        headers=superadmin_headers,
    )
    assert resp.json()["total"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -k "billing_review or deletions or audit_log" -v`

Expected: FAIL — 404, routes missing.

- [ ] **Step 3: Add the read methods**

Append to `backend/app/services/admin/admin_read_service.py` (import `OperatorAuditLog` at the top):

```python
    @staticmethod
    async def billing_review_queue(db: AsyncSession) -> list[dict]:
        """Subscriptions a webhook refused to act on automatically.

        Written by subscription_state.mark_for_review — refunds, reversals,
        and the failed-cancel case that risks double billing. The highest
        signal-to-effort queue in the app.
        """
        rows = (
            await db.execute(
                select(FamilySubscription, SubscriptionPlan, Family)
                .outerjoin(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .join(Family, FamilySubscription.family_id == Family.id)
                .where(FamilySubscription.needs_review.is_(True))
                .order_by(FamilySubscription.updated_at.desc())
            )
        ).all()
        return [
            {
                "family_id": str(fam.id),
                "family_name": fam.name,
                "plan": plan.name if plan else None,
                "status": sub.status,
                "paypal_subscription_id": sub.paypal_subscription_id,
                "review_reason": sub.review_reason,
                "updated_at": sub.updated_at.isoformat(),
            }
            for sub, plan, fam in rows
        ]

    @staticmethod
    async def pending_purge_queue(db: AsyncSession) -> list[dict]:
        """Families inside the 30-day recovery window, oldest first."""
        member_counts = (
            select(User.family_id, func.count().label("n"))
            .group_by(User.family_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(Family, member_counts.c.n)
                .outerjoin(member_counts, member_counts.c.family_id == Family.id)
                .where(Family.deleted_at.is_not(None))
                .order_by(Family.deleted_at.asc())
            )
        ).all()
        return [
            {
                "id": str(fam.id),
                "name": fam.name,
                "deleted_at": fam.deleted_at.isoformat(),
                "purge_after": (fam.deleted_at + timedelta(days=30)).isoformat(),
                "member_count": int(n or 0),
            }
            for fam, n in rows
        ]

    @staticmethod
    async def audit_log(
        db: AsyncSession,
        *,
        family_id: UUID | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Operator audit trail, newest first."""
        conditions = []
        if family_id is not None:
            conditions.append(OperatorAuditLog.target_family_id == family_id)
        if action:
            conditions.append(OperatorAuditLog.action == action)

        total = await db.scalar(
            select(func.count()).select_from(OperatorAuditLog).where(*conditions)
        )
        rows = (
            await db.execute(
                select(OperatorAuditLog)
                .where(*conditions)
                .order_by(OperatorAuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(r.id),
                    "actor_email": r.actor_email,
                    "action": r.action,
                    "target_family_id": (
                        str(r.target_family_id) if r.target_family_id else None
                    ),
                    "target_user_id": (
                        str(r.target_user_id) if r.target_user_id else None
                    ),
                    "params": r.params,
                    "result": r.result,
                    "error": r.error,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }
```

- [ ] **Step 4: Add the routes**

Append to `backend/app/api/routes/admin/overview.py` (add `from typing import Optional`, `from uuid import UUID`, `from fastapi import Query`):

```python
@router.get("/billing-review")
async def billing_review(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Subscriptions flagged for human review by the PayPal webhook."""
    return await AdminReadService.billing_review_queue(db)


@router.get("/deletions")
async def pending_deletions(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Families inside the 30-day recovery window."""
    return await AdminReadService.pending_purge_queue(db)


@router.get("/audit")
async def audit_log(
    family_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Operator audit trail."""
    return await AdminReadService.audit_log(
        db, family_id=family_id, action=action, limit=limit, offset=offset
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -v`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/admin/admin_read_service.py \
  backend/app/api/routes/admin/overview.py backend/tests/test_admin_reads.py
git commit -m "feat(admin): billing-review, deletions, and audit-log reads"
```

---

## Task 8: Make `families.is_active` a real suspension

**Files:**
- Modify: `backend/app/services/auth_service.py:416-419`
- Modify: `backend/app/core/dependencies.py:40-55`
- Test: `backend/tests/test_family_suspension.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: suspended families are rejected by `authenticate_user` and `get_current_user`. Both raise 401 with `detail="Family suspended"` so the frontend can distinguish it from an ordinary auth failure.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_family_suspension.py`:

```python
"""families.is_active must actually lock a family out.

Before this change is_active was enforced in exactly two places (join-code
lookup and registration), so a "suspended" family kept using the entire app.
"""

import pytest


@pytest.mark.asyncio
async def test_suspended_family_cannot_log_in(
    client, db_session, test_family, test_parent_user
):
    test_family.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_existing_token_stops_working_once_family_suspended(
    client, db_session, auth_headers, test_family
):
    ok = await client.get("/api/auth/me", headers=auth_headers)
    assert ok.status_code == 200

    test_family.is_active = False
    await db_session.commit()

    blocked = await client.get("/api/auth/me", headers=auth_headers)
    assert blocked.status_code == 401


@pytest.mark.asyncio
async def test_unsuspending_restores_access(
    client, db_session, auth_headers, test_family
):
    test_family.is_active = False
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401

    test_family.is_active = True
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_family_suspension.py -v`

Expected: all three FAIL with 200 where 401 is expected.

- [ ] **Step 3: Enforce it in `get_current_user`**

In `backend/app/core/dependencies.py`, insert immediately after the `deleted_at` check (line 53), before `await _touch_last_seen(...)`:

```python
    # Operator suspension. families.is_active was previously checked only at
    # join-code lookup and registration, which meant a "suspended" family kept
    # full access to the app. A valid access token must stop working the
    # moment an operator suspends the family.
    family_active = await db.scalar(
        select(Family.is_active).where(Family.id == user.family_id)
    )
    if family_active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Family suspended",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

Add the import at line 11:

```python
from app.models.family import Family
```

- [ ] **Step 4: Enforce it in `authenticate_user`**

In `backend/app/services/auth_service.py`, insert immediately after the `deleted_at` check (line 423):

```python
        # Operator suspension: the family is locked out as a whole. Same 401
        # as a deactivated account — deliberately indistinguishable to an
        # attacker probing for valid emails.
        family_active = await db.scalar(
            select(Family.is_active).where(Family.id == user.family_id)
        )
        if family_active is False:
            raise UnauthorizedException("Family suspended")
```

Confirm `Family` is imported in that module; if not, add `from app.models.family import Family`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_family_suspension.py -v`

Expected: 3 passed.

- [ ] **Step 6: Run the full suite — this touches the hot auth path**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q`

Expected: the full suite stays green. `Family.is_active` defaults to `True`, so no existing fixture is affected.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/dependencies.py backend/app/services/auth_service.py \
  backend/tests/test_family_suspension.py
git commit -m "fix(auth): enforce families.is_active on login and every request"
```

---

## Task 9: Operator actions — account and family

**Files:**
- Create: `backend/app/services/admin/admin_action_service.py`
- Create: `backend/app/api/routes/admin/actions.py`
- Modify: `backend/app/api/routes/admin/__init__.py`
- Test: `backend/tests/test_admin_actions.py`

**Interfaces:**
- Consumes: `OperatorAuditService.record` (Task 2), `require_superadmin` (Task 1).
- Produces: `AdminActionService` with `resend_verification`, `trigger_password_reset`, `comp_plus_month`, `set_modules`, `set_family_active`, `set_user_active`. All are `@staticmethod async def …(db, *, operator: User, …) -> dict` and all commit. Routes: `POST /api/admin/families/{family_id}/actions/{action}` is **not** used — each action gets its own explicit route, listed below.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_actions.py`:

```python
@pytest.mark.asyncio
async def test_comp_plus_month_extends_referral_bonus_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "goodwill"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert test_family.referral_bonus_until is not None

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.comp_plus"
            )
        )
    ).scalar_one()
    assert row.target_family_id == test_family.id
    assert row.params["days"] == 30
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_comp_plus_month_sets_absolute_expiry_not_stacked(
    client, db_session, superadmin_headers, test_family
):
    """Two comps of 30 days must not silently become 60.

    ReferralService._grant_referral_month stacks +30d per call; the operator
    action deliberately does NOT use it and writes an absolute expiry.
    """
    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "one"},
        headers=superadmin_headers,
    )
    await db_session.refresh(test_family)
    first = test_family.referral_bonus_until

    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "two"},
        headers=superadmin_headers,
    )
    await db_session.refresh(test_family)
    delta = abs((test_family.referral_bonus_until - first).total_seconds())
    assert delta < 5


@pytest.mark.asyncio
async def test_suspend_family_sets_is_active_false_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/suspend",
        json={"suspended": True, "reason": "abuse report"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert test_family.is_active is False

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.suspend"
            )
        )
    ).scalar_one()
    assert row.params["reason"] == "abuse report"


@pytest.mark.asyncio
async def test_set_modules_persists_registry_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/modules",
        json={"enabled_modules": ["budget", "chat"], "reason": "support"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert set(test_family.enabled_modules) == {"budget", "chat"}


@pytest.mark.asyncio
async def test_password_reset_bumps_token_version(
    client, db_session, superadmin_headers, test_parent_user, monkeypatch
):
    """The EmailService helper does NOT bump token_version — the public route
    does. An operator reset that skipped it would leave sessions alive."""
    from app.services.email_service import EmailService

    async def _fake_send(db, user, base_url=""):
        return True

    monkeypatch.setattr(
        EmailService, "send_password_reset_email", staticmethod(_fake_send)
    )
    before = test_parent_user.token_version

    resp = await client.post(
        f"/api/admin/users/{test_parent_user.id}/password-reset",
        json={"reason": "user locked out"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_parent_user)
    assert test_parent_user.token_version == before + 1


@pytest.mark.asyncio
async def test_failed_action_writes_error_audit_row(
    client, db_session, superadmin_headers, test_parent_user, monkeypatch
):
    from app.services.email_service import EmailService

    async def _boom(db, user, base_url=""):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        EmailService, "send_verification_email", staticmethod(_boom)
    )
    resp = await client.post(
        f"/api/admin/users/{test_parent_user.id}/resend-verification",
        json={"reason": "never arrived"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 502

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "user.resend_verification"
            )
        )
    ).scalar_one()
    assert row.result == "error"
    assert "smtp down" in row.error


@pytest.mark.asyncio
async def test_deactivate_user_audits_and_flags_asymmetry(
    client, db_session, superadmin_headers, test_child_user
):
    resp = await client.post(
        f"/api/admin/users/{test_child_user.id}/active",
        json={"active": False, "reason": "parent request"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["warning"]
    await db_session.refresh(test_child_user)
    assert test_child_user.is_active is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -v`

Expected: the new tests FAIL with 404.

- [ ] **Step 3: Write the action service**

Create `backend/app/services/admin/admin_action_service.py`:

```python
"""The bounded set of write actions an operator may perform.

Every method reuses an existing service rather than writing raw SQL, commits
exactly once, and stages its audit row on the same transaction as the
mutation — so a rolled-back action cannot leave an "ok" audit row and a
committed one cannot go unrecorded.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.modules import TOGGLABLE_MODULES
from app.models.family import Family
from app.models.user import User
from app.services.admin.operator_audit_service import OperatorAuditService
from app.services.email_service import EmailService

# Deactivating a user also bulk-cancels their PENDING/CLAIMED/OVERDUE
# assignments; reactivating does NOT restore them. Surfaced to the operator
# rather than hidden, because the support case usually cares.
DEACTIVATE_WARNING = (
    "Deactivating also cancels this user's pending, claimed and overdue "
    "assignments. Reactivating does not restore them."
)


async def _load_family(db: AsyncSession, family_id: UUID) -> Family:
    family = await db.scalar(select(Family).where(Family.id == family_id))
    if family is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return family


async def _load_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


class AdminActionService:
    """Operator write actions."""

    @staticmethod
    async def comp_plus_month(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        days: int,
        reason: str,
    ) -> dict:
        """Grant free Plus for ``days`` from now.

        Writes families.referral_bonus_until directly and ABSOLUTELY, rather
        than calling ReferralService._grant_referral_month — that helper is
        private, does not commit, stacks +30d per invocation, and is Plus-only.
        An operator comp must be idempotent in intent: "Plus until date X".
        """
        family = await _load_family(db, family_id)
        until = datetime.now(timezone.utc) + timedelta(days=days)
        family.referral_bonus_until = until
        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.comp_plus",
            target_family_id=family_id,
            params={"days": days, "reason": reason, "until": until.isoformat()},
        )
        await db.commit()
        return {"referral_bonus_until": until.isoformat()}

    @staticmethod
    async def set_family_active(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        suspended: bool,
        reason: str,
    ) -> dict:
        """Suspend or reinstate a whole family.

        Deliberately NOT implemented via the soft-delete tombstone: that would
        conflate abuse suspension with account closure and arm the 30-day
        purge sweep against a family the operator may want to reinstate.
        """
        family = await _load_family(db, family_id)
        family.is_active = not suspended
        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.suspend" if suspended else "family.unsuspend",
            target_family_id=family_id,
            params={"reason": reason},
        )
        await db.commit()
        return {"is_active": family.is_active}

    @staticmethod
    async def set_modules(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        enabled_modules: Optional[list[str]],
        reason: str,
    ) -> dict:
        """Rewrite a family's module registry.

        ``None`` restores the default, which means ALL modules on — not none.
        """
        if enabled_modules is not None:
            unknown = set(enabled_modules) - set(TOGGLABLE_MODULES)
            if unknown:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"unknown modules: {sorted(unknown)}",
                )
        family = await _load_family(db, family_id)
        family.enabled_modules = enabled_modules
        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.set_modules",
            target_family_id=family_id,
            params={"enabled_modules": enabled_modules, "reason": reason},
        )
        await db.commit()
        return {"enabled_modules": enabled_modules}

    @staticmethod
    async def set_user_active(
        db: AsyncSession,
        *,
        operator: User,
        user_id: UUID,
        active: bool,
        reason: str,
    ) -> dict:
        """Deactivate or reactivate one member, via AuthService."""
        from app.services.auth_service import AuthService

        user = await _load_user(db, user_id)
        if active:
            await AuthService.activate_user(db, user.id)
        else:
            await AuthService.deactivate_user(db, user.id)
        OperatorAuditService.record(
            db,
            actor=operator,
            action="user.activate" if active else "user.deactivate",
            target_family_id=user.family_id,
            target_user_id=user.id,
            params={"reason": reason},
        )
        await db.commit()
        return {
            "is_active": active,
            "warning": None if active else DEACTIVATE_WARNING,
        }

    @staticmethod
    async def resend_verification(
        db: AsyncSession, *, operator: User, user_id: UUID, reason: str
    ) -> dict:
        """Send a fresh email-verification link."""
        user = await _load_user(db, user_id)
        try:
            sent = await EmailService.send_verification_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="user.resend_verification",
                target_family_id=user.family_id,
                target_user_id=user.id,
                params={"reason": reason},
                result="error",
                error=str(exc),
            )
            await db.commit()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"email send failed: {exc}"
            ) from exc

        OperatorAuditService.record(
            db,
            actor=operator,
            action="user.resend_verification",
            target_family_id=user.family_id,
            target_user_id=user.id,
            params={"reason": reason},
            result="ok" if sent else "error",
            error=None if sent else "email provider returned false",
        )
        await db.commit()
        return {"sent": bool(sent)}

    @staticmethod
    async def trigger_password_reset(
        db: AsyncSession, *, operator: User, user_id: UUID, reason: str
    ) -> dict:
        """Send a reset link AND invalidate outstanding sessions.

        EmailService.send_password_reset_email does not bump token_version —
        the public route does. An operator reset that skipped the bump would
        leave a compromised session alive, which is usually the whole reason
        support is resetting the password.
        """
        user = await _load_user(db, user_id)
        try:
            sent = await EmailService.send_password_reset_email(
                db, user, base_url=settings.email_link_base
            )
        except Exception as exc:
            OperatorAuditService.record(
                db,
                actor=operator,
                action="user.password_reset",
                target_family_id=user.family_id,
                target_user_id=user.id,
                params={"reason": reason},
                result="error",
                error=str(exc),
            )
            await db.commit()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"email send failed: {exc}"
            ) from exc

        user.token_version = (user.token_version or 0) + 1
        OperatorAuditService.record(
            db,
            actor=operator,
            action="user.password_reset",
            target_family_id=user.family_id,
            target_user_id=user.id,
            params={"reason": reason},
            result="ok" if sent else "error",
            error=None if sent else "email provider returned false",
        )
        await db.commit()
        return {"sent": bool(sent), "sessions_invalidated": True}
```

- [ ] **Step 4: Write the routes**

Create `backend/app/api/routes/admin/actions.py`:

```python
"""Operator write actions. Every route audits."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_action_service import AdminActionService

router = APIRouter()


class ReasonRequest(BaseModel):
    """Every operator action carries an operator-written reason."""

    reason: str = Field(..., min_length=3, max_length=500)


class CompPlusRequest(ReasonRequest):
    days: int = Field(30, ge=1, le=365)


class SuspendRequest(ReasonRequest):
    suspended: bool


class ModulesRequest(ReasonRequest):
    # None restores the default registry, which means ALL modules on.
    enabled_modules: Optional[list[str]] = None


class ActiveRequest(ReasonRequest):
    active: bool


@router.post("/families/{family_id}/comp-plus")
async def comp_plus(
    family_id: UUID,
    body: CompPlusRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant free Plus until now + days (absolute, not stacked)."""
    return await AdminActionService.comp_plus_month(
        db,
        operator=operator,
        family_id=family_id,
        days=body.days,
        reason=body.reason,
    )


@router.post("/families/{family_id}/suspend")
async def suspend_family(
    family_id: UUID,
    body: SuspendRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lock a family out of the app, or reinstate it."""
    return await AdminActionService.set_family_active(
        db,
        operator=operator,
        family_id=family_id,
        suspended=body.suspended,
        reason=body.reason,
    )


@router.post("/families/{family_id}/modules")
async def set_modules(
    family_id: UUID,
    body: ModulesRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rewrite the family's module registry."""
    return await AdminActionService.set_modules(
        db,
        operator=operator,
        family_id=family_id,
        enabled_modules=body.enabled_modules,
        reason=body.reason,
    )


@router.post("/users/{user_id}/active")
async def set_user_active(
    user_id: UUID,
    body: ActiveRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deactivate or reactivate one member."""
    return await AdminActionService.set_user_active(
        db,
        operator=operator,
        user_id=user_id,
        active=body.active,
        reason=body.reason,
    )


@router.post("/users/{user_id}/resend-verification")
async def resend_verification(
    user_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a fresh verification link."""
    return await AdminActionService.resend_verification(
        db, operator=operator, user_id=user_id, reason=body.reason
    )


@router.post("/users/{user_id}/password-reset")
async def password_reset(
    user_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a reset link and invalidate outstanding sessions."""
    return await AdminActionService.trigger_password_reset(
        db, operator=operator, user_id=user_id, reason=body.reason
    )
```

Register in `backend/app/api/routes/admin/__init__.py`:

```python
from app.api.routes.admin import actions  # noqa: E402

router.include_router(actions.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -v`

Expected: all pass.

- [ ] **Step 6: Add these routes to the authorization matrix**

Append to `backend/tests/test_admin_authz.py`:

```python
@pytest.mark.asyncio
async def test_every_action_route_404s_for_non_operator(
    client, auth_headers, test_family, test_parent_user, allowlist_superadmin
):
    """A parent must not reach ANY operator action, on their own family or
    anyone else's."""
    fid, uid = test_family.id, test_parent_user.id
    calls = [
        (f"/api/admin/families/{fid}/comp-plus", {"reason": "x", "days": 30}),
        (f"/api/admin/families/{fid}/suspend", {"reason": "x", "suspended": True}),
        (f"/api/admin/families/{fid}/modules", {"reason": "x"}),
        (f"/api/admin/users/{uid}/active", {"reason": "x", "active": False}),
        (f"/api/admin/users/{uid}/resend-verification", {"reason": "x"}),
        (f"/api/admin/users/{uid}/password-reset", {"reason": "x"}),
    ]
    for path, body in calls:
        resp = await client.post(path, json=body, headers=auth_headers)
        assert resp.status_code == 404, path
```

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_authz.py -v`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/admin/admin_action_service.py \
  backend/app/api/routes/admin/actions.py \
  backend/app/api/routes/admin/__init__.py \
  backend/tests/test_admin_actions.py backend/tests/test_admin_authz.py
git commit -m "feat(admin): account and family operator actions"
```

---

## Task 10: Operator actions — economy, tasks, budget, deletion cancel

**Files:**
- Modify: `backend/app/services/admin/admin_action_service.py`
- Modify: `backend/app/api/routes/admin/actions.py`
- Modify: `backend/app/services/family_deletion_service.py`
- Test: `backend/tests/test_admin_actions.py`

**Interfaces:**
- Consumes: `AdminActionService` (Task 9).
- Produces: `AdminActionService.release_paycheck`, `undo_chore_approval`, `restore_recycled`, `cancel_deletion`; `FamilyDeletionService.cancel_deletion(db, *, family_id: UUID) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_actions.py`:

```python
@pytest.mark.asyncio
async def test_cancel_deletion_clears_tombstones_and_audits(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    now = datetime.now(timezone.utc)
    test_family.deleted_at = now
    test_parent_user.deleted_at = now
    await db_session.commit()

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "closed by mistake"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["billing_restored"] is False

    await db_session.refresh(test_family)
    await db_session.refresh(test_parent_user)
    assert test_family.deleted_at is None
    assert test_parent_user.deleted_at is None

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.cancel_deletion"
            )
        )
    ).scalar_one()
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_cancel_deletion_refuses_past_retention_window(
    client, db_session, superadmin_headers, test_family
):
    test_family.deleted_at = datetime.now(timezone.utc) - timedelta(days=45)
    await db_session.commit()

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "too late"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_deletion_on_live_family_is_a_noop_409(
    client, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "nothing to undo"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_undo_chore_approval_rejects_bonus_assignment(
    client, db_session, superadmin_headers, test_family, test_child_user,
    gig_template_factory,
):
    """patch_assignment refuses bonus/gig reversals. The operator route must
    surface that refusal rather than fail opaquely."""
    from app.models.task_assignment import AssignmentStatus, TaskAssignment

    template = await gig_template_factory()
    assignment = TaskAssignment(
        template_id=template.id,
        family_id=test_family.id,
        assigned_to=test_child_user.id,
        status=AssignmentStatus.COMPLETED,
    )
    db_session.add(assignment)
    await db_session.commit()
    await db_session.refresh(assignment)

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/assignments/{assignment.id}/undo-approval",
        json={"reason": "approved by mistake"},
        headers=superadmin_headers,
    )
    assert resp.status_code in (400, 422)
    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "assignment.undo_approval"
            )
        )
    ).scalar_one()
    assert row.result == "error"
```

Add `from datetime import datetime, timedelta, timezone` to the imports at the top of `test_admin_actions.py`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -k "cancel_deletion or undo_chore" -v`

Expected: FAIL — 404, routes missing.

- [ ] **Step 3: Add `cancel_deletion` to `FamilyDeletionService`**

Append to `backend/app/services/family_deletion_service.py`, inside `FamilyDeletionService`:

```python
    @classmethod
    async def cancel_deletion(cls, db: AsyncSession, *, family_id: UUID) -> dict:
        """Undo a soft delete, inside the retention window.

        The 30-day recovery window has been documented since the deletion
        feature shipped, but nothing anywhere cleared deleted_at — this is
        that missing half.

        Billing is NOT restored: delete_family cancels the family's PayPal
        subscription at soft-delete time, and there is no API to un-cancel it.
        A reinstated family must re-subscribe. The caller must say so.
        """
        family = await FamilyService.get_family(db, family_id)
        if family.deleted_at is None:
            raise HTTPException(
                status_code=409, detail="family is not pending deletion"
            )

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=cls.PURGE_RETENTION_DAYS
        )
        if family.deleted_at < cutoff:
            raise HTTPException(
                status_code=409,
                detail="retention window has expired; data may already be purged",
            )

        family.deleted_at = None
        # Mirror of the soft-delete statement: clear the denormalized tombstone
        # on every member. token_version is deliberately NOT rolled back —
        # deletion invalidated those refresh tokens and reinstating the family
        # must not resurrect them.
        await db.execute(
            update(User).where(User.family_id == family_id).values(deleted_at=None)
        )
        return {"family_id": str(family_id), "billing_restored": False}
```

Confirm `HTTPException`, `timedelta`, and `update` are imported in that module; add whichever are missing.

Note: this method does **not** commit — the caller (`AdminActionService`) commits so the audit row lands in the same transaction.

- [ ] **Step 4: Add the remaining actions to `AdminActionService`**

First extend the imports at the top of `backend/app/services/admin/admin_action_service.py`:

```python
from datetime import date, datetime, timedelta, timezone
```

Then append to the class:

```python
    @staticmethod
    async def cancel_deletion(
        db: AsyncSession, *, operator: User, family_id: UUID, reason: str
    ) -> dict:
        """Reinstate a family inside its 30-day recovery window."""
        from app.services.family_deletion_service import FamilyDeletionService

        try:
            result = await FamilyDeletionService.cancel_deletion(
                db, family_id=family_id
            )
        except HTTPException as exc:
            await db.rollback()
            OperatorAuditService.record(
                db,
                actor=operator,
                action="family.cancel_deletion",
                target_family_id=family_id,
                params={"reason": reason},
                result="error",
                error=str(exc.detail),
            )
            await db.commit()
            raise

        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.cancel_deletion",
            target_family_id=family_id,
            params={"reason": reason},
        )
        await db.commit()
        return result

    @staticmethod
    async def release_paycheck(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        kid_id: UUID,
        week_of: date,
        reason: str,
    ) -> dict:
        """Force-release a stuck chore paycheck for one kid and week.

        Idempotent per (kid, week) inside BankService. released_by carries the
        OPERATOR's id — cash_transactions.created_by is a nullable FK with
        ON DELETE SET NULL, so a cross-family actor is valid at the DB level
        and truthful in the ledger.
        """
        from app.services.bank_service import BankService

        kid = await _load_user(db, kid_id)
        if kid.family_id != family_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        try:
            result = await BankService.release_chore_paycheck(
                db,
                kid,
                family_id,
                week_of,
                entitled=True,
                released_by=operator.id,
            )
        except HTTPException as exc:
            await db.rollback()
            OperatorAuditService.record(
                db,
                actor=operator,
                action="bank.release_paycheck",
                target_family_id=family_id,
                target_user_id=kid_id,
                params={"week_of": week_of.isoformat(), "reason": reason},
                result="error",
                error=str(exc.detail),
            )
            await db.commit()
            raise

        OperatorAuditService.record(
            db,
            actor=operator,
            action="bank.release_paycheck",
            target_family_id=family_id,
            target_user_id=kid_id,
            params={"week_of": week_of.isoformat(), "reason": reason},
        )
        await db.commit()
        return result

    @staticmethod
    async def undo_chore_approval(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        assignment_id: UUID,
        reason: str,
    ) -> dict:
        """Revert a mistakenly-approved CHORE back to PENDING.

        TaskAssignmentService.patch_assignment claws the points back and
        clears the grade — which matters, because a leftover `partial` grade
        keeps haircutting the kid's payday math. It REFUSES bonus and gig
        reversals; that refusal is surfaced to the operator verbatim.
        """
        from app.models.task_assignment import AssignmentStatus
        from app.services.task_assignment_service import TaskAssignmentService

        try:
            assignment = await TaskAssignmentService.patch_assignment(
                db,
                assignment_id,
                family_id,
                status=AssignmentStatus.PENDING,
            )
        except HTTPException as exc:
            await db.rollback()
            OperatorAuditService.record(
                db,
                actor=operator,
                action="assignment.undo_approval",
                target_family_id=family_id,
                params={"assignment_id": str(assignment_id), "reason": reason},
                result="error",
                error=str(exc.detail),
            )
            await db.commit()
            raise

        OperatorAuditService.record(
            db,
            actor=operator,
            action="assignment.undo_approval",
            target_family_id=family_id,
            target_user_id=assignment.assigned_to,
            params={"assignment_id": str(assignment_id), "reason": reason},
        )
        await db.commit()
        return {"assignment_id": str(assignment_id), "status": "pending"}

    @staticmethod
    async def restore_recycled(
        db: AsyncSession,
        *,
        operator: User,
        family_id: UUID,
        item_type: str,
        item_id: UUID,
        reason: str,
    ) -> dict:
        """Restore one soft-deleted budget row from the recycle bin."""
        from app.services.budget.recycle_bin_service import RecycleBinService

        restorers = {
            "transaction": RecycleBinService.restore_transaction,
            "account": RecycleBinService.restore_account,
            "category": RecycleBinService.restore_category,
            "category_group": RecycleBinService.restore_category_group,
        }
        restore = restorers.get(item_type)
        if restore is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown item_type: {item_type}",
            )
        await restore(db, item_id, family_id)
        OperatorAuditService.record(
            db,
            actor=operator,
            action="budget.restore",
            target_family_id=family_id,
            params={
                "item_type": item_type,
                "item_id": str(item_id),
                "reason": reason,
            },
        )
        await db.commit()
        return {"restored": True, "item_type": item_type}
```

- [ ] **Step 5: Add the routes**

Append to `backend/app/api/routes/admin/actions.py` (add `from datetime import date`):

```python
class CancelDeletionRequest(ReasonRequest):
    pass


class ReleasePaycheckRequest(ReasonRequest):
    kid_id: UUID
    week_of: date


class RestoreRequest(ReasonRequest):
    item_type: str
    item_id: UUID


@router.post("/families/{family_id}/cancel-deletion")
async def cancel_deletion(
    family_id: UUID,
    body: CancelDeletionRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reinstate a family inside its 30-day recovery window.

    Billing is NOT restored — the PayPal subscription was cancelled at
    soft-delete time and the family must re-subscribe.
    """
    return await AdminActionService.cancel_deletion(
        db, operator=operator, family_id=family_id, reason=body.reason
    )


@router.post("/families/{family_id}/release-paycheck")
async def release_paycheck(
    family_id: UUID,
    body: ReleasePaycheckRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force-release a stuck chore paycheck. Idempotent per (kid, week)."""
    return await AdminActionService.release_paycheck(
        db,
        operator=operator,
        family_id=family_id,
        kid_id=body.kid_id,
        week_of=body.week_of,
        reason=body.reason,
    )


@router.post("/families/{family_id}/assignments/{assignment_id}/undo-approval")
async def undo_approval(
    family_id: UUID,
    assignment_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revert a mistakenly-approved chore. Refuses bonus and gig reversals."""
    return await AdminActionService.undo_chore_approval(
        db,
        operator=operator,
        family_id=family_id,
        assignment_id=assignment_id,
        reason=body.reason,
    )


@router.post("/families/{family_id}/restore")
async def restore_recycled(
    family_id: UUID,
    body: RestoreRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore one budget row from the family's recycle bin."""
    return await AdminActionService.restore_recycled(
        db,
        operator=operator,
        family_id=family_id,
        item_type=body.item_type,
        item_id=body.item_id,
        reason=body.reason,
    )
```

Also add a read endpoint so the UI can offer a paycheck preview before releasing — append to `backend/app/api/routes/admin/families.py`:

```python
@router.get("/families/{family_id}/paycheck-preview/{kid_id}")
async def paycheck_preview(
    family_id: UUID,
    kid_id: UUID,
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Side-effect-free projection + the kid's unreleased weeks.

    The operator must see this before releasing anything.
    """
    from fastapi import HTTPException, status as http_status

    from app.models.user import User as UserModel
    from app.services.bank_service import BankService

    kid = await db.scalar(select(UserModel).where(UserModel.id == kid_id))
    if kid is None or kid.family_id != family_id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Not Found")
    return {
        "preview": await BankService.chore_paycheck_preview(db, kid, family_id),
        "outstanding_weeks": await BankService.list_outstanding_weeks(
            db, kid, family_id
        ),
    }
```

Add `from sqlalchemy import select` to that file's imports.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_actions.py -v`

Expected: all pass.

- [ ] **Step 7: Run the whole backend suite and lint**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q
cd backend && ruff check app
```

Expected: green, no lint findings.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/admin/admin_action_service.py \
  backend/app/api/routes/admin/actions.py \
  backend/app/api/routes/admin/families.py \
  backend/app/services/family_deletion_service.py \
  backend/tests/test_admin_actions.py
git commit -m "feat(admin): economy, task, budget actions and deletion cancel"
```

---

## Task 11: Expose `is_superadmin` on `/auth/me` and guard `/admin` in middleware

**Files:**
- Modify: `backend/app/schemas/user.py:71`
- Modify: `backend/tests/test_admin_authz.py`
- Modify: `frontend/src/middleware.ts:335`
- Modify: `frontend/src/env.d.ts`

**Interfaces:**
- Consumes: `User.is_superadmin` (Task 1).
- Produces: `UserResponse.is_superadmin: bool`; middleware returns 404 for `/admin*` and `/api/admin/*` requests from non-operators.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_authz.py`:

```python
@pytest.mark.asyncio
async def test_auth_me_exposes_is_superadmin(
    client, superadmin_headers, auth_headers
):
    """The frontend middleware gates /admin on this field."""
    operator = await client.get("/api/auth/me", headers=superadmin_headers)
    assert operator.json()["is_superadmin"] is True

    parent = await client.get("/api/auth/me", headers=auth_headers)
    assert parent.json()["is_superadmin"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_authz.py -k is_superadmin -v`

Expected: `KeyError: 'is_superadmin'`.

- [ ] **Step 3: Add the schema field**

In `backend/app/schemas/user.py`, immediately after `approval_status` (line 71):

```python
    approval_status: str = "approved"
    # Platform-operator flag, denormalized onto every UserResponse so the
    # frontend middleware can 404 the /admin route group without an extra
    # fetch. This is a UX guard only — require_superadmin on the backend is
    # the real boundary, and it also checks the env allowlist, which never
    # leaves the server.
    is_superadmin: bool = False
```

No change is needed in `backend/app/api/routes/auth.py`: `/me` builds its response with `UserResponse.model_validate(current_user)`, so the new field populates from the ORM object automatically.

- [ ] **Step 4: Run the test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_authz.py -v`

Expected: all pass.

- [ ] **Step 5: Add the middleware guard**

In `frontend/src/middleware.ts`, insert immediately after the `if (!accessToken) { … }` block closes (line 335) and **before** the `if (path.startsWith("/api/") …)` auth block:

```ts
    // ── Super-admin surface: fail CLOSED ────────────────────────────────
    // /admin pages and /api/admin proxy calls are 404 for everyone who is
    // not a platform operator. 404 rather than 403 so the surface is not
    // discoverable. Resolved with its own /auth/me call (locals.user is not
    // populated yet at this point) — the cost lands only on admin paths.
    // Any doubt — fetch failure, missing field — is a 404, never a pass.
    if (path === "/admin" || path.startsWith("/admin/") || path.startsWith("/api/admin/")) {
        let isOperator = false;
        try {
            const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
            const meRes = await fetch(`${apiUrl}/api/auth/me`, {
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (meRes.ok) {
                const me = await meRes.json();
                isOperator = me?.is_superadmin === true;
            }
        } catch {
            isOperator = false;
        }
        if (!isOperator) {
            if (path.startsWith("/api/")) {
                return withSecurityHeaders(new Response(
                    JSON.stringify({ detail: "Not Found" }),
                    { status: 404, headers: { "Content-Type": "application/json" } }
                ));
            }
            return withSecurityHeaders(new Response(null, { status: 404 }));
        }
    }
```

- [ ] **Step 6: Add the type**

In `frontend/src/env.d.ts`, add `is_superadmin` to the `User` interface:

```ts
    is_superadmin?: boolean;
```

- [ ] **Step 7: Verify the frontend builds**

```bash
cd frontend && npm run check && npm run build
```

Expected: both succeed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/user.py backend/tests/test_admin_authz.py \
  frontend/src/middleware.ts frontend/src/env.d.ts
git commit -m "feat(admin): expose is_superadmin and fail-closed /admin middleware guard"
```

---

## Task 12: Admin proxy route and shell

**Files:**
- Create: `frontend/src/pages/api/admin/[...path].ts`
- Create: `frontend/src/components/ui/AdminShell.astro`

**Interfaces:**
- Consumes: middleware guard (Task 11).
- Produces: `/api/admin/*` browser-reachable proxy; `<AdminShell title active>` wrapping `Layout.astro` with a wide container and no BottomNav.

- [ ] **Step 1: Create the proxy**

Create `frontend/src/pages/api/admin/[...path].ts` — a verbatim copy of `frontend/src/pages/api/budget/[...path].ts` with two changes: the doc comment, and the error-log prefix. Critically, keep `url.pathname` (not `params.path`), `redirect: "manual"`, the cookie→Bearer injection, and `tryRefreshFor401`.

```ts
import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "../../../lib/server/refresh";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

/**
 * Wildcard proxy for all /api/admin/* requests.
 *
 * Route: /api/admin/[...path]  →  <BACKEND>/api/admin/<path>
 *
 * The middleware already 404s this path for non-operators, and the backend's
 * require_superadmin re-checks independently — this file adds no authorization
 * of its own on purpose. It uses url.pathname rather than params.path because
 * rebuilding the path drops the trailing slash and FastAPI's 307 then breaks
 * the proxied POST body.
 */
async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    if (!forwardHeaders.has("Authorization")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            const token = decodeURIComponent(match[1]);
            forwardHeaders.set("Authorization", `Bearer ${token}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    async function doFetch(targetUrl: string): Promise<Response> {
        const backendRes = await fetch(targetUrl, {
            method: request.method,
            headers: forwardHeaders,
            body: body,
            redirect: "manual",
        });

        if (backendRes.status >= 300 && backendRes.status < 400) {
            const location = backendRes.headers.get("location");
            if (location) {
                const redirectUrl = location.startsWith("http")
                    ? location
                    : `${BACKEND_URL}${location}`;
                return doFetch(redirectUrl);
            }
        }

        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            if (key.toLowerCase() === "transfer-encoding") continue;
            responseHeaders.set(key, value);
        }

        return new Response(backendRes.body, {
            status: backendRes.status,
            statusText: backendRes.statusText,
            headers: responseHeaders,
        });
    }

    try {
        let res = await doFetch(backendUrl);
        if (res.status === 401) {
            const refreshed = await tryRefreshFor401(res.status, request.headers.get("cookie") ?? "");
            if (refreshed) {
                forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
                res = await doFetch(backendUrl);
                for (const c of refreshed.setCookies) res.headers.append("Set-Cookie", c);
            }
        }
        return res;
    } catch (e: any) {
        console.error(`[api/admin proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
        return new Response(
            JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
            { status: 502, headers: { "Content-Type": "application/json" } }
        );
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const PUT: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
```

- [ ] **Step 2: Create the shell**

Create `frontend/src/components/ui/AdminShell.astro`:

```astro
---
/**
 * Chrome for the operator console.
 *
 * Wraps Layout.astro DIRECTLY. Not PageLayout or BudgetShell — their
 * BottomNav is hard-wired with no opt-out prop and fires four backend calls
 * per render, none of which mean anything here.
 *
 * Two deliberate departures from the family-facing shells: a wider container
 * (every other shell caps at lg:max-w-6xl, which is too narrow for tabular
 * operator data) and English-only copy, kept in each page's local dict rather
 * than lib/i18n.ts, which is scoped to family-facing strings.
 */
import Layout from "../../layouts/Layout.astro";

interface Props {
    title: string;
    /** Nav key of the current page, for the active-link highlight. */
    active?: "overview" | "families" | "billing" | "deletions" | "audit";
}
const { title, active } = Astro.props;

const NAV = [
    { key: "overview", href: "/admin", label: "Overview" },
    { key: "families", href: "/admin/families", label: "Families" },
    { key: "billing", href: "/admin/billing-review", label: "Billing review" },
    { key: "deletions", href: "/admin/deletions", label: "Deletions" },
    { key: "audit", href: "/admin/audit", label: "Audit log" },
] as const;
---

<Layout title={`Admin · ${title}`} theme="light" noindex>
    <div class="min-h-screen bg-slate-50 text-slate-900">
        <header class="border-b border-slate-200 bg-white">
            <div class="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
                <a href="/admin" class="text-sm font-semibold tracking-tight">
                    Operator console
                </a>
                <nav class="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    {NAV.map((item) => (
                        <a
                            href={item.href}
                            class={`rounded px-2 py-1 hover:bg-slate-100 ${
                                active === item.key
                                    ? "bg-slate-900 text-white hover:bg-slate-900"
                                    : "text-slate-600"
                            }`}
                        >
                            {item.label}
                        </a>
                    ))}
                </nav>
                <a href="/parent" class="ml-auto text-sm text-slate-500 hover:text-slate-900">
                    Back to app
                </a>
            </div>
        </header>

        <main class="mx-auto max-w-[1400px] px-4 py-6">
            <h1 class="mb-5 text-xl font-semibold tracking-tight">{title}</h1>
            <slot />
        </main>
    </div>
</Layout>
```

- [ ] **Step 3: Verify the frontend builds**

```bash
cd frontend && npm run check && npm run build
```

Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/api/admin/ frontend/src/components/ui/AdminShell.astro
git commit -m "feat(admin): admin API proxy and console shell"
```

---

## Task 13: Admin pages — overview, directory, billing review, deletions, audit

**Files:**
- Create: `frontend/src/pages/admin/index.astro`
- Create: `frontend/src/pages/admin/families.astro`
- Create: `frontend/src/pages/admin/billing-review.astro`
- Create: `frontend/src/pages/admin/deletions.astro`
- Create: `frontend/src/pages/admin/audit.astro`

**Interfaces:**
- Consumes: `AdminShell` (Task 12); backend endpoints from Tasks 4, 5, 7.
- Produces: five SSR pages. Each fetches server-side with `apiFetch(path, { token })` and renders a plain table — no client JS, no charts.

- [ ] **Step 1: Create the overview page**

Create `frontend/src/pages/admin/index.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const { data } = await apiFetch<any>("/api/admin/overview", { token });
// The middleware already 404s non-operators, so a null body here means the
// backend is down, not that the caller lacks permission.
const pulse = data ?? null;

const money = (cents: number, currency: string) =>
    `${(cents / 100).toFixed(2)} ${currency}`;

const TILES: [string, number, string][] = pulse
    ? [
          ["Families", pulse.families_total, "active tenants"],
          ["Suspended", pulse.families_suspended, "locked out by an operator"],
          ["Pending purge", pulse.families_pending_purge, "inside the 30-day window"],
          ["Users", pulse.users_total, "not soft-deleted"],
          ["Verified", pulse.users_verified, "email confirmed"],
          ["Awaiting approval", pulse.users_pending_approval, "join-code signups"],
          ["Billing review", pulse.billing_needs_review, "webhook flagged for a human"],
          ["Receipt drafts", pulse.receipt_drafts_pending, "low-confidence scans"],
          ["Overdue tasks", pulse.overdue_assignments, "across all families"],
      ]
    : [];
---

<AdminShell title="Overview" active="overview">
    {!pulse && (
        <p class="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            Could not load platform state. The backend may be restarting.
        </p>
    )}

    {pulse && (
        <>
            <div class="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
                {TILES.map(([label, value, hint]) => (
                    <div class="rounded-lg border border-slate-200 bg-white p-4">
                        <div class="text-xs uppercase tracking-wide text-slate-500">{label}</div>
                        <div class="num mt-1 text-2xl font-semibold">{value}</div>
                        <div class="mt-1 text-xs text-slate-400">{hint}</div>
                    </div>
                ))}
            </div>

            <section class="mt-8">
                <h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                    Current-state MRR
                </h2>
                <p class="mb-3 max-w-3xl text-xs text-slate-500">
                    Implied by today's subscription rows — not a time series, and not
                    reconstructible history. Reported per currency because no FX rate is
                    stored; a single summed figure would be fiction.
                </p>
                {pulse.mrr.length === 0 ? (
                    <p class="text-sm text-slate-500">No paying subscriptions.</p>
                ) : (
                    <table class="w-full max-w-md border-collapse text-sm">
                        <thead>
                            <tr class="border-b border-slate-200 text-left text-slate-500">
                                <th class="py-2">Currency</th>
                                <th class="py-2">Subscriptions</th>
                                <th class="py-2 text-right">MRR</th>
                            </tr>
                        </thead>
                        <tbody>
                            {pulse.mrr.map((row: any) => (
                                <tr class="border-b border-slate-100">
                                    <td class="py-2">{row.currency}</td>
                                    <td class="num py-2">{row.subscriptions}</td>
                                    <td class="num py-2 text-right">
                                        {money(row.cents, row.currency)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </section>

            <section class="mt-8">
                <h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                    Bank-matcher webhook health
                </h2>
                <dl class="flex flex-wrap gap-6 text-sm">
                    <div>
                        <dt class="text-slate-500">By status</dt>
                        <dd class="num">
                            {Object.entries(pulse.a2a.by_status)
                                .map(([k, v]) => `${k}: ${v}`)
                                .join(" · ") || "no deliveries"}
                        </dd>
                    </div>
                    <div>
                        <dt class="text-slate-500">Overdue retries</dt>
                        <dd class="num">{pulse.a2a.overdue_retries}</dd>
                    </div>
                    <div>
                        <dt class="text-slate-500">Oldest pending</dt>
                        <dd class="num">{pulse.a2a.oldest_pending_at ?? "—"}</dd>
                    </div>
                </dl>
            </section>
        </>
    )}
</AdminShell>
```

- [ ] **Step 2: Create the directory page**

Create `frontend/src/pages/admin/families.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const q = Astro.url.searchParams.get("q") ?? "";
const includeDeleted = Astro.url.searchParams.get("include_deleted") === "true";
const offset = Number(Astro.url.searchParams.get("offset") ?? "0") || 0;
const LIMIT = 50;

const params = new URLSearchParams({
    limit: String(LIMIT),
    offset: String(offset),
});
if (q) params.set("q", q);
if (includeDeleted) params.set("include_deleted", "true");

const { data } = await apiFetch<any>(`/api/admin/families?${params}`, { token });
const result = data ?? { total: 0, items: [] };
const shortDate = (iso: string | null) => (iso ? iso.slice(0, 10) : "—");
---

<AdminShell title="Families" active="families">
    <form method="get" class="mb-4 flex flex-wrap items-center gap-3">
        <input
            type="search"
            name="q"
            value={q}
            placeholder="name, join code, family id, or member email"
            class="w-96 max-w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <label class="flex items-center gap-2 text-sm text-slate-600">
            <input
                type="checkbox"
                name="include_deleted"
                value="true"
                checked={includeDeleted}
            />
            include deleted
        </label>
        <button class="rounded bg-slate-900 px-3 py-2 text-sm text-white">Search</button>
        <span class="num text-sm text-slate-500">{result.total} match(es)</span>
    </form>

    <div class="overflow-x-auto">
        <table class="w-full min-w-[900px] border-collapse text-sm">
            <thead>
                <tr class="border-b border-slate-200 text-left text-slate-500">
                    <th class="py-2">Family</th>
                    <th class="py-2">Plan</th>
                    <th class="py-2">Status</th>
                    <th class="py-2">Members</th>
                    <th class="py-2">Created</th>
                    <th class="py-2">Last seen</th>
                    <th class="py-2">Join code</th>
                </tr>
            </thead>
            <tbody>
                {result.items.map((row: any) => (
                    <tr class="border-b border-slate-100 hover:bg-slate-50">
                        <td class="py-2">
                            <a class="font-medium underline" href={`/admin/families/${row.id}`}>
                                {row.name}
                            </a>
                        </td>
                        <td class="py-2">{row.plan}</td>
                        <td class="py-2">
                            {row.deleted_at
                                ? "deleted"
                                : row.is_active
                                  ? (row.subscription_status ?? "free")
                                  : "suspended"}
                        </td>
                        <td class="num py-2">{row.member_count}</td>
                        <td class="num py-2">{shortDate(row.created_at)}</td>
                        <td class="num py-2">{shortDate(row.last_seen_at)}</td>
                        <td class="num py-2">{row.join_code ?? "—"}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    </div>

    {result.total > LIMIT && (
        <div class="mt-4 flex gap-3 text-sm">
            {offset > 0 && (
                <a
                    class="underline"
                    href={`/admin/families?${new URLSearchParams({ q, offset: String(Math.max(0, offset - LIMIT)) })}`}
                >
                    ← Previous
                </a>
            )}
            {offset + LIMIT < result.total && (
                <a
                    class="underline"
                    href={`/admin/families?${new URLSearchParams({ q, offset: String(offset + LIMIT) })}`}
                >
                    Next →
                </a>
            )}
        </div>
    )}
</AdminShell>
```

- [ ] **Step 3: Create the billing-review page**

Create `frontend/src/pages/admin/billing-review.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const { data } = await apiFetch<any[]>("/api/admin/billing-review", { token });
const rows = data ?? [];
---

<AdminShell title="Billing review" active="billing">
    <p class="mb-4 max-w-3xl text-sm text-slate-600">
        Subscriptions the PayPal webhook refused to act on automatically — refunds,
        reversals, and the failed-cancel case that risks double billing. No automatic
        downgrade happens for these; a human decides.
    </p>

    {rows.length === 0 ? (
        <p class="text-sm text-slate-500">Nothing awaiting review.</p>
    ) : (
        <div class="overflow-x-auto">
            <table class="w-full min-w-[900px] border-collapse text-sm">
                <thead>
                    <tr class="border-b border-slate-200 text-left text-slate-500">
                        <th class="py-2">Family</th>
                        <th class="py-2">Plan</th>
                        <th class="py-2">Status</th>
                        <th class="py-2">PayPal id</th>
                        <th class="py-2">Reason</th>
                        <th class="py-2">Flagged</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row) => (
                        <tr class="border-b border-slate-100">
                            <td class="py-2">
                                <a class="underline" href={`/admin/families/${row.family_id}`}>
                                    {row.family_name}
                                </a>
                            </td>
                            <td class="py-2">{row.plan ?? "—"}</td>
                            <td class="py-2">{row.status}</td>
                            <td class="num py-2">{row.paypal_subscription_id ?? "—"}</td>
                            <td class="py-2">{row.review_reason ?? "—"}</td>
                            <td class="num py-2">{row.updated_at.slice(0, 16).replace("T", " ")}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )}
</AdminShell>
```

- [ ] **Step 4: Create the deletions page**

Create `frontend/src/pages/admin/deletions.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const { data } = await apiFetch<any[]>("/api/admin/deletions", { token });
const rows = data ?? [];
---

<AdminShell title="Pending deletions" active="deletions">
    <p class="mb-4 max-w-3xl text-sm text-slate-600">
        Families inside the 30-day recovery window. Reinstating one restores its data
        but <strong>not</strong> its billing — the PayPal subscription was cancelled at
        closure and the family must re-subscribe.
    </p>

    {rows.length === 0 ? (
        <p class="text-sm text-slate-500">No families pending purge.</p>
    ) : (
        <table class="w-full max-w-4xl border-collapse text-sm">
            <thead>
                <tr class="border-b border-slate-200 text-left text-slate-500">
                    <th class="py-2">Family</th>
                    <th class="py-2">Members</th>
                    <th class="py-2">Closed</th>
                    <th class="py-2">Purges after</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((row) => (
                    <tr class="border-b border-slate-100">
                        <td class="py-2">
                            <a class="underline" href={`/admin/families/${row.id}`}>{row.name}</a>
                        </td>
                        <td class="num py-2">{row.member_count}</td>
                        <td class="num py-2">{row.deleted_at.slice(0, 10)}</td>
                        <td class="num py-2">{row.purge_after.slice(0, 10)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    )}
</AdminShell>
```

- [ ] **Step 5: Create the audit page**

Create `frontend/src/pages/admin/audit.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const action = Astro.url.searchParams.get("action") ?? "";
const offset = Number(Astro.url.searchParams.get("offset") ?? "0") || 0;
const LIMIT = 100;

const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
if (action) params.set("action", action);

const { data } = await apiFetch<any>(`/api/admin/audit?${params}`, { token });
const result = data ?? { total: 0, items: [] };
---

<AdminShell title="Audit log" active="audit">
    <form method="get" class="mb-4 flex items-center gap-3">
        <input
            type="text"
            name="action"
            value={action}
            placeholder="filter by action, e.g. family.suspend"
            class="w-80 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button class="rounded bg-slate-900 px-3 py-2 text-sm text-white">Filter</button>
        <span class="num text-sm text-slate-500">{result.total} entries</span>
    </form>

    <div class="overflow-x-auto">
        <table class="w-full min-w-[1000px] border-collapse text-sm">
            <thead>
                <tr class="border-b border-slate-200 text-left text-slate-500">
                    <th class="py-2">When</th>
                    <th class="py-2">Operator</th>
                    <th class="py-2">Action</th>
                    <th class="py-2">Family</th>
                    <th class="py-2">Result</th>
                    <th class="py-2">Params</th>
                </tr>
            </thead>
            <tbody>
                {result.items.map((row: any) => (
                    <tr class="border-b border-slate-100 align-top">
                        <td class="num py-2 whitespace-nowrap">
                            {row.created_at.slice(0, 19).replace("T", " ")}
                        </td>
                        <td class="py-2">{row.actor_email}</td>
                        <td class="py-2 font-medium">{row.action}</td>
                        <td class="py-2">
                            {row.target_family_id ? (
                                <a class="underline" href={`/admin/families/${row.target_family_id}`}>
                                    {row.target_family_id.slice(0, 8)}
                                </a>
                            ) : (
                                "—"
                            )}
                        </td>
                        <td class={`py-2 ${row.result === "error" ? "text-red-700" : ""}`}>
                            {row.result}
                            {row.error && <div class="text-xs text-red-600">{row.error}</div>}
                        </td>
                        <td class="py-2 text-xs text-slate-500">
                            {JSON.stringify(row.params ?? {})}
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    </div>
</AdminShell>
```

- [ ] **Step 6: Verify the frontend builds**

```bash
cd frontend && npm run check && npm run build
```

Expected: both succeed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/admin/
git commit -m "feat(admin): overview, directory, billing-review, deletions, audit pages"
```

---

## Task 14: Admin page — family detail with actions

**Files:**
- Create: `frontend/src/pages/admin/families/[id].astro`

**Interfaces:**
- Consumes: `GET /api/admin/families/{id}` (Task 6), the action routes (Tasks 9, 10), `AdminShell` (Task 12).
- Produces: the family detail page. Actions post through the `/api/admin/*` proxy from a small inline script; the page reloads on success.

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/admin/families/[id].astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const familyId = Astro.params.id!;
const { data, status } = await apiFetch<any>(
    `/api/admin/families/${familyId}`,
    { token }
);
if (status === 404 || !data) return Astro.redirect("/admin/families");

const { overview, members, economy, tasks, budget, billing, integrations } = data;
const kids = members.filter((m: any) => m.role !== "parent");
const money = (cents: number) => `$${(cents / 100).toFixed(2)}`;
const shortDT = (iso: string | null) =>
    iso ? iso.slice(0, 16).replace("T", " ") : "—";

// NULL means every module is on. Rendered explicitly so the operator never
// reads an empty list as "no modules".
const moduleSummary =
    overview.enabled_modules === null
        ? "all modules on (default)"
        : overview.enabled_modules.join(", ") || "all optional modules off";
---

<AdminShell title={overview.name} active="families">
    <div class="mb-4 flex flex-wrap gap-3 text-sm">
        <a class="underline" href="/admin/families">← All families</a>
        <span class="text-slate-400">·</span>
        <span class="num text-slate-500">{overview.id}</span>
    </div>

    {overview.deleted_at && (
        <div class="mb-5 rounded border border-amber-300 bg-amber-50 p-4 text-sm">
            <strong>Closed {overview.deleted_at.slice(0, 10)}.</strong> Purges after
            {" "}{overview.purge_after?.slice(0, 10)}. Reinstating restores the data but
            <strong> not</strong> billing — the PayPal subscription was cancelled at closure.
            <button
                class="ml-3 rounded bg-amber-700 px-2 py-1 text-white"
                data-action={`/api/admin/families/${familyId}/cancel-deletion`}
            >
                Cancel deletion
            </button>
        </div>
    )}

    {!overview.is_active && (
        <div class="mb-5 rounded border border-red-300 bg-red-50 p-4 text-sm">
            <strong>Suspended.</strong> Every member is locked out of the app.
            <button
                class="ml-3 rounded bg-red-700 px-2 py-1 text-white"
                data-action={`/api/admin/families/${familyId}/suspend`}
                data-payload={JSON.stringify({ suspended: false })}
            >
                Reinstate
            </button>
        </div>
    )}

    <section class="mb-8 grid gap-4 md:grid-cols-2">
        <div class="rounded-lg border border-slate-200 bg-white p-4">
            <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Overview
            </h2>
            <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt class="text-slate-500">Timezone</dt><dd>{overview.timezone}</dd>
                <dt class="text-slate-500">Created</dt><dd class="num">{overview.created_at.slice(0, 10)}</dd>
                <dt class="text-slate-500">Join code</dt><dd class="num">{overview.join_code ?? "—"}</dd>
                <dt class="text-slate-500">Modules</dt><dd>{moduleSummary}</dd>
                <dt class="text-slate-500">Point value</dt><dd class="num">{money(overview.point_value_cents)}</dd>
                <dt class="text-slate-500">Comped until</dt>
                <dd class="num">{overview.referral_bonus_until?.slice(0, 10) ?? "—"}</dd>
                <dt class="text-slate-500">AI consent</dt>
                <dd>{overview.ai_processing_consent ? "granted" : "not granted"}</dd>
            </dl>
            <p class="mt-3 text-xs text-slate-400">
                AI consent covers proof-photo validation and Jarvis chat reads only —
                not the calendar or receipt scanners.
            </p>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-4">
            <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Billing
            </h2>
            {billing ? (
                <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                    <dt class="text-slate-500">Plan</dt><dd>{billing.plan} ({billing.currency})</dd>
                    <dt class="text-slate-500">Status</dt><dd>{billing.status}</dd>
                    <dt class="text-slate-500">Cycle</dt><dd>{billing.billing_cycle}</dd>
                    <dt class="text-slate-500">PayPal id</dt><dd class="num">{billing.paypal_subscription_id ?? "—"}</dd>
                    <dt class="text-slate-500">Period ends</dt><dd class="num">{billing.current_period_end?.slice(0, 10) ?? "—"}</dd>
                    <dt class="text-slate-500">Payment failed</dt><dd class="num">{billing.payment_failure_at?.slice(0, 10) ?? "—"}</dd>
                </dl>
            ) : (
                <p class="text-sm text-slate-500">No subscription row (free tier).</p>
            )}
            {billing?.needs_review && (
                <p class="mt-3 rounded bg-amber-50 p-2 text-sm text-amber-900">
                    Flagged for review: {billing.review_reason}
                </p>
            )}
        </div>
    </section>

    <section class="mb-8">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Members
        </h2>
        <div class="overflow-x-auto">
            <table class="w-full min-w-[900px] border-collapse text-sm">
                <thead>
                    <tr class="border-b border-slate-200 text-left text-slate-500">
                        <th class="py-2">Name</th>
                        <th class="py-2">Email</th>
                        <th class="py-2">Role</th>
                        <th class="py-2">Verified</th>
                        <th class="py-2">Approval</th>
                        <th class="py-2">Points</th>
                        <th class="py-2">Cash</th>
                        <th class="py-2">Last seen</th>
                        <th class="py-2">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {members.map((m: any) => (
                        <tr class="border-b border-slate-100">
                            <td class="py-2">{m.name}</td>
                            <td class="py-2">{m.email}</td>
                            <td class="py-2">{m.role}</td>
                            <td class="py-2">{m.email_verified ? "yes" : "no"}</td>
                            <td class="py-2">{m.approval_status}</td>
                            <td class="num py-2">{m.points}</td>
                            <td class="num py-2">{money(m.cash_cents)}</td>
                            <td class="num py-2">{shortDT(m.last_seen_at)}</td>
                            <td class="py-2">
                                <div class="flex flex-wrap gap-1">
                                    <button
                                        class="rounded border border-slate-300 px-2 py-1 text-xs"
                                        data-action={`/api/admin/users/${m.id}/resend-verification`}
                                    >
                                        Resend verification
                                    </button>
                                    <button
                                        class="rounded border border-slate-300 px-2 py-1 text-xs"
                                        data-action={`/api/admin/users/${m.id}/password-reset`}
                                        data-confirm="This also invalidates all of this user's active sessions. Continue?"
                                    >
                                        Reset password
                                    </button>
                                    <button
                                        class="rounded border border-slate-300 px-2 py-1 text-xs"
                                        data-action={`/api/admin/users/${m.id}/active`}
                                        data-payload={JSON.stringify({ active: !m.is_active })}
                                        data-confirm={
                                            m.is_active
                                                ? "Deactivating also cancels this user's pending, claimed and overdue assignments. Reactivating does NOT restore them. Continue?"
                                                : undefined
                                        }
                                    >
                                        {m.is_active ? "Deactivate" : "Reactivate"}
                                    </button>
                                </div>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    </section>

    <section class="mb-8 grid gap-4 md:grid-cols-3">
        <div class="rounded-lg border border-slate-200 bg-white p-4">
            <h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Tasks</h2>
            <dl class="grid grid-cols-[auto_1fr] gap-x-4 text-sm">
                {Object.entries(tasks.by_status).map(([k, v]) => (
                    <>
                        <dt class="text-slate-500">{k}</dt>
                        <dd class="num">{v}</dd>
                    </>
                ))}
            </dl>
        </div>
        <div class="rounded-lg border border-slate-200 bg-white p-4">
            <h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Budget</h2>
            <dl class="grid grid-cols-[auto_1fr] gap-x-4 text-sm">
                <dt class="text-slate-500">Accounts</dt><dd class="num">{budget.account_count}</dd>
                <dt class="text-slate-500">Transactions</dt><dd class="num">{budget.transaction_count}</dd>
                <dt class="text-slate-500">Drafts pending</dt><dd class="num">{budget.receipt_drafts_pending}</dd>
            </dl>
        </div>
        <div class="rounded-lg border border-slate-200 bg-white p-4">
            <h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Bank-matcher
            </h2>
            {integrations.a2a_webhook ? (
                <dl class="grid grid-cols-[auto_1fr] gap-x-4 text-sm">
                    <dt class="text-slate-500">Enabled</dt>
                    <dd>{integrations.a2a_webhook.enabled ? "yes" : "no"}</dd>
                    <dt class="text-slate-500">Failures</dt>
                    <dd class="num">{integrations.a2a_webhook.failure_count}</dd>
                    <dt class="text-slate-500">Last success</dt>
                    <dd class="num">{shortDT(integrations.a2a_webhook.last_success_at)}</dd>
                </dl>
            ) : (
                <p class="text-sm text-slate-500">Not configured.</p>
            )}
        </div>
    </section>

    <section class="mb-8">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Recent cash movements
        </h2>
        {economy.recent_cash_transactions.length === 0 ? (
            <p class="text-sm text-slate-500">No cash transactions.</p>
        ) : (
            <table class="w-full max-w-4xl border-collapse text-sm">
                <thead>
                    <tr class="border-b border-slate-200 text-left text-slate-500">
                        <th class="py-2">When</th>
                        <th class="py-2">Type</th>
                        <th class="py-2">Jar</th>
                        <th class="py-2">Week</th>
                        <th class="py-2 text-right">Amount</th>
                        <th class="py-2 text-right">Balance</th>
                    </tr>
                </thead>
                <tbody>
                    {economy.recent_cash_transactions.map((tx: any) => (
                        <tr class="border-b border-slate-100">
                            <td class="num py-2">{shortDT(tx.created_at)}</td>
                            <td class="py-2">{tx.type}</td>
                            <td class="py-2">{tx.jar}</td>
                            <td class="num py-2">{tx.week_of ?? "—"}</td>
                            <td class="num py-2 text-right">{money(tx.amount_cents)}</td>
                            <td class="num py-2 text-right">{money(tx.balance_after)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        )}
    </section>

    <section class="rounded-lg border border-slate-200 bg-white p-4">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Family actions
        </h2>
        <div class="flex flex-wrap gap-2">
            <button
                class="rounded border border-slate-300 px-3 py-2 text-sm"
                data-action={`/api/admin/families/${familyId}/comp-plus`}
                data-payload={JSON.stringify({ days: 30 })}
            >
                Comp 30 days of Plus
            </button>
            {overview.is_active && (
                <button
                    class="rounded border border-red-300 px-3 py-2 text-sm text-red-700"
                    data-action={`/api/admin/families/${familyId}/suspend`}
                    data-payload={JSON.stringify({ suspended: true })}
                    data-confirm="Suspending locks every member out of the app immediately. Continue?"
                >
                    Suspend family
                </button>
            )}
        </div>
        <p class="mt-3 max-w-3xl text-xs text-slate-500">
            Comping sets an absolute expiry (now + 30 days). Repeating it does not stack.
            Points and cash adjustments are deliberately absent — an operator has no
            member identity to attribute them to, and faking one would put a change in a
            child's ledger that their parent never made.
        </p>
    </section>

    <section class="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Operator tools
        </h2>
        <div class="grid gap-6 lg:grid-cols-2">
            <form data-action={`/api/admin/families/${familyId}/modules`} class="space-y-2">
                <h3 class="text-sm font-medium">Module registry</h3>
                <p class="text-xs text-slate-500">
                    Leave every box unchecked and tick "restore default" to go back to
                    NULL, which means all modules on.
                </p>
                <div class="flex flex-wrap gap-3 text-sm">
                    {["meals", "shopping", "calendar", "pet", "chat", "budget", "gigs"].map((m) => (
                        <label class="flex items-center gap-1">
                            <input
                                type="checkbox"
                                name="enabled_modules"
                                value={m}
                                checked={
                                    overview.enabled_modules === null ||
                                    overview.enabled_modules.includes(m)
                                }
                            />
                            {m}
                        </label>
                    ))}
                </div>
                <label class="flex items-center gap-1 text-sm">
                    <input type="checkbox" name="__null_modules" value="true" />
                    restore default (all on)
                </label>
                <button class="rounded border border-slate-300 px-3 py-2 text-sm">
                    Save modules
                </button>
            </form>

            <form
                data-action={`/api/admin/families/${familyId}/release-paycheck`}
                data-confirm="Releasing credits real money to the kid's jars. It is idempotent per kid and week, but it cannot be undone from here. Preview first. Continue?"
                class="space-y-2"
            >
                <h3 class="text-sm font-medium">Release a stuck chore paycheck</h3>
                <p class="text-xs text-slate-500">
                    Preview the projection and the kid's unreleased weeks first — the
                    preview link beside each kid opens the raw JSON.
                </p>
                <div class="flex flex-wrap items-end gap-2 text-sm">
                    <label class="flex flex-col">
                        <span class="text-xs text-slate-500">Kid</span>
                        <select name="kid_id" class="rounded border border-slate-300 px-2 py-1">
                            {kids.map((kid: any) => (
                                <option value={kid.id}>{kid.name}</option>
                            ))}
                        </select>
                    </label>
                    <label class="flex flex-col">
                        <span class="text-xs text-slate-500">Week (any day in it)</span>
                        <input
                            type="date"
                            name="week_of"
                            required
                            class="rounded border border-slate-300 px-2 py-1"
                        />
                    </label>
                    <button class="rounded border border-slate-300 px-3 py-2">Release</button>
                </div>
                <ul class="space-y-1 text-xs">
                    {kids.map((kid: any) => (
                        <li>
                            <a
                                class="underline"
                                href={`/api/admin/families/${familyId}/paycheck-preview/${kid.id}`}
                                target="_blank"
                                rel="noopener"
                            >
                                Preview {kid.name}
                            </a>
                        </li>
                    ))}
                </ul>
            </form>

            <form
                data-action={`/api/admin/families/${familyId}/undo-approval-form`}
                data-template={`/api/admin/families/${familyId}/assignments/{assignment_id}/undo-approval`}
                class="space-y-2"
            >
                <h3 class="text-sm font-medium">Undo a chore approval</h3>
                <p class="text-xs text-slate-500">
                    Claws the points back and clears the grade. Refuses bonus and gig
                    reversals — those must go through the parent's own review screen.
                </p>
                <div class="flex flex-wrap items-end gap-2 text-sm">
                    <label class="flex flex-col">
                        <span class="text-xs text-slate-500">Assignment id</span>
                        <input
                            type="text"
                            name="assignment_id"
                            data-path-param="true"
                            required
                            class="w-80 rounded border border-slate-300 px-2 py-1"
                        />
                    </label>
                    <button class="rounded border border-slate-300 px-3 py-2">Undo</button>
                </div>
            </form>

            <form data-action={`/api/admin/families/${familyId}/restore`} class="space-y-2">
                <h3 class="text-sm font-medium">Restore from the budget recycle bin</h3>
                <div class="flex flex-wrap items-end gap-2 text-sm">
                    <label class="flex flex-col">
                        <span class="text-xs text-slate-500">Type</span>
                        <select name="item_type" class="rounded border border-slate-300 px-2 py-1">
                            <option value="transaction">transaction</option>
                            <option value="account">account</option>
                            <option value="category">category</option>
                            <option value="category_group">category_group</option>
                        </select>
                    </label>
                    <label class="flex flex-col">
                        <span class="text-xs text-slate-500">Item id</span>
                        <input
                            type="text"
                            name="item_id"
                            required
                            class="w-80 rounded border border-slate-300 px-2 py-1"
                        />
                    </label>
                    <button class="rounded border border-slate-300 px-3 py-2">Restore</button>
                </div>
            </form>
        </div>
    </section>
</AdminShell>

<script>
    // Every operator action requires a typed reason, which is recorded in the
    // audit log alongside the change. Failures surface the backend's actual
    // message verbatim — nothing is swallowed.
    async function submitAction(
        url: string,
        payload: Record<string, unknown>,
        confirmMsg: string | undefined,
        control: HTMLButtonElement | null,
    ) {
        if (confirmMsg && !window.confirm(confirmMsg)) return;
        const reason = window.prompt("Reason for this action (recorded in the audit log):");
        if (!reason || reason.trim().length < 3) return;

        const original = control?.textContent ?? "";
        if (control) {
            control.disabled = true;
            control.textContent = "Working…";
        }
        try {
            const res = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ...payload, reason: reason.trim() }),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok) {
                window.alert(`Failed (${res.status}): ${body.detail ?? "unknown error"}`);
                return;
            }
            if (body.warning) window.alert(body.warning);
            window.location.reload();
        } catch (e) {
            window.alert(`Request failed: ${e}`);
        } finally {
            if (control) {
                control.disabled = false;
                control.textContent = original;
            }
        }
    }

    // Simple one-shot buttons carry their whole payload in data-payload.
    document
        .querySelectorAll<HTMLButtonElement>("button[data-action]")
        .forEach((btn) => {
            btn.addEventListener("click", () =>
                submitAction(
                    btn.dataset.action!,
                    JSON.parse(btn.dataset.payload || "{}"),
                    btn.dataset.confirm,
                    btn,
                ),
            );
        });

    // Forms build their payload from their own fields. A field marked
    // data-path-param is substituted into data-template instead of being sent
    // in the body — that is how the assignment id reaches its path segment.
    document.querySelectorAll<HTMLFormElement>("form[data-action]").forEach((form) => {
        form.addEventListener("submit", (ev) => {
            ev.preventDefault();
            const fd = new FormData(form);
            const payload: Record<string, unknown> = {};

            // Checkbox groups collapse to arrays; everything else is scalar.
            for (const key of new Set(fd.keys())) {
                if (key.startsWith("__")) continue;
                const values = fd.getAll(key).map(String);
                const isGroup =
                    form.querySelectorAll(`[name="${key}"]`).length > 1;
                payload[key] = isGroup ? values : values[0];
            }

            // The module form's explicit "restore default" wins: null, not [].
            if (fd.get("__null_modules") === "true") payload.enabled_modules = null;
            else if (form.querySelector('[name="enabled_modules"]') && !payload.enabled_modules)
                payload.enabled_modules = [];

            let url = form.dataset.action!;
            const template = form.dataset.template;
            if (template) {
                url = template;
                form
                    .querySelectorAll<HTMLInputElement>("[data-path-param]")
                    .forEach((input) => {
                        url = url.replace(`{${input.name}}`, encodeURIComponent(input.value));
                        delete payload[input.name];
                    });
            }

            submitAction(
                url,
                payload,
                form.dataset.confirm,
                form.querySelector("button"),
            );
        });
    });
</script>
```

- [ ] **Step 2: Verify the frontend builds**

```bash
cd frontend && npm run check && npm run build
```

Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/admin/families/
git commit -m "feat(admin): family detail page with operator actions"
```

---

## Task 15: Deployment configuration and documentation

**Files:**
- Modify: `.env.example`
- Modify: `.env.onprem.example`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the operator bootstrap procedure, written down.

- [ ] **Step 1: Add the env keys**

Append to both `.env.example` and `.env.onprem.example`:

```bash
# Platform-operator allowlist (comma-separated emails). A user reaches
# /admin only when users.is_superadmin is true AND their email is listed
# here. Leave EMPTY unless this is the production host — empty means the
# entire admin surface is unreachable by anyone.
SUPERADMIN_EMAILS=

# Minimum gap between users.last_seen_at writes for one user, in minutes.
LAST_SEEN_THROTTLE_MINUTES=15
```

- [ ] **Step 2: Document the bootstrap**

Append to `docs/DEPLOYMENT.md`:

```markdown
## Granting super-admin access

The operator console at `/admin` requires **two** independent grants. There is
deliberately no UI for either — this is a manual, auditable act.

1. **Env allowlist** — on the production host, set the operator's email in `.env`:

   ```bash
   SUPERADMIN_EMAILS=juan.mtz79@gmail.com
   ```

   Then redeploy so the backend picks it up: `./scripts/deploy-onprem.sh`.

2. **DB flag** — on the production host, as user `jc` (never `sudo podman`):

   ```bash
   ssh jc@10.1.0.91 'podman exec -i family_onprem_postgres \
     psql -U familyapp -d familyapp -c \
     "UPDATE users SET is_superadmin = true WHERE email = '\''juan.mtz79@gmail.com'\'';"'
   ```

3. **Cloudflare Access** — in the Zero Trust dashboard, create an Access
   application for the **path** `family.agent-ia.mx/admin*` with a policy
   allowing only that email. A path policy is used rather than a separate
   hostname because the auth cookies are host-only (no `Domain=` attribute), so
   a second hostname would receive no session.

Revoking is the reverse, and either step alone is sufficient to lock the
operator out. Every action taken through the console is recorded in
`operator_audit_log`, which carries no foreign keys and therefore survives the
purge of any family it describes.
```

- [ ] **Step 3: Update the project instructions**

In `CLAUDE.md`, add a row to the "Additional domains" table:

```markdown
| **Admin** (operator console) | `/api/admin` | Cross-tenant operator surface: family directory, per-family support views, ten bounded write actions, append-only `operator_audit_log`. Gated by `require_superadmin` — `users.is_superadmin` **AND** `SUPERADMIN_EMAILS`, 404 on failure. Frontend at `/admin/*` behind a Cloudflare Access path policy. Metadata only: no message bodies, no images. See `docs/superpowers/specs/2026-07-26-super-admin-dashboard-design.md`. |
```

And under "Multi-tenant isolation (critical)", append:

```markdown
The **only** sanctioned exception is `app/services/admin/`, reached exclusively
through `require_superadmin`. Never relax `family_id` filtering anywhere else,
and never use `verify_family_id` or `get_family_user` in an admin route — both
compare against the caller's own `family_id`.
```

- [ ] **Step 4: Run the full verification pass**

```bash
cd backend && ruff check app
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
cd frontend && npm run check && npm run build
```

Expected: ruff clean, full suite green with coverage ≥70%, migrations round-trip, frontend checks and builds.

- [ ] **Step 5: Commit**

```bash
git add .env.example .env.onprem.example docs/DEPLOYMENT.md CLAUDE.md
git commit -m "docs(admin): operator bootstrap procedure and env keys"
```

---

## Post-implementation

Open a PR from the feature branch, watch CI (ruff · migration round-trip · pytest with the ≥70% coverage gate · astro check + build), merge, sync main, and deploy with `./scripts/deploy-onprem.sh`. Complete the three deployment steps in `docs/DEPLOYMENT.md` — the env key, the DB flag, and the Cloudflare Access path policy — before expecting `/admin` to load.

**Six pre-existing defects** were catalogued in spec §13 and are **not** addressed by this plan. File them as issues; the most urgent is `backend/app/api/routes/uploads.py:47`, where proof-image authorization is a URL-string match with no role check, so any authenticated family member — including a CHILD — can fetch every proof photo in their family.
