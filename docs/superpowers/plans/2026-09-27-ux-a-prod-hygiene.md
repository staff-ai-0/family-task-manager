# UX-A Prod Hygiene Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the production issues that look broken, leak internals, or bury signal in noise (push health, stale push subscriptions, notification spam, Jarvis `[actions: …]` leak, raw kiosk errors, orphaned routines, CSP-blocked analytics beacon).

**Architecture:** Eleven independent fixes to existing flows. Backend changes stay inside the existing services (`PushService`, `NotificationService`, `JarvisService`) plus one data-only Alembic migration. Frontend logic that can be tested goes into small pure modules under `frontend/src/lib/` (covered by vitest); `.astro` pages only wire them in.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy async · pytest · pywebpush/py_vapid · Astro 7 SSR · Tailwind v4 · vitest

**Spec:** `docs/superpowers/specs/2026-09-27-ux-a-prod-hygiene-design.md` (evidence: `docs/audit/2026-09-27-ux-competitive/findings.md`)

## Global Constraints

- Work only in the worktree `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-a-prod-hygiene` (branch `feat/ux-a-prod-hygiene`). Never `cd` to the main checkout.
- **Backend tests:** run ONLY targeted files, in the foreground, through
  `/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/run-backend-tests.sh tests/<file>.py [-k expr]`
  (podman is down; it points pytest at an ephemeral Postgres on 5435 + local redis). **Never run the full backend suite** — it exceeds the command time cap. The controller runs it at the end.
- **Frontend checks:** from `frontend/`: `npx vitest run` and `npx astro check`. Vitest only picks up `frontend/test/**/*.test.ts`.
- Every user-visible string ships in Spanish and English; Spanish is the default when `lang` is missing.
- No new dependencies (backend or frontend).
- Every new test must be mutation-checked: after it passes, break the line it guards, confirm it fails, restore.
- Never type the two-word phrase made of `alembic` + the reverse-migration subcommand in any shell command (a repo hook blocks it by substring). CI runs the upgrade → reverse → upgrade round-trip.
- Do not touch production (no ssh, no deploy) — the controller does that after merge.
- Commit after each task with a conventional message ending in:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. VAPID env values with `=` padding or stray whitespace/newlines (common in hand-edited `.env`) must still read as valid — pinned in Task 1.
2. A notification whose `link` is absolute (`https://…`), protocol-relative (`//evil`), backslash-tricked (`/\evil`) or empty must never redirect off-site — pinned in Task 7.
3. A notification created at 11 pm Mexico City (next day in UTC) must group under the family's *today*, not "earlier" — pinned in Task 7.
4. If the transaction that creates a new reminder rolls back, the older reminders it would have superseded must stay unread — pinned in Task 3.
5. `/kiosk` while the backend is down must say "try again", not "your link expired" (a wall tablet during a deploy) — pinned in Task 9.

---

### Task 1: Push keypair health check

**Files:**
- Modify: `backend/app/services/push_service.py` (add helper + `PushService.keypair_status`)
- Modify: `backend/app/api/routes/push.py:43-68` (`push_health`)
- Test: `backend/tests/test_push_subscriptions.py` (append)

**Interfaces:**
- Produces: `PushService.keypair_status() -> dict[str, Any]` with keys `configured: bool`, `valid_keys: bool`, `error: str | None`. Never raises, never includes key material.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_push_subscriptions.py`:

```python
# ── VAPID keypair health (UX-A, 2026-09-27) ──────────────────────────────────
# Prod stores the private key in the 43-char raw form; the old health check
# assumed PEM (len >= 60) and told parents push was "not configured" while it
# worked. The check now derives the public key the same way pywebpush loads
# the private key for a real send (py_vapid.Vapid.from_string: raw or DER).
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings as app_settings


def _vapid_pair(fmt: str = "raw") -> tuple[str, str]:
    """A fresh P-256 pair as (private, public) env strings. fmt: raw | der."""
    key = ec.generate_private_key(ec.SECP256R1())
    if fmt == "raw":
        secret = key.private_numbers().private_value.to_bytes(32, "big")
    else:
        secret = key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    priv = base64.urlsafe_b64encode(secret).rstrip(b"=").decode()
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    pub = base64.urlsafe_b64encode(point).rstrip(b"=").decode()
    return priv, pub


def _set_keys(monkeypatch, priv: str, pub: str) -> None:
    monkeypatch.setattr(app_settings, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(app_settings, "VAPID_PUBLIC_KEY", pub)


class TestKeypairStatus:
    def test_raw_pair_is_valid(self, monkeypatch):
        _set_keys(monkeypatch, *_vapid_pair("raw"))
        assert PushService.keypair_status() == {
            "configured": True, "valid_keys": True, "error": None,
        }

    def test_der_pair_is_valid(self, monkeypatch):
        _set_keys(monkeypatch, *_vapid_pair("der"))
        assert PushService.keypair_status()["valid_keys"] is True

    def test_padding_and_whitespace_are_tolerated(self, monkeypatch):
        priv, pub = _vapid_pair("raw")
        _set_keys(monkeypatch, f"  {priv}\n", f"{pub}=\n")
        assert PushService.keypair_status()["valid_keys"] is True

    def test_mismatched_pair_is_invalid(self, monkeypatch):
        priv, _ = _vapid_pair("raw")
        _, other_pub = _vapid_pair("raw")
        _set_keys(monkeypatch, priv, other_pub)
        status = PushService.keypair_status()
        assert status == {"configured": True, "valid_keys": False, "error": "KeyMismatch"}

    def test_garbage_private_key_is_invalid_and_not_echoed(self, monkeypatch):
        _, pub = _vapid_pair("raw")
        _set_keys(monkeypatch, "not-a-real-key", pub)
        status = PushService.keypair_status()
        assert status["configured"] is True
        assert status["valid_keys"] is False
        assert status["error"] and "not-a-real-key" not in str(status)

    def test_empty_keys_are_unconfigured(self, monkeypatch):
        _set_keys(monkeypatch, "", "")
        assert PushService.keypair_status() == {
            "configured": False, "valid_keys": False, "error": None,
        }


@pytest.mark.asyncio
async def test_health_reports_raw_prod_style_pair_as_valid(
    client: AsyncClient, auth_headers, monkeypatch,
):
    priv, pub = _vapid_pair("raw")
    _set_keys(monkeypatch, priv, pub)
    r = await client.get("/api/push/health", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["valid_keys"] is True
    assert body["private_key_length"] == len(priv)
    assert body["public_key_length"] == len(pub)
```

- [ ] **Step 2: Run to verify they fail**

Run: `…/run-backend-tests.sh tests/test_push_subscriptions.py -k "Keypair or health_reports"`
Expected: FAIL — `AttributeError: type object 'PushService' has no attribute 'keypair_status'`, and the health test fails on `valid_keys` (old heuristic rejects the 43-char key).

- [ ] **Step 3: Implement** — in `backend/app/services/push_service.py`, add below `log = logging.getLogger(__name__)`:

```python
def _derive_public_key(private_key: str) -> str:
    """Public key (X9.62 uncompressed point, base64url, unpadded) of a VAPID
    private key, loaded exactly the way pywebpush loads it for a real send
    (``Vapid.from_string``: raw 32-byte or DER, base64url). Raises on a key
    pywebpush could not use either."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid.from_string(private_key=private_key)
    point = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()
```

and inside `class PushService`, right after `_vapid_configured`:

```python
    @staticmethod
    def keypair_status() -> dict[str, Any]:
        """Is the configured VAPID pair one a real send can use?

        ``valid_keys`` means the private key loads and derives exactly the
        configured public key. Never raises and never returns key material:
        on failure ``error`` is an exception class name or "KeyMismatch".
        """
        pub = (settings.VAPID_PUBLIC_KEY or "").strip().rstrip("=")
        priv = (settings.VAPID_PRIVATE_KEY or "").strip()
        if not (pub and priv):
            return {"configured": False, "valid_keys": False, "error": None}
        try:
            derived = _derive_public_key(priv)
        except Exception as exc:
            return {"configured": True, "valid_keys": False, "error": type(exc).__name__}
        if derived != pub:
            return {"configured": True, "valid_keys": False, "error": "KeyMismatch"}
        return {"configured": True, "valid_keys": True, "error": None}
```

In `backend/app/api/routes/push.py`, replace the body of `push_health` from `pub = settings.VAPID_PUBLIC_KEY or ""` through the `return {...}` with:

```python
    from sqlalchemy import func, select
    from app.models.push_subscription import PushSubscription
    from app.services.push_service import PushService

    keys = PushService.keypair_status()

    sub_count = int((await db.execute(
        select(func.count()).select_from(PushSubscription).where(
            PushSubscription.user_id == to_uuid_required(current_user.id)
        )
    )).scalar() or 0)

    return {
        "configured": keys["configured"],
        "valid_keys": keys["valid_keys"],
        "claim_email": settings.VAPID_CLAIM_EMAIL,
        "subscription_count": sub_count,
        "public_key_length": len(settings.VAPID_PUBLIC_KEY or ""),
        "private_key_length": len(settings.VAPID_PRIVATE_KEY or ""),
    }
```

(Keep the existing docstring; delete the now-unused `pub`/`priv`/`configured`/`valid_keys` locals and the "65 bytes → 87 chars" comment.)

- [ ] **Step 4: Run to verify they pass**

Run: `…/run-backend-tests.sh tests/test_push_subscriptions.py`
Expected: all PASS (existing tests included).

- [ ] **Step 5: Mutation check** — change `if derived != pub:` to `if False:`; `test_mismatched_pair_is_invalid` must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/push_service.py backend/app/api/routes/push.py backend/tests/test_push_subscriptions.py
git commit -m "fix(push): health derives the public key instead of guessing from PEM length

Prod uses the 43-char raw VAPID key, so the length heuristic reported
'not configured' while push worked. keypair_status() loads the key the
way pywebpush does and compares the derived public key.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Log push failure reasons, prune foreign-key subscriptions

**Files:**
- Modify: `backend/app/services/push_service.py` (module helpers + the `except WebPushException` branch of `send_to_user`)
- Test: `backend/tests/test_push_subscriptions.py` (append)

**Interfaces:**
- Produces (module-level, private): `_push_failure_reason(exc: WebPushException) -> str`, `_is_dead_subscription(status: int | None, reason: str) -> bool`.

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── Failure reasons + pruning (UX-A) ─────────────────────────────────────────
# Prod: one Apple endpoint answered 403 on every send for weeks and was never
# pruned (only 404/410 pruned), and the log never said WHY — pywebpush's
# exception omits the body because a 4xx requests.Response is falsy.
import logging

from pywebpush import WebPushException


class _FakeResp:
    """Mimics requests.Response: falsy for 4xx/5xx, exactly like the real one."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def __bool__(self) -> bool:
        return self.status_code < 400


async def _add_sub(db_session, user, endpoint: str) -> None:
    db_session.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh="p", auth="a"))
    await db_session.commit()


async def _endpoints(db_session, user) -> list[str]:
    return list((await db_session.scalars(
        select(PushSubscription.endpoint).where(PushSubscription.user_id == user.id)
    )).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,pruned", [
    (410, "", True),
    (404, "", True),
    (403, '{"reason":"VapidPkHashMismatch"}', True),
    (403, "the key in the authorization header does not correspond to the sender that created the subscription", True),
    (403, '{"reason":"BadJwtToken"}', False),
    (500, "upstream boom", False),
])
async def test_send_prunes_only_dead_or_foreign_key_subscriptions(
    db_session, test_parent_user, monkeypatch, status, body, pruned,
):
    monkeypatch.setattr(app_settings, "VAPID_PRIVATE_KEY", "fake-private")
    monkeypatch.setattr(app_settings, "VAPID_PUBLIC_KEY", "fake-public")
    endpoint = "https://web.push.apple.com/ENDPOINT-X"
    await _add_sub(db_session, test_parent_user, endpoint)

    exc = WebPushException("Push failed", response=_FakeResp(status, body))
    with patch("app.services.push_service.webpush", side_effect=exc):
        sent = await PushService.send_to_user(db_session, test_parent_user.id, {"title": "t"})

    assert sent == 0
    assert (endpoint in await _endpoints(db_session, test_parent_user)) is (not pruned)


@pytest.mark.asyncio
async def test_send_failure_logs_the_provider_reason(
    db_session, test_parent_user, monkeypatch, caplog,
):
    monkeypatch.setattr(app_settings, "VAPID_PRIVATE_KEY", "fake-private")
    monkeypatch.setattr(app_settings, "VAPID_PUBLIC_KEY", "fake-public")
    await _add_sub(db_session, test_parent_user, "https://web.push.apple.com/LOG-ME")

    exc = WebPushException("Push failed", response=_FakeResp(403, '{"reason":"BadJwtToken"}'))
    with caplog.at_level(logging.WARNING, logger="app.services.push_service"):
        with patch("app.services.push_service.webpush", side_effect=exc):
            await PushService.send_to_user(db_session, test_parent_user.id, {"title": "t"})

    assert "reason=BadJwtToken" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `…/run-backend-tests.sh tests/test_push_subscriptions.py -k "prunes_only or provider_reason"`
Expected: FAIL — the two 403 mismatch cases are not pruned, and `reason=BadJwtToken` is not in the log.

- [ ] **Step 3: Implement** — add below `_derive_public_key` in `push_service.py`:

```python
# 403 bodies that mean "this subscription was made with a different VAPID
# key" — the subscription is unusable forever, same as 404/410. Any other 403
# (e.g. Apple BadJwtToken) is OUR bug, not the device's: log it, never prune,
# or one bad deploy would silently wipe every device.
_KEY_MISMATCH_MARKERS = ("VapidPkHashMismatch", "does not correspond")


def _push_failure_reason(exc: WebPushException) -> str:
    """Provider's reason for a failed send: Apple's JSON ``reason`` when the
    body parses, else the first 200 chars of the body (FCM sends text)."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    try:
        text = resp.text or ""
    except Exception:
        return ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return text[:200]
    if isinstance(data, dict) and data.get("reason"):
        return str(data["reason"])
    return text[:200]


def _is_dead_subscription(status: int | None, reason: str) -> bool:
    if status in (404, 410):
        return True
    return status == 403 and any(m in reason for m in _KEY_MISMATCH_MARKERS)
```

Replace the `except WebPushException as exc:` block inside `send_to_user` with:

```python
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                reason = _push_failure_reason(exc)
                if _is_dead_subscription(status, reason):
                    dead_endpoints.append(sub.endpoint)
                    log.info(
                        "pruning push endpoint %s (status=%s reason=%s)",
                        sub.endpoint[:60], status, reason,
                    )
                else:
                    log.warning(
                        "push send to %s failed (status=%s reason=%s): %s",
                        sub.endpoint[:60], status, reason, exc,
                    )
```

Update the module docstring's second paragraph to: "Dead endpoints (404/410, or 403 for a subscription made with another VAPID key) are pruned automatically."

- [ ] **Step 4: Run to verify they pass**

Run: `…/run-backend-tests.sh tests/test_push_subscriptions.py`
Expected: all PASS.

- [ ] **Step 5: Mutation check** — change `_KEY_MISMATCH_MARKERS` to `()`; the two 403-mismatch parametrized cases must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/push_service.py backend/tests/test_push_subscriptions.py
git commit -m "fix(push): log provider reason, prune subscriptions made with another key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Superseding reminders + 14-day unread badge window

**Files:**
- Modify: `backend/app/services/notification_service.py` (constants, `_supersede_older`, `create`, `create_no_commit`, `unread_count`)
- Test: `backend/tests/test_notifications.py` (append a class)

**Interfaces:**
- Produces: `SUPERSEDING_TYPES: frozenset[str]` = `{"task_due", "task_assigned"}`, `UNREAD_BADGE_WINDOW_DAYS = 14` (module constants in `notification_service.py`).
- Note: `NotificationType` is a plain class of string constants (`NT.TASK_DUE == "task_due"`), not an Enum. `sql_update` is already imported in `notification_service.py`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_notifications.py`:

```python
from sqlalchemy import update as sa_update

from app.services.notification_service import UNREAD_BADGE_WINDOW_DAYS


async def _mk(db, family_id, user_id, type_, title):
    return await NotificationService.create(
        db, family_id=family_id, user_id=user_id, type=type_, title=title, push=False,
    )


async def _is_read(db, notif_id) -> bool:
    row = (await db.execute(
        select(Notification.is_read).where(Notification.id == notif_id)
    )).scalar_one()
    return bool(row)


class TestSupersedingReminders:
    """UX-A 2026-09-27: prod had 958 unread rows, 664 of them stale
    task_due / task_assigned reminders. A newer reminder of the same type for
    the same user marks the older unread ones read."""

    async def test_new_task_due_marks_older_unread_task_due_read(
        self, db_session, test_family, test_child_user,
    ):
        old = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_DUE, "yesterday")
        new = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_DUE, "today")
        assert await _is_read(db_session, old.id) is True
        assert await _is_read(db_session, new.id) is False
        refreshed = (await db_session.execute(
            select(Notification).where(Notification.id == old.id)
        )).scalar_one()
        assert refreshed.read_at is not None

    async def test_new_task_assigned_marks_older_task_assigned_read(
        self, db_session, test_family, test_child_user,
    ):
        old = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_ASSIGNED, "last week")
        await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_ASSIGNED, "this week")
        assert await _is_read(db_session, old.id) is True

    async def test_supersede_is_scoped_to_same_user_type_and_family(
        self, db_session, test_family, test_child_user, test_teen_user,
        other_family, other_parent,
    ):
        survivors = [
            await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "other type"),
            await _mk(db_session, test_family.id, test_teen_user.id, NotificationType.TASK_DUE, "other user"),
            await _mk(db_session, test_family.id, None, NotificationType.TASK_DUE, "family-wide"),
            await _mk(db_session, other_family.id, other_parent.id, NotificationType.TASK_DUE, "other family"),
        ]
        await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_DUE, "trigger")
        for n in survivors:
            assert await _is_read(db_session, n.id) is False, n.title

    async def test_other_types_never_supersede(
        self, db_session, test_family, test_child_user,
    ):
        first = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "gig 1")
        await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "gig 2")
        assert await _is_read(db_session, first.id) is False

    async def test_create_no_commit_supersedes_on_commit(
        self, db_session, test_family, test_child_user,
    ):
        old = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_ASSIGNED, "old")
        await NotificationService.create_no_commit(
            db_session, family_id=test_family.id, user_id=test_child_user.id,
            type=NotificationType.TASK_ASSIGNED, title="new",
        )
        await db_session.commit()
        assert await _is_read(db_session, old.id) is True

    async def test_supersede_rolls_back_with_the_new_row(
        self, db_session, test_family, test_child_user,
    ):
        old = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.TASK_DUE, "old")
        old_id = old.id
        await NotificationService.create_no_commit(
            db_session, family_id=test_family.id, user_id=test_child_user.id,
            type=NotificationType.TASK_DUE, title="never committed",
        )
        await db_session.rollback()
        assert await _is_read(db_session, old_id) is False
        rows = (await db_session.execute(
            select(Notification).where(
                Notification.user_id == test_child_user.id,
                Notification.type == NotificationType.TASK_DUE,
            )
        )).scalars().all()
        assert len(rows) == 1


class TestUnreadBadgeWindow:
    async def test_unread_count_ignores_rows_older_than_window(
        self, db_session, test_family, test_child_user,
    ):
        now = datetime.now(timezone.utc)
        fresh = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "fresh")
        edge = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "13 days")
        stale = await _mk(db_session, test_family.id, test_child_user.id, NotificationType.GIG_APPROVED, "15 days")
        await db_session.execute(sa_update(Notification).where(Notification.id == edge.id)
                                 .values(created_at=now - timedelta(days=UNREAD_BADGE_WINDOW_DAYS - 1)))
        await db_session.execute(sa_update(Notification).where(Notification.id == stale.id)
                                 .values(created_at=now - timedelta(days=UNREAD_BADGE_WINDOW_DAYS + 1)))
        await db_session.commit()

        assert await NotificationService.unread_count(db_session, test_child_user.id, test_family.id) == 2
        # Old rows are still in the feed — they just stop inflating the badge.
        feed = await NotificationService.list_for_user(db_session, test_child_user.id, test_family.id)
        assert {n.title for n in feed} >= {fresh.title, edge.title, stale.title}
```

- [ ] **Step 2: Run to verify they fail**

Run: `…/run-backend-tests.sh tests/test_notifications.py -k "Superseding or BadgeWindow"`
Expected: FAIL — `ImportError: cannot import name 'UNREAD_BADGE_WINDOW_DAYS'` (collection error). After Step 3's constants exist but before the logic, the supersede and window tests fail on assertions.

- [ ] **Step 3: Implement** — in `backend/app/services/notification_service.py`, add right after the imports (before `_COPY`):

```python
# Reminder types that go stale the moment a newer one of the same type exists
# for the same user: yesterday's "you have 3 chores today", last week's "you
# have 13 new chores". Creating a new one marks that user's older unread ones
# read, inside the caller's transaction. Prod 2026-09-27: 664 of 958 unread
# rows were these, keeping every badge at 75–214.
SUPERSEDING_TYPES = frozenset({NT.TASK_DUE, NT.TASK_ASSIGNED})

# The unread badge only counts the last N days. Older unread rows stay in the
# feed; they just stop inflating a number nobody can act on.
UNREAD_BADGE_WINDOW_DAYS = 14
```

Inside `class NotificationService`, add (e.g. just above `create`):

```python
    @staticmethod
    async def _supersede_older(
        db: AsyncSession, family_id: UUID, user_id: Optional[UUID], type: str
    ) -> None:
        """Mark the user's older unread reminders of ``type`` read. Runs in the
        caller's transaction, BEFORE the new row is added, so the new row is
        never touched and a rollback restores the old ones."""
        if user_id is None or type not in SUPERSEDING_TYPES:
            return
        await db.execute(
            sql_update(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    Notification.user_id == user_id,
                    Notification.type == type,
                    Notification.is_read.is_(False),
                )
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
```

In `create(...)`, insert as the first statement of the body (before `n = Notification(`):

```python
        await NotificationService._supersede_older(db, family_id, user_id, type)
```

In `create_no_commit(...)`, insert the same line as the first statement of the body (before `n = Notification(`).

In `unread_count(...)`, add to the `and_(...)` conditions, after the `is_read` condition:

```python
                    Notification.created_at
                    >= now - timedelta(days=UNREAD_BADGE_WINDOW_DAYS),
```

- [ ] **Step 4: Run to verify they pass**

Run: `…/run-backend-tests.sh tests/test_notifications.py tests/test_push_subscriptions.py`
Expected: all PASS — including the existing `test_sweep_is_idempotent_per_day` and `test_shuffle_fires_task_assigned_per_assignee`.

- [ ] **Step 5: Mutation checks** — (a) remove the `Notification.user_id == user_id` condition: the scope test must fail. (b) move the `_supersede_older` call in `create` to after `db.add(n)`: `test_new_task_due_marks_older_unread_task_due_read` must fail (the new row gets marked read by autoflush). Restore both.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/notification_service.py backend/tests/test_notifications.py
git commit -m "feat(notifications): newer chore reminders supersede older ones; badge counts 14 days

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Data migration — clear the stale reminder backlog

**Files:**
- Create: `backend/migrations/versions/2026_09_27_mark_stale_reminders_read.py`
- Test: `backend/tests/test_migration_mark_stale_reminders_read.py`

**Interfaces:**
- Consumes: current head revision `jarvis_message_mode` (file `2026_08_03_jarvis_message_mode.py`).
- Produces: new head revision `mark_stale_reminders_read`.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_migration_mark_stale_reminders_read.py`:

```python
"""The mark_stale_reminders_read data migration, exercised against real rows.

Alembic itself is covered by CI's upgrade/round-trip job; this pins the
UPDATE's semantics by running the migration's own SQL on seeded data.
"""
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select, text, update

from app.models.notification import Notification, NotificationType as NT

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_09_27_mark_stale_reminders_read.py"
)


def _migration_sql() -> str:
    spec = importlib.util.spec_from_file_location("mark_stale_reminders_read", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    captured: list[str] = []
    mod.op = SimpleNamespace(execute=lambda sql: captured.append(str(sql)))
    mod.upgrade()
    assert len(captured) == 1
    return captured[0]


def test_revision_chain():
    spec = importlib.util.spec_from_file_location("m", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "mark_stale_reminders_read"
    assert mod.down_revision == "jarvis_message_mode"


async def test_marks_only_old_unread_reminders_read(db_session, test_family, test_child_user):
    now = datetime.now(timezone.utc)
    rows = {
        "old_due": (NT.TASK_DUE, 3, True),
        "new_due": (NT.TASK_DUE, 1, False),
        "old_assigned": (NT.TASK_ASSIGNED, 5, True),
        "old_gig": (NT.GIG_APPROVED, 10, False),
    }
    ids = {}
    for title, (type_, age_days, _) in rows.items():
        n = Notification(
            family_id=test_family.id, user_id=test_child_user.id,
            type=type_, title=title,
        )
        db_session.add(n)
        await db_session.flush()
        await db_session.execute(
            update(Notification).where(Notification.id == n.id)
            .values(created_at=now - timedelta(days=age_days))
        )
        ids[title] = n.id
    await db_session.commit()

    await db_session.execute(text(_migration_sql()))
    await db_session.commit()

    for title, (_, _, should_be_read) in rows.items():
        is_read = (await db_session.execute(
            select(Notification.is_read).where(Notification.id == ids[title])
        )).scalar_one()
        assert bool(is_read) is should_be_read, title
```

- [ ] **Step 2: Run to verify it fails**

Run: `…/run-backend-tests.sh tests/test_migration_mark_stale_reminders_read.py`
Expected: FAIL — `FileNotFoundError` for the migration file.

- [ ] **Step 3: Implement** — create `backend/migrations/versions/2026_09_27_mark_stale_reminders_read.py`:

```python
"""Mark stale chore reminders read (UX-A, 2026-09-27)

task_due ("You have N chores today") and task_assigned ("You have N new
chores") are superseded by the next reminder of the same type — from this
release NotificationService marks older unread ones read when a new one is
created. This clears the backlog from before that rule: prod had 664 such
unread rows out of 958, which kept every user's badge at 75–214.

Data only; no schema change. The reverse step is a no-op: read state is not
restorable and nothing depends on it.

Revision ID: mark_stale_reminders_read
Revises: jarvis_message_mode
Create Date: 2026-09-27
"""
from alembic import op

revision = "mark_stale_reminders_read"
down_revision = "jarvis_message_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notifications
           SET is_read = true, read_at = now()
         WHERE is_read = false
           AND type IN ('task_due', 'task_assigned')
           AND created_at < now() - interval '2 days'
        """
    )


def downgrade() -> None:
    # Irreversible data cleanup — see module docstring.
    pass
```

- [ ] **Step 4: Run to verify it passes**

Run: `…/run-backend-tests.sh tests/test_migration_mark_stale_reminders_read.py`
Expected: PASS.

- [ ] **Step 5: Verify the chain upgrades on a fresh database**

```bash
psql -h 127.0.0.1 -p 5435 -U postgres -c "DROP DATABASE IF EXISTS familyapp_migr;" -c "CREATE DATABASE familyapp_migr OWNER familyapp;"
cd /Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-a-prod-hygiene/backend
DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_migr" /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/alembic upgrade head
DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_migr" /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/alembic heads
```

Expected: upgrade completes; `heads` prints exactly one line, `mark_stale_reminders_read (head)`. (If `env.py` needs a sync driver URL, retry with `postgresql://…` — report which one worked.)

- [ ] **Step 6: Mutation check** — change `interval '2 days'` to `interval '0 days'`: the `new_due` assertion must fail. Restore.

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/versions/2026_09_27_mark_stale_reminders_read.py backend/tests/test_migration_mark_stale_reminders_read.py
git commit -m "chore(db): data migration marks stale chore reminders read

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Jarvis history — strip the actions suffix, format money

**Files:**
- Modify: `backend/app/services/jarvis_service.py` (add `import re`, `split_actions_suffix`, one sentence in `SYSTEM_BASE` and `SYSTEM_TEEN`)
- Modify: `backend/app/api/routes/jarvis.py` (`HistoryItem.actions`, `history` route, import)
- Test: `backend/tests/test_jarvis_history_actions.py` (create)

**Interfaces:**
- Produces: `split_actions_suffix(content: str) -> tuple[str, list[str]]` in `app.services.jarvis_service`; `GET /api/jarvis/history` items gain `actions: list[str]` (default `[]`).
- Storage is unchanged: `JarvisMessage.content` keeps `"\n\n[actions: …]"` because `_load_history` replays it to the model.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_jarvis_history_actions.py`:

```python
"""Jarvis history must not leak the internal "[actions: …]" suffix (UX-A).

The suffix stays in storage — _load_history replays it to the model as
context — but GET /api/jarvis/history returns clean text plus an actions list.
"""
import pytest
from httpx import AsyncClient

from app.models.jarvis_message import JarvisMessage
from app.services.jarvis_service import (
    SYSTEM_BASE,
    SYSTEM_TEEN,
    JarvisService,
    split_actions_suffix,
)


class TestSplitActionsSuffix:
    def test_no_suffix(self):
        assert split_actions_suffix("Hola.") == ("Hola.", [])

    def test_one_action(self):
        assert split_actions_suffix("Listo.\n\n[actions: budget_spending_report(ok)]") == (
            "Listo.", ["budget_spending_report(ok)"],
        )

    def test_many_actions(self):
        text, actions = split_actions_suffix(
            "Hecho.\n\n[actions: shopping_add_item(ok), calendar_create_event(pending), x(err)]"
        )
        assert text == "Hecho."
        assert actions == ["shopping_add_item(ok)", "calendar_create_event(pending)", "x(err)"]

    def test_suffix_like_text_mid_message_is_untouched(self):
        content = "Hecho.\n\n[actions: x(ok)]\nY algo más que dijo el modelo."
        assert split_actions_suffix(content) == (content, [])

    def test_empty(self):
        assert split_actions_suffix("") == ("", [])


def test_prompts_require_formatted_money():
    for prompt in (SYSTEM_BASE, SYSTEM_TEEN):
        assert "thousands separators" in prompt
        assert "$13,849 MXN" in prompt


async def _seed(db, family_id, user_id, role, content):
    db.add(JarvisMessage(family_id=family_id, user_id=user_id, role=role, content=content, mode="copilot"))
    await db.commit()


@pytest.mark.asyncio
async def test_history_endpoint_strips_suffix_and_returns_actions(
    client: AsyncClient, auth_headers, db_session, test_family, test_parent_user,
):
    await _seed(db_session, test_family.id, test_parent_user.id, "user", "¿y [actions: x]?")
    await _seed(
        db_session, test_family.id, None, "assistant",
        "Gastaron $13,849 MXN.\n\n[actions: budget_spending_report(ok)]",
    )
    r = await client.get("/api/jarvis/history", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert [m["content"] for m in items] == ["¿y [actions: x]?", "Gastaron $13,849 MXN."]
    assert items[0]["actions"] == []
    assert items[1]["actions"] == ["budget_spending_report(ok)"]


@pytest.mark.asyncio
async def test_model_history_still_carries_the_suffix(db_session, test_family, test_parent_user):
    await _seed(
        db_session, test_family.id, None, "assistant",
        "Ok.\n\n[actions: budget_spending_report(ok)]",
    )
    rows = await JarvisService.list_history(db_session, test_family.id, user_id=test_parent_user.id)
    assert rows[-1].content.endswith("[actions: budget_spending_report(ok)]")
```

- [ ] **Step 2: Run to verify they fail**

Run: `…/run-backend-tests.sh tests/test_jarvis_history_actions.py`
Expected: FAIL — `ImportError: cannot import name 'split_actions_suffix'`.

- [ ] **Step 3: Implement** — in `backend/app/services/jarvis_service.py`:

Add `import re` next to `import json`.

Append this sentence to the end of the `SYSTEM_BASE` string (inside the parentheses, as a new string literal line):

```python
    " Write money with its currency symbol and thousands separators "
    "(e.g. $13,849 MXN) — never as a bare integer or in cents."
```

Append the same two lines to the end of `SYSTEM_TEEN`.

Add at module level (after `SYSTEM_TEEN`):

```python
# Assistant rows are stored as reply + "\n\n[actions: a(ok), b(pending)]" so
# the model sees what it did when history is replayed. Humans must not.
_ACTIONS_SUFFIX = re.compile(r"\n\n\[actions: ([^\]\n]*)\]\s*\Z")


def split_actions_suffix(content: str) -> tuple[str, list[str]]:
    """Split a stored assistant message into (display text, action labels)."""
    match = _ACTIONS_SUFFIX.search(content or "")
    if not match:
        return content, []
    actions = [a.strip() for a in match.group(1).split(",") if a.strip()]
    return content[: match.start()], actions
```

In `backend/app/api/routes/jarvis.py`: add `split_actions_suffix` to the `from app.services.jarvis_service import (...)` list; add `actions: List[str] = []` to `HistoryItem` (after `mode`); replace the `history` route's `return [...]` line with:

```python
    items: list[HistoryItem] = []
    for row in rows:
        item = HistoryItem.model_validate(row)
        if item.role == "assistant":
            item.content, item.actions = split_actions_suffix(item.content)
        items.append(item)
    return items
```

- [ ] **Step 4: Run to verify they pass**

Run: `…/run-backend-tests.sh tests/test_jarvis_history_actions.py tests/test_jarvis_support.py tests/test_jarvis_sse.py`
Expected: all PASS.

- [ ] **Step 5: Mutation checks** — (a) delete `\Z` from `_ACTIONS_SUFFIX`: `test_suffix_like_text_mid_message_is_untouched` must fail. (b) in the route, replace `split_actions_suffix(item.content)` with `(item.content, [])`: `test_history_endpoint_strips_suffix_and_returns_actions` must fail. Restore both.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/jarvis_service.py backend/app/api/routes/jarvis.py backend/tests/test_jarvis_history_actions.py
git commit -m "fix(jarvis): history hides the internal actions suffix; prompts format money

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Jarvis action chips (frontend)

**Files:**
- Create: `frontend/src/lib/jarvis-actions.ts`
- Modify: `frontend/src/pages/parent/jarvis.astro` (frontmatter import, history render ~L182-190, live chip text ~L462, client-script import ~L221)
- Modify: `frontend/src/pages/soporte.astro` (frontmatter import, history render ~L125-133)
- Test: `frontend/test/jarvis-actions.test.ts`

**Interfaces:**
- Consumes: `GET /api/jarvis/history` items now carry `actions: string[]` (Task 5). Raw labels look like `name(ok|err|pending)`.
- Produces: `formatActionLabel(raw: string): string`.

- [ ] **Step 1: Write the failing test** — create `frontend/test/jarvis-actions.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { formatActionLabel } from "../src/lib/jarvis-actions";

describe("formatActionLabel", () => {
    it("humanizes an ok action", () => {
        expect(formatActionLabel("budget_spending_report(ok)")).toBe("budget spending report ✓");
    });
    it("marks pending actions", () => {
        expect(formatActionLabel("calendar_create_event(pending)")).toBe("calendar create event ⏳");
    });
    it("marks failed actions", () => {
        expect(formatActionLabel("shopping_add_item(err)")).toBe("shopping add item ⚠");
    });
    it("degrades gracefully on an unexpected shape", () => {
        expect(formatActionLabel("  weird_label ")).toBe("weird label");
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/jarvis-actions.test.ts`
Expected: FAIL — cannot resolve `../src/lib/jarvis-actions`.

- [ ] **Step 3: Implement** — create `frontend/src/lib/jarvis-actions.ts`:

```ts
/**
 * Jarvis records each tool it ran as "tool_name(status)", status one of
 * ok | err | pending. Chips show a readable label instead of the raw name.
 */
const MARK: Record<string, string> = { ok: "✓", pending: "⏳" };

export function formatActionLabel(raw: string): string {
    const trimmed = raw.trim();
    const match = /^([\w.-]+)\((\w+)\)$/.exec(trimmed);
    if (!match) return trimmed.replace(/_/g, " ");
    const [, name, status] = match;
    return `${name.replace(/_/g, " ")} ${MARK[status] ?? "⚠"}`;
}
```

In `frontend/src/pages/parent/jarvis.astro`:
1. Frontmatter: add `import { formatActionLabel } from "../../lib/jarvis-actions";` after the `isFreePlan` import.
2. In the SSR `history.map((m: any) => (...))` bubble, directly after `<p class="whitespace-pre-wrap">{m.content}</p>`, add:

```astro
                            {Array.isArray(m.actions) && m.actions.length > 0 && (
                                <div class="mt-2 flex flex-wrap gap-1">
                                    {m.actions.map((a: string) => (
                                        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">⚡ {formatActionLabel(a)}</span>
                                    ))}
                                </div>
                            )}
```

3. In the client `<script>`, next to `import { streamJarvisChat } from "../../lib/jarvis-chat";` add `import { formatActionLabel } from "../../lib/jarvis-actions";`, and change `(el as HTMLElement).textContent = "⚡ " + actions[i];` to `(el as HTMLElement).textContent = "⚡ " + formatActionLabel(actions[i]);`.

In `frontend/src/pages/soporte.astro`: add `import { formatActionLabel } from "../lib/jarvis-actions";` to the frontmatter imports, and add the same chip block (with identical markup) after `<p class="whitespace-pre-wrap">{m.content}</p>` in its `history.map`.

- [ ] **Step 4: Run to verify**

Run: `cd frontend && npx vitest run && npx astro check`
Expected: vitest all PASS; `astro check` reports 0 errors.

- [ ] **Step 5: Mutation check** — change `"✓"` to `"x"` in `MARK`: the ok test must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/jarvis-actions.ts frontend/test/jarvis-actions.test.ts frontend/src/pages/parent/jarvis.astro frontend/src/pages/soporte.astro
git commit -m "feat(jarvis): readable action chips in live replies and history

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Notifications page — day groups, one-tap cards

**Files:**
- Create: `frontend/src/lib/notifications.ts`
- Modify: `frontend/src/pages/notifications.astro` (full list/section markup + POST handler)
- Test: `frontend/test/notifications.test.ts`

**Interfaces:**
- Consumes: `dayKeyInTz(value, tz)` from `frontend/src/lib/datetime.ts`; `/api/auth/me` returns `timezone` (family IANA tz); existing `POST /api/notifications/{id}/read`.
- Produces: `type DayBucket = "today" | "yesterday" | "earlier"`, `groupByDay<T extends { created_at: string }>(items: T[], tz: string | null | undefined, now?: Date): { bucket: DayBucket; items: T[] }[]`, `safeNotificationLink(link: unknown): string`.

- [ ] **Step 1: Write the failing test** — create `frontend/test/notifications.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { groupByDay, safeNotificationLink } from "../src/lib/notifications";

const TZ = "America/Mexico_City"; // UTC-6, no DST since 2022
// 2026-09-27 12:00 local = 18:00Z
const NOW = new Date("2026-09-27T18:00:00Z");

describe("groupByDay", () => {
    it("buckets by the family's local day, not UTC", () => {
        const items = [
            { id: "late-tonight", created_at: "2026-09-28T04:30:00Z" }, // 22:30 local, 27th
            { id: "yesterday", created_at: "2026-09-26T20:00:00Z" },
            { id: "old", created_at: "2026-09-20T12:00:00Z" },
        ];
        const groups = groupByDay(items, TZ, NOW);
        expect(groups.map((g) => g.bucket)).toEqual(["today", "yesterday", "earlier"]);
        expect(groups[0].items.map((i) => i.id)).toEqual(["late-tonight"]);
    });

    it("treats a just-after-midnight-UTC item as the local day before", () => {
        const items = [{ id: "a", created_at: "2026-09-27T03:00:00Z" }]; // 21:00 local on the 26th
        expect(groupByDay(items, TZ, NOW)[0].bucket).toBe("yesterday");
    });

    it("keeps input order within a bucket and drops empty buckets", () => {
        const items = [
            { id: "1", created_at: "2026-09-27T17:00:00Z" },
            { id: "2", created_at: "2026-09-27T15:00:00Z" },
        ];
        const groups = groupByDay(items, TZ, NOW);
        expect(groups).toHaveLength(1);
        expect(groups[0].items.map((i) => i.id)).toEqual(["1", "2"]);
    });

    it("files unparseable timestamps under earlier", () => {
        expect(groupByDay([{ created_at: "garbage" }], TZ, NOW)[0].bucket).toBe("earlier");
    });
});

describe("safeNotificationLink", () => {
    it("keeps same-origin paths", () => {
        expect(safeNotificationLink("/parent/approvals?x=1")).toBe("/parent/approvals?x=1");
    });
    it.each([
        ["https://evil.example/x"],
        ["//evil.example/x"],
        ["/\\evil.example"],
        ["javascript:alert(1)"],
        [""],
        [null],
        [undefined],
    ])("sends %s back to /notifications", (link) => {
        expect(safeNotificationLink(link)).toBe("/notifications");
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/notifications.test.ts`
Expected: FAIL — cannot resolve `../src/lib/notifications`.

- [ ] **Step 3: Implement the helpers** — create `frontend/src/lib/notifications.ts`:

```ts
import { dayKeyInTz } from "./datetime";

export type DayBucket = "today" | "yesterday" | "earlier";

function previousDayKey(key: string): string {
    const [y, m, d] = key.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/** Group feed items under Today / Yesterday / Earlier in the FAMILY timezone
 *  (SSR runs in UTC; a 10 pm Mexico City item is already "tomorrow" in UTC). */
export function groupByDay<T extends { created_at: string }>(
    items: T[],
    tz: string | null | undefined,
    now: Date = new Date(),
): { bucket: DayBucket; items: T[] }[] {
    const today = dayKeyInTz(now, tz);
    const yesterday = previousDayKey(today);
    const buckets: Record<DayBucket, T[]> = { today: [], yesterday: [], earlier: [] };
    for (const item of items) {
        const key = dayKeyInTz(item.created_at, tz);
        // A slightly-ahead server clock can stamp an item "tomorrow": still today.
        const bucket: DayBucket =
            key && key >= today ? "today" : key === yesterday ? "yesterday" : "earlier";
        buckets[bucket].push(item);
    }
    return (["today", "yesterday", "earlier"] as const)
        .filter((b) => buckets[b].length > 0)
        .map((b) => ({ bucket: b, items: buckets[b] }));
}

/** Where tapping a notification may send the browser: same-origin paths only. */
export function safeNotificationLink(link: unknown): string {
    if (typeof link !== "string") return "/notifications";
    const path = link.trim();
    if (!path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) {
        return "/notifications";
    }
    return path;
}
```

- [ ] **Step 4: Run to verify the helpers pass**

Run: `cd frontend && npx vitest run test/notifications.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire the page** — in `frontend/src/pages/notifications.astro`:

(a) Imports: add `import { groupByDay, safeNotificationLink, type DayBucket } from "../lib/notifications";`.

(b) In the POST handler, add a branch before `} else if (action === "read_all") {`:

```ts
    } else if (action === "open") {
        // One tap = read + go. The link is echoed back from the form, so it
        // is guarded to same-origin paths before redirecting.
        const id = data.get("notif_id");
        if (id) {
            await apiFetch(`/api/notifications/${encodeURIComponent(String(id))}/read`, {
                method: "POST",
                token,
            });
        }
        return Astro.redirect(safeNotificationLink(data.get("link")));
```

(c) After `const feed = feedRaw ?? { unread: 0, items: [] };` add:

```ts
const groups = groupByDay(feed.items ?? [], user.timezone);
const bucketLabel: Record<DayBucket, string> = lang === "es"
    ? { today: "Hoy", yesterday: "Ayer", earlier: "Antes" }
    : { today: "Today", yesterday: "Yesterday", earlier: "Earlier" };
const cardClass = (n: any) =>
    `press w-full text-left bg-brand-cream rounded-2xl p-4 border shadow-[var(--shadow-card)] ${
        n.is_read ? "border-brand-ink/10 opacity-75" : "border-brand-ink/30"
    }`;
```

and add `unread_one: lang === "es" ? "Sin leer" : "Unread",` to `labels`.

(d) Replace the whole `<ul class="space-y-2"> … </ul>` block (the non-empty branch) with:

```astro
                <div class="space-y-5">
                    {groups.map((g) => (
                        <section class="space-y-2">
                            <h2 class="px-1 text-xs font-bold uppercase tracking-wider text-brand-ink-soft">
                                {bucketLabel[g.bucket]}
                            </h2>
                            <ul class="space-y-2">
                                {g.items.map((n: any) => (
                                    <li>
                                        <form method="POST">
                                            <input type="hidden" name="action" value="open" />
                                            <input type="hidden" name="notif_id" value={n.id} />
                                            <input type="hidden" name="link" value={n.link ?? ""} />
                                            <button type="submit" class={cardClass(n)}>
                                                <span class="flex items-start gap-3">
                                                    <span class="text-2xl flex-shrink-0" aria-hidden="true">{iconFor(n.type)}</span>
                                                    <span class="flex-1 min-w-0 block">
                                                        <span class="flex items-baseline justify-between gap-2">
                                                            <span class={`text-sm ${n.is_read ? "font-medium text-brand-ink-soft" : "font-bold text-brand-ink"}`}>
                                                                {n.title}
                                                            </span>
                                                            <span class="flex items-center gap-1.5 text-xs text-brand-ink-soft whitespace-nowrap">
                                                                {!n.is_read && (
                                                                    <span class="h-2 w-2 rounded-full bg-brand-coral" role="img" aria-label={labels.unread_one}></span>
                                                                )}
                                                                {timeAgo(n.created_at)}
                                                            </span>
                                                        </span>
                                                        {n.body && (
                                                            <span class="block text-xs text-brand-ink-soft mt-1">{n.body}</span>
                                                        )}
                                                    </span>
                                                </span>
                                            </button>
                                        </form>
                                    </li>
                                ))}
                            </ul>
                        </section>
                    ))}
                </div>
```

(Buttons may only contain phrasing content, hence `<span class="block">` instead of `<p>`/`<div>`.) Keep the "Mark all read" form and the empty state as they are.

- [ ] **Step 6: Run checks**

Run: `cd frontend && npx vitest run && npx astro check`
Expected: all PASS, 0 errors.

- [ ] **Step 7: Mutation checks** — (a) in `safeNotificationLink` delete the `path.startsWith("//")` clause: the `//evil.example/x` case must fail. (b) in `groupByDay` replace `dayKeyInTz(item.created_at, tz)` with `item.created_at.slice(0, 10)`: the local-day test must fail. Restore both.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/notifications.ts frontend/test/notifications.test.ts frontend/src/pages/notifications.astro
git commit -m "feat(notifications): group by local day, tap a card to read and open it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Enable-push button states + stale-subscription healing

**Files:**
- Modify: `frontend/src/components/EnablePushButton.astro` (full rewrite below)

**Interfaces:**
- Consumes: `GET /api/push/public-key` (`{ public_key }` or 503), `POST /api/push/subscribe` (upsert, idempotent), `/sw.js`.
- Used by: `pages/dashboard.astro` and `pages/parent/index.astro` (props unchanged: `lang`). `layouts/Layout.astro` only mentions it in a comment.

- [ ] **Step 1: Replace the component** — write `frontend/src/components/EnablePushButton.astro` as:

```astro
---
/**
 * Push opt-in, shown only when there is something useful to show (UX-A):
 *   - iOS Safari tab (no PushManager until installed) → install hint
 *   - other browsers without push → nothing
 *   - permission denied → one-line note
 *   - server has no push key → nothing
 *   - already subscribed with the CURRENT server key → nothing (and the
 *     subscription is re-posted at most daily, so a row the server pruned
 *     comes back)
 *   - subscribed with an OLD server key → unsubscribed, button offered
 *     (every send to it would 403 forever)
 *   - otherwise → the button
 */
interface Props {
    lang: string;
}
const { lang } = Astro.props;

const L = lang === "es"
    ? {
        enable: "Activar notificaciones",
        enabled: "Notificaciones activas",
        denied: "Permiso denegado",
        err: "Error",
        install: "Para recibir avisos, instala la app: Compartir → Agregar a inicio.",
        blocked: "Avisos bloqueados en este navegador.",
    }
    : {
        enable: "Enable push notifications",
        enabled: "Notifications enabled",
        denied: "Permission denied",
        err: "Error",
        install: "To get alerts, install the app: Share → Add to Home Screen.",
        blocked: "Notifications are blocked in this browser.",
    };
---

<div id="push-root" hidden>
    <button
        id="enable-push-btn"
        type="button"
        hidden
        class="px-3 py-2 rounded-lg border border-brand-sky text-brand-sky-deep text-sm font-medium hover:bg-brand-sky/10 transition-colors disabled:opacity-60"
        data-state="idle"
    >
        {L.enable}
    </button>
    <span id="push-status" class="text-xs text-brand-ink-soft ml-2" aria-live="polite"></span>
</div>

<script define:vars={{ L }}>
    const root = document.getElementById("push-root");
    const btn = document.getElementById("enable-push-btn");
    const status = document.getElementById("push-status");
    const HEAL_KEY = "ftm-push-heal-at";
    let publicKey = null;

    function setStatus(msg, color = "text-brand-ink-soft") {
        status.textContent = msg;
        status.className = `text-xs ${color} ml-2`;
    }

    function urlBase64ToUint8Array(b64) {
        const padding = "=".repeat((4 - (b64.length % 4)) % 4);
        const padded = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
        const raw = atob(padded);
        const arr = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
        return arr;
    }

    function sameKey(buf, b64) {
        if (!buf || !b64) return false;
        const a = new Uint8Array(buf);
        const b = urlBase64ToUint8Array(b64);
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    function postSubscription(sub) {
        const json = sub.toJSON();
        return fetch("/api/push/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                endpoint: json.endpoint,
                keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
            }),
        });
    }

    async function healDaily(sub) {
        try {
            const last = Number(localStorage.getItem(HEAL_KEY) || "0");
            if (Date.now() - last < 86400000) return;
            const r = await postSubscription(sub);
            if (r.ok) localStorage.setItem(HEAL_KEY, String(Date.now()));
        } catch (_) {}
    }

    async function decide() {
        const standalone = window.matchMedia("(display-mode: standalone)").matches
            || navigator.standalone === true;
        const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
            || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
        const supported = "serviceWorker" in navigator
            && "PushManager" in window
            && "Notification" in window;

        if (!supported) {
            // iOS exposes Web Push only to Home Screen apps.
            if (isIOS && !standalone) {
                setStatus(L.install);
                root.hidden = false;
            }
            return;
        }
        if (Notification.permission === "denied") {
            setStatus(L.blocked);
            root.hidden = false;
            return;
        }
        try {
            const keyResp = await fetch("/api/push/public-key");
            if (!keyResp.ok) return;
            publicKey = (await keyResp.json()).public_key;
            const reg = await navigator.serviceWorker.register("/sw.js");
            const existing = await reg.pushManager.getSubscription();
            if (existing) {
                if (sameKey(existing.options.applicationServerKey, publicKey)) {
                    await healDaily(existing);
                    return;
                }
                await existing.unsubscribe().catch(() => {});
            }
        } catch (_) {
            return;
        }
        btn.hidden = false;
        root.hidden = false;
    }

    btn.addEventListener("click", async () => {
        btn.disabled = true;
        setStatus("…");
        try {
            if (!publicKey) {
                const keyResp = await fetch("/api/push/public-key");
                if (!keyResp.ok) throw new Error("no key");
                publicKey = (await keyResp.json()).public_key;
            }
            // register() is idempotent and, unlike serviceWorker.ready, its
            // failure is catchable — a broken registration surfaces as an error.
            const reg = await navigator.serviceWorker.register("/sw.js");
            await navigator.serviceWorker.ready;
            const sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey),
            });
            const r = await postSubscription(sub);
            if (r.ok) {
                try { localStorage.setItem(HEAL_KEY, String(Date.now())); } catch (_) {}
                setStatus(L.enabled, "text-green-700");
                btn.setAttribute("data-state", "enabled");
                btn.hidden = true;
            } else {
                setStatus(L.err, "text-red-700");
                btn.disabled = false;
            }
        } catch (e) {
            console.error(e);
            const msg = e?.name === "NotAllowedError" ? L.denied : L.err;
            setStatus(msg, "text-red-700");
            btn.disabled = false;
        }
    });

    decide();
</script>
```

- [ ] **Step 2: Run checks**

Run: `cd frontend && npx astro check && npx astro build`
Expected: 0 errors; build succeeds.

- [ ] **Step 3: Manual verification** (dev server: `cd frontend && npx astro dev --port 4321`, backend not required for the first two):
  1. Desktop Chrome, fresh profile: component shows only if `/api/push/public-key` answers 2xx — with no backend it must show nothing (not an error).
  2. Emulate iPhone Safari UA (DevTools device mode) where `PushManager` is absent: the install hint text shows, no button.
  3. In DevTools console on a page with the component: `Notification.permission` → if you block notifications for the origin and reload, only the "blocked" note shows.
  Record what you observed for each in the task report. If a case cannot be exercised locally, say so plainly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EnablePushButton.astro
git commit -m "feat(push): opt-in only where useful; replace subscriptions made with an old key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Kiosk unpaired / unavailable page

**Files:**
- Create: `frontend/src/lib/kiosk-unpaired.ts`
- Modify: `frontend/src/pages/kiosk.astro:11-23` (token/snapshot failure handling; move `lang` up)
- Test: `frontend/test/kiosk-unpaired.test.ts`

**Interfaces:**
- Produces: `type UnpairedReason = "missing" | "invalid" | "unavailable"`, `kioskFailureReason(apiStatus: number | null | undefined): UnpairedReason` (for a failed snapshot), `kioskUnpairedStatus(reason: UnpairedReason, apiStatus?: number | null): number`, `renderKioskUnpaired(opts: { lang: string; reason: UnpairedReason; signedIn: boolean }): string` (a complete HTML document).

- [ ] **Step 1: Write the failing test** — create `frontend/test/kiosk-unpaired.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
    kioskFailureReason,
    kioskUnpairedStatus,
    renderKioskUnpaired,
} from "../src/lib/kiosk-unpaired";

describe("kioskFailureReason", () => {
    it("treats auth-ish statuses as an invalid link", () => {
        expect(kioskFailureReason(401)).toBe("invalid");
        expect(kioskFailureReason(403)).toBe("invalid");
        expect(kioskFailureReason(404)).toBe("invalid");
    });
    it("treats a down backend as unavailable, not an expired link", () => {
        expect(kioskFailureReason(0)).toBe("unavailable");
        expect(kioskFailureReason(undefined)).toBe("unavailable");
        expect(kioskFailureReason(502)).toBe("unavailable");
    });
});

describe("kioskUnpairedStatus", () => {
    it("maps reasons to HTTP statuses", () => {
        expect(kioskUnpairedStatus("missing")).toBe(400);
        expect(kioskUnpairedStatus("invalid", 404)).toBe(404);
        expect(kioskUnpairedStatus("invalid", undefined)).toBe(401);
        expect(kioskUnpairedStatus("unavailable", 502)).toBe(503);
    });
});

describe("renderKioskUnpaired", () => {
    it("defaults to Spanish and sends a signed-in parent to pairing", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "missing", signedIn: true });
        expect(html.startsWith("<!doctype html>")).toBe(true);
        expect(html).toContain('lang="es"');
        expect(html).toContain("Esta pantalla no está vinculada");
        expect(html).toContain('href="/parent/kiosk"');
        expect(html).not.toContain("Missing token");
    });
    it("sends a signed-out visitor to login", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "invalid", signedIn: false });
        expect(html).toContain('href="/login"');
        expect(html).toContain("expiró");
    });
    it("renders English", () => {
        const html = renderKioskUnpaired({ lang: "en", reason: "missing", signedIn: false });
        expect(html).toContain('lang="en"');
        expect(html).toContain("This screen isn't paired");
    });
    it("offers a retry, not pairing, when the backend is down", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "unavailable", signedIn: true });
        expect(html).toContain("location.reload()");
        expect(html).not.toContain("/parent/kiosk");
    });
    it("falls back to Spanish for unknown languages", () => {
        expect(renderKioskUnpaired({ lang: "fr", reason: "missing", signedIn: false })).toContain('lang="es"');
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/kiosk-unpaired.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `frontend/src/lib/kiosk-unpaired.ts`:

```ts
/**
 * Standalone page for /kiosk when it cannot show a board: no token, a bad or
 * revoked token, or a backend that is down (e.g. a wall tablet mid-deploy).
 * Returned as a plain HTML string because /kiosk bails out before its own
 * template renders. Only constant copy is interpolated — no user input.
 */
export type UnpairedReason = "missing" | "invalid" | "unavailable";

const COPY = {
    es: {
        unpairedTitle: "Esta pantalla no está vinculada",
        unavailableTitle: "Tablero no disponible",
        missing: "Abre el enlace de kiosko desde Ajustes → Kiosko en el teléfono de un papá o mamá.",
        invalid: "El enlace de kiosko expiró o fue revocado. Genera uno nuevo en Ajustes → Kiosko.",
        unavailable: "No pudimos cargar el tablero. Intenta de nuevo en un momento.",
        pair: "Vincular esta pantalla",
        login: "Iniciar sesión",
        retry: "Reintentar",
    },
    en: {
        unpairedTitle: "This screen isn't paired",
        unavailableTitle: "Board unavailable",
        missing: "Open the kiosk link from Settings → Kiosk on a parent's phone.",
        invalid: "This kiosk link expired or was revoked. Create a new one in Settings → Kiosk.",
        unavailable: "We couldn't load the board. Try again in a moment.",
        pair: "Pair this screen",
        login: "Sign in",
        retry: "Try again",
    },
} as const;

export function kioskFailureReason(apiStatus: number | null | undefined): UnpairedReason {
    return !apiStatus || apiStatus >= 500 ? "unavailable" : "invalid";
}

export function kioskUnpairedStatus(reason: UnpairedReason, apiStatus?: number | null): number {
    if (reason === "missing") return 400;
    if (reason === "unavailable") return 503;
    return apiStatus && apiStatus >= 400 && apiStatus < 500 ? apiStatus : 401;
}

export function renderKioskUnpaired(opts: {
    lang: string;
    reason: UnpairedReason;
    signedIn: boolean;
}): string {
    const htmlLang = opts.lang === "en" ? "en" : "es";
    const c = COPY[htmlLang];
    const title = opts.reason === "unavailable" ? c.unavailableTitle : c.unpairedTitle;
    const action = opts.reason === "unavailable"
        ? `<button type="button" onclick="location.reload()">${c.retry}</button>`
        : `<a href="${opts.signedIn ? "/parent/kiosk" : "/login"}">${opts.signedIn ? c.pair : c.login}</a>`;
    return `<!doctype html>
<html lang="${htmlLang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${title}</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F1A24;color:#FFF8F0;font-family:Nunito,ui-sans-serif,system-ui,sans-serif}
main{max-width:28rem;padding:2rem;text-align:center}
.icon{font-size:3.5rem;line-height:1}
h1{font-family:"Plus Jakarta Sans",ui-sans-serif,system-ui,sans-serif;font-weight:800;font-size:1.75rem;margin:1rem 0 .5rem}
p{color:#A8C3D4;margin:0 0 1.5rem;line-height:1.5}
a,button{display:inline-block;background:#FF8A65;color:#1F2937;font:inherit;font-weight:800;padding:.85rem 1.5rem;border-radius:999px;border:2px solid #1F2937;box-shadow:4px 4px 0 #1F2937;text-decoration:none;cursor:pointer}
</style>
</head>
<body>
<main>
<div class="icon" aria-hidden="true">📺</div>
<h1>${title}</h1>
<p>${c[opts.reason]}</p>
${action}
</main>
</body>
</html>`;
}
```

In `frontend/src/pages/kiosk.astro`, add `import { kioskFailureReason, kioskUnpairedStatus, renderKioskUnpaired, type UnpairedReason } from "../lib/kiosk-unpaired";` to the imports, and replace lines from `const token = Astro.url.searchParams.get("token");` through `const lang = Astro.cookies.get("lang")?.value ?? "es";` with:

```ts
const lang = Astro.cookies.get("lang")?.value ?? "es";
const signedIn = Boolean(Astro.cookies.get("access_token")?.value);
const unpaired = (reason: UnpairedReason, apiStatus?: number) =>
    new Response(renderKioskUnpaired({ lang, reason, signedIn }), {
        status: kioskUnpairedStatus(reason, apiStatus),
        headers: { "Content-Type": "text/html; charset=utf-8" },
    });

const token = Astro.url.searchParams.get("token");
if (!token) {
    return unpaired("missing");
}

const { data, ok, status } = await apiFetch<any>(
    `/api/kiosk/snapshot?token=${encodeURIComponent(token)}`,
);
if (!ok || !data) {
    return unpaired(kioskFailureReason(status), status);
}
```

(The original `const lang = …` line after the snapshot check must be deleted — it now lives at the top.)

- [ ] **Step 4: Run checks**

Run: `cd frontend && npx vitest run && npx astro check`
Expected: all PASS, 0 errors.

- [ ] **Step 5: Mutation check** — in `kioskFailureReason` change `>= 500` to `>= 600`: the 502 case must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/kiosk-unpaired.ts frontend/test/kiosk-unpaired.test.ts frontend/src/pages/kiosk.astro
git commit -m "fix(kiosk): friendly unpaired/unavailable page instead of raw 'Missing token'

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Routines discoverability

**Files:**
- Create: `frontend/src/lib/routines.ts`
- Modify: `frontend/src/components/MoreSheet.astro` (icon + kid link + parent link)
- Modify: `frontend/src/pages/dashboard.astro` (4th parallel fetch; strip inside the header after the greeting row)
- Test: `frontend/test/routines.test.ts`

**Interfaces:**
- Consumes: `GET /api/routines/today` → `{ routines: [{ id, name, name_es, icon, time_of_day, sort_order, steps_done, total_steps, completed, … }], color }`.
- Produces: `interface DashboardRoutine`, `pickDashboardRoutines(routines: unknown, max?: number): DashboardRoutine[]`, `routineName(r: DashboardRoutine, lang: string): string`, `routineProgress(r: DashboardRoutine): string`.

- [ ] **Step 1: Write the failing test** — create `frontend/test/routines.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { pickDashboardRoutines, routineName, routineProgress } from "../src/lib/routines";

const r = (over: Record<string, unknown>) => ({
    id: "x", name: "Routine", name_es: "Rutina", icon: "⭐", time_of_day: "custom",
    sort_order: 0, steps_done: 0, total_steps: 3, completed: false, ...over,
});

describe("pickDashboardRoutines", () => {
    it("returns [] for anything that is not an array", () => {
        expect(pickDashboardRoutines(null)).toEqual([]);
        expect(pickDashboardRoutines({ routines: [] })).toEqual([]);
    });
    it("orders morning, evening, then the rest, and caps at two", () => {
        const picked = pickDashboardRoutines([
            r({ id: "c", time_of_day: "custom" }),
            r({ id: "e", time_of_day: "evening" }),
            r({ id: "m", time_of_day: "morning" }),
        ]);
        expect(picked.map((x) => x.id)).toEqual(["m", "e"]);
    });
    it("uses sort_order within the same time of day", () => {
        const picked = pickDashboardRoutines([
            r({ id: "m2", time_of_day: "morning", sort_order: 2 }),
            r({ id: "m1", time_of_day: "morning", sort_order: 1 }),
        ]);
        expect(picked.map((x) => x.id)).toEqual(["m1", "m2"]);
    });
    it("skips routines with no steps", () => {
        expect(pickDashboardRoutines([r({ total_steps: 0 })])).toEqual([]);
    });
});

describe("routineName / routineProgress", () => {
    it("localizes with a fallback to the base name", () => {
        expect(routineName(r({}), "es")).toBe("Rutina");
        expect(routineName(r({ name_es: null }), "es")).toBe("Routine");
        expect(routineName(r({}), "en")).toBe("Routine");
    });
    it("shows a fraction until done, then a check", () => {
        expect(routineProgress(r({ steps_done: 2, total_steps: 5 }))).toBe("2/5");
        expect(routineProgress(r({ steps_done: 5, total_steps: 5, completed: true }))).toBe("✓");
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/routines.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper** — create `frontend/src/lib/routines.ts`:

```ts
/** Kid-dashboard strip for icon tap-through routines (UX-A): at most two,
 *  morning first, then evening, then the rest. */
export interface DashboardRoutine {
    id: string;
    name: string;
    name_es?: string | null;
    icon?: string | null;
    time_of_day?: string | null;
    sort_order?: number | null;
    steps_done: number;
    total_steps: number;
    completed: boolean;
}

const TIME_RANK: Record<string, number> = { morning: 0, evening: 1 };
const rank = (r: DashboardRoutine) => TIME_RANK[r.time_of_day ?? ""] ?? 2;

export function pickDashboardRoutines(routines: unknown, max = 2): DashboardRoutine[] {
    if (!Array.isArray(routines)) return [];
    return (routines as DashboardRoutine[])
        .filter((r) => (r?.total_steps ?? 0) > 0)
        .sort((a, b) => rank(a) - rank(b) || (a.sort_order ?? 0) - (b.sort_order ?? 0))
        .slice(0, max);
}

export function routineName(r: DashboardRoutine, lang: string): string {
    return lang === "es" ? r.name_es || r.name : r.name;
}

export function routineProgress(r: DashboardRoutine): string {
    return r.completed ? "✓" : `${r.steps_done}/${r.total_steps}`;
}
```

- [ ] **Step 4: Run to verify**

Run: `cd frontend && npx vitest run test/routines.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire the More sheet** — in `frontend/src/components/MoreSheet.astro`:
  - add to the `I` icon map: `routines: "M12 3v1m6.36 1.64l-.7.7M21 12h-1M4 12H3m2.34-6.36l.7.7M8 12a4 4 0 118 0M4 16h16M7 20h10",`
  - in `kidLinks`, directly after `inbox,` add `{ href: "/routines", label: es ? "Rutinas" : "Routines", icon: I.routines },`
  - in `parentLinks`, directly after the `/parent/tasks` entry add `{ href: "/parent/routines", label: es ? "Rutinas" : "Routines", icon: I.routines },`

- [ ] **Step 6: Wire the kid dashboard** — in `frontend/src/pages/dashboard.astro`:
  - add `import { pickDashboardRoutines, routineName, routineProgress } from "../lib/routines";` to the imports;
  - extend the `Promise.all` destructuring and list to a 4th entry:

```ts
const [{ data: user, ok: userOk }, { data: progress }, { data: familyCup }, { data: routinesToday }] = await Promise.all([
    apiFetch<any>("/api/auth/me", { token }),
    apiFetch<any>("/api/task-assignments/progress", { token }),
    apiFetch<any>("/api/family-cup/", { token }),
    // Icon tap-through routines. apiFetch never throws; null → no strip.
    apiFetch<any>("/api/routines/today", { token }),
]);
```

  - after `const boss = familyCup?.boss ?? null;` add `const dashboardRoutines = pickDashboardRoutines(routinesToday?.routines);`
  - inside `<header slot="header" …>`, directly after the greeting row (the `<div class="flex justify-between items-center mb-6">…</div>` that holds "Hello" + the avatar circle) and before the points card, insert:

```astro
            {dashboardRoutines.length > 0 && (
                <div class="mb-4 space-y-2" data-routines-strip>
                    {dashboardRoutines.map((r) => (
                        <a
                            href="/routines"
                            class="press flex items-center gap-3 rounded-2xl bg-brand-cream/20 border border-white/30 px-4 py-3"
                        >
                            <span class="text-2xl leading-none" aria-hidden="true">{r.icon || "⭐"}</span>
                            <span class="flex-1 font-bold">{routineName(r, lang)}</span>
                            <span class="text-sm font-extrabold tabular-nums">{routineProgress(r)}</span>
                            <svg class="h-4 w-4 opacity-80" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7" />
                            </svg>
                        </a>
                    ))}
                </div>
            )}
```

- [ ] **Step 7: Run checks**

Run: `cd frontend && npx vitest run && npx astro check`
Expected: all PASS, 0 errors.

- [ ] **Step 8: Mutation check** — remove the `.filter(...)` line in `pickDashboardRoutines`: the "skips routines with no steps" test must fail. Restore.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/routines.ts frontend/test/routines.test.ts frontend/src/components/MoreSheet.astro frontend/src/pages/dashboard.astro
git commit -m "feat(routines): reachable from More sheets; today's routines on the kid dashboard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: CSP allows Cloudflare Web Analytics; privacy notice says so

**Files:**
- Create: `frontend/src/lib/security/csp.ts` (the CSP string + its explanatory comment, moved out of middleware)
- Modify: `frontend/src/middleware.ts:18-43` (delete the local `CSP` const + comment; import it)
- Modify: `frontend/src/pages/privacidad.astro` (Cloudflare processor line, ES ~L110 and EN ~L221)
- Test: `frontend/test/csp.test.ts`

**Interfaces:**
- Produces: `export const CSP: string` in `frontend/src/lib/security/csp.ts`. `middleware.ts` keeps using the name `CSP` unchanged.

- [ ] **Step 1: Write the failing test** — create `frontend/test/csp.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { CSP } from "../src/lib/security/csp";

const directive = (name: string) =>
    CSP.split("; ").find((d) => d.startsWith(`${name} `)) ?? "";

describe("CSP", () => {
    it("lets the Cloudflare Web Analytics beacon load", () => {
        expect(directive("script-src")).toContain("https://static.cloudflareinsights.com");
    });
    it("lets the beacon report", () => {
        expect(directive("connect-src")).toContain("https://cloudflareinsights.com");
    });
    it("keeps Google Sign-In working", () => {
        expect(directive("script-src")).toContain("https://accounts.google.com");
        expect(directive("frame-src")).toContain("https://accounts.google.com");
    });
    it("keeps the strict defaults", () => {
        expect(directive("default-src")).toBe("default-src 'self'");
        expect(directive("frame-ancestors")).toBe("frame-ancestors 'none'");
        expect(directive("object-src")).toBe("object-src 'none'");
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/csp.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `frontend/src/lib/security/csp.ts` with exactly this content (the first comment lines are moved from `middleware.ts`; the Cloudflare bullet and the two new sources are the change):

```ts
// ---------------------------------------------------------------------------
// Security headers (WS-F1). Starter CSP notes:
// - The browser talks to the backend ONLY through same-origin Astro proxy
//   routes (/api/*, /uploads/*) — no page fetches api-family.agent-ia.mx
//   directly — so connect-src stays 'self' plus accounts.google.com (Google
//   Identity Services pings its own origin from the GSI client script).
// - Astro emits inline <script> tags → script-src needs 'unsafe-inline'.
// - Google Sign-In: script + iframe + stylesheet from accounts.google.com.
// - Fonts: Google Fonts stylesheet (fonts.googleapis.com) + files (gstatic).
// - img-src blob:/data: for camera-capture previews (receipt/proof upload).
// - frame-ancestors 'none' + X-Frame-Options DENY: nothing embeds this app
//   (the kiosk page is opened directly, never iframed).
// - Cloudflare Web Analytics (cookieless page views + Web Vitals, injected by
//   Cloudflare at the edge): beacon script from static.cloudflareinsights.com,
//   reports to cloudflareinsights.com. Disclosed in /privacidad (UX-A).
// CSP is only sent in production: dev needs Vite HMR websockets/eval, and
// guarding it here keeps local DX untouched.
export const CSP = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://accounts.google.com https://static.cloudflareinsights.com",
    "style-src 'self' 'unsafe-inline' https://accounts.google.com https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self' https://accounts.google.com https://cloudflareinsights.com",
    "frame-src https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
].join("; ");
```

In `frontend/src/middleware.ts`: delete that comment block and the `const CSP = [...].join("; ");` statement, and add `import { CSP } from "./lib/security/csp";` beside the existing `./lib/security/request-guards` import (with a one-line comment: `// CSP string + rationale: lib/security/csp.ts (unit-tested).`).

In `frontend/src/pages/privacidad.astro`, change the ES line
`"Cloudflare (EE. UU.) — red de entrega, seguridad y túnel de conexión del sitio.",`
to
`"Cloudflare (EE. UU.) — red de entrega, seguridad, túnel de conexión del sitio y medición anónima y agregada de visitas y rendimiento (Cloudflare Web Analytics, sin cookies).",`
and the EN line
`"Cloudflare (USA) — content delivery, security, and the site's connection tunnel.",`
to
`"Cloudflare (USA) — content delivery, security, the site's connection tunnel, and anonymous, aggregate visit and performance measurement (Cloudflare Web Analytics, cookieless).",`

- [ ] **Step 4: Run checks**

Run: `cd frontend && npx vitest run && npx astro check`
Expected: all PASS (including the existing `request-guards` tests), 0 errors.

- [ ] **Step 5: Mutation check** — remove `https://cloudflareinsights.com` from `connect-src`: the "lets the beacon report" test must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/security/csp.ts frontend/test/csp.test.ts frontend/src/middleware.ts frontend/src/pages/privacidad.astro
git commit -m "fix(csp): allow Cloudflare Web Analytics beacon; disclose it in the privacy notice

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Branch verification, PR, deploy (controller)

- [ ] **Step 1: Full backend suite** — controller only, backgrounded to a file:
  `…/run-backend-tests.sh tests/ > $SCRATCH/full-suite.log 2>&1` (with `run_in_background`; if the 540 s cap in the script is too short, run it with a larger `timeout` via a copy of the script). Then `grep -E "passed|failed|error" $SCRATCH/full-suite.log | tail`. Skip nothing except `tests/test_jarvis_models.py` if it needs a live LLM.
- [ ] **Step 2: Lint** — `cd backend && /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/ruff check app` → 0 findings.
- [ ] **Step 3: Frontend** — `cd frontend && npx vitest run && npx astro check && npx astro build`.
- [ ] **Step 4: Local UI pass** — Playwright against `npx astro dev` with the backend unavailable is limited; at minimum load `/kiosk` (no token) and confirm the friendly page renders with status 400.
- [ ] **Step 5: Whole-branch review** — adversarial review of `git diff origin/main...HEAD` (per memory: fixes get reviewed as a branch, not only per task).
- [ ] **Step 6: PR** — push, `gh pr create` with `--body-file` (the body must not contain the guarded alembic phrase inline in the command), watch CI, merge explicitly (no `--auto`).
- [ ] **Step 7: Deploy + verify on prod** — `./scripts/deploy-onprem.sh` from a clean checkout of merged `main`; then verify the seven success criteria from the spec (demo family, read-only) and `podman logs` for `push send … reason=` / `pruning push endpoint`. Record results in `logs/SESSION-WORKLOG.md`.
