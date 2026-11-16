"""Member display preferences — per-member color + kiosk PIN (P1-KIOSK).

Storage: the `users` table has no JSON/preferences column and adding one
requires a migration, so these low-stakes display prefs follow the existing
per-family Redis settings precedent (see `budget/ai_settings.py`, key
`family_settings:{family_id}:receipt_model`).

Key layout: one Redis HASH per family —
    family_settings:{family_id}:member_prefs
        field  = str(user_id)
        value  = JSON {"color": "<palette name>", "pin_hash": "<bcrypt>"}

Loss tolerance: if Redis is ever flushed, colors fall back to the
deterministic palette assignment below (still stable per user), and kiosk
PINs simply need to be re-set by a parent. Nothing security-critical lives
here — the kiosk device itself is already token-gated; the PIN only scopes
WHICH kid's view shows on a shared wall tablet.
"""

import json
from typing import Dict, Optional, Tuple
from uuid import UUID

from app.core.config import settings
from app.core.security import get_password_hash, verify_password

# Brand palette (docs/design-tokens.md — Colors table). Keys are the
# `--color-brand-*` token suffixes; values are the canonical hex.
MEMBER_COLORS: Dict[str, str] = {
    "sky": "#4FB8E6",
    "coral": "#FF8A65",
    "mint": "#5DD4A8",
    "sun": "#FFC857",
    "sky-deep": "#2E9BCC",
    "coral-deep": "#E96A45",
    "mint-deep": "#3DB689",
    "sun-deep": "#E5A91F",
}
_COLOR_ORDER = list(MEMBER_COLORS.keys())

# PIN brute-force guard: max failures per (device, member) inside the window.
PIN_MAX_FAILURES = 5
PIN_FAILURE_WINDOW_SECONDS = 300


def _prefs_key(family_id) -> str:
    return f"family_settings:{family_id}:member_prefs"


def _fail_key(device_id, user_id) -> str:
    return f"kiosk_pin_fails:{device_id}:{user_id}"


def _switch_pair_key(home_user_id, member_id) -> str:
    return f"switch_pin_fails:pair:{home_user_id}:{member_id}"


def _switch_member_key(member_id) -> str:
    return f"switch_pin_fails:member:{member_id}"


# KEYS[1] = member key, KEYS[2] = pair key. DECR only an existing positive
# counter (DECR keeps the TTL; DECR on a missing key would create -1 with
# none), then drop the pair key.
_REFUND_LUA = """
local v = tonumber(redis.call('GET', KEYS[1]) or '0')
if v and v > 0 then
    redis.call('DECR', KEYS[1])
end
redis.call('DEL', KEYS[2])
return 1
"""


async def _redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def default_color_name(user_id) -> str:
    """Deterministic palette assignment — stable per user, no storage."""
    return _COLOR_ORDER[UUID(str(user_id)).int % len(_COLOR_ORDER)]


def resolve_color_name(user_id, prefs: Optional[dict]) -> str:
    """Stored override if valid, else the deterministic default."""
    name = (prefs or {}).get("color")
    if name in MEMBER_COLORS:
        return name
    return default_color_name(user_id)


def color_hex(name: str) -> str:
    return MEMBER_COLORS.get(name, MEMBER_COLORS["sky"])


class MemberPrefsService:
    @staticmethod
    async def get_family_prefs(family_id) -> Dict[str, dict]:
        """All stored prefs for a family: {user_id_str: {...}}."""
        r = await _redis()
        try:
            raw = await r.hgetall(_prefs_key(family_id))
        finally:
            await r.aclose()
        out: Dict[str, dict] = {}
        for uid, blob in (raw or {}).items():
            try:
                val = json.loads(blob)
                if isinstance(val, dict):
                    out[uid] = val
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    async def update_member_prefs(
        family_id,
        user_id,
        *,
        color: Optional[str] = None,
        pin: Optional[str] = None,
    ) -> dict:
        """Merge-update one member's prefs.

        color: palette name (caller validates against MEMBER_COLORS).
        pin:   "1234" sets (stored bcrypt-hashed); "" clears; None = untouched.
        """
        r = await _redis()
        key = _prefs_key(family_id)
        field = str(user_id)
        try:
            raw = await r.hget(key, field)
            current: dict = {}
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        current = parsed
                except (TypeError, ValueError):
                    current = {}
            if color is not None:
                current["color"] = color
            if pin is not None:
                if pin == "":
                    current.pop("pin_hash", None)
                else:
                    current["pin_hash"] = get_password_hash(pin)
            await r.hset(key, field, json.dumps(current))
        finally:
            await r.aclose()
        return current

    @staticmethod
    async def verify_member_pin(family_id, user_id, pin: str) -> Optional[bool]:
        """True/False if a PIN is set; None if the member has no PIN."""
        prefs = await MemberPrefsService.get_family_prefs(family_id)
        entry = prefs.get(str(user_id)) or {}
        pin_hash = entry.get("pin_hash")
        if not pin_hash:
            return None
        try:
            return bool(verify_password(pin, pin_hash))
        except (ValueError, TypeError):
            return False

    # ── PIN failure throttle (per device+member, self-expiring) ─────────

    @staticmethod
    async def pin_failures(device_id, user_id) -> int:
        r = await _redis()
        try:
            val = await r.get(_fail_key(device_id, user_id))
        finally:
            await r.aclose()
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    async def record_pin_failure(device_id, user_id) -> int:
        r = await _redis()
        key = _fail_key(device_id, user_id)
        try:
            count = await r.incr(key)
            await r.expire(key, PIN_FAILURE_WINDOW_SECONDS)
        finally:
            await r.aclose()
        return int(count)

    @staticmethod
    async def clear_pin_failures(device_id, user_id) -> None:
        r = await _redis()
        try:
            await r.delete(_fail_key(device_id, user_id))
        finally:
            await r.aclose()

    # ── Profile-switch PIN throttle (UX-E4) ─────────────────────────────
    # Two counters: (home parent, member) and member-wide. The member-wide
    # one stops an attacker from dodging the lock by rotating home sessions.
    #
    # RESERVE FIRST: every attempt is counted BEFORE the PIN is checked, in
    # one MULTI/EXEC (INCR + EXPIRE on both keys), and the caller refuses the
    # attempt when either count is over PIN_MAX_FAILURES. A read-then-check-
    # then-increment gate let N concurrent requests all pass the read, and a
    # separate INCR/EXPIRE could leave a key with no TTL (member locked
    # forever) if the process died in between. A successful PIN refunds its
    # own reservation; a wrong PIN needs no further write.

    @staticmethod
    async def reserve_switch_attempt(home_user_id, member_id) -> Tuple[int, int]:
        """Count one attempt on both keys atomically. Returns (member, pair)."""
        member_key = _switch_member_key(member_id)
        pair_key = _switch_pair_key(home_user_id, member_id)
        r = await _redis()
        try:
            async with r.pipeline(transaction=True) as pipe:
                pipe.incr(member_key)
                pipe.expire(member_key, PIN_FAILURE_WINDOW_SECONDS)
                pipe.incr(pair_key)
                pipe.expire(pair_key, PIN_FAILURE_WINDOW_SECONDS)
                member_count, _, pair_count, _ = await pipe.execute()
        finally:
            await r.aclose()
        return int(member_count), int(pair_count)

    @staticmethod
    async def refund_switch_attempt(home_user_id, member_id) -> None:
        """After a correct PIN: drop the pair key and give back the member
        reservation this attempt took. Atomic, never below zero, and never
        creates a key (a DECR on an expired key would leave -1 with no TTL)."""
        r = await _redis()
        try:
            await r.eval(
                _REFUND_LUA,
                2,
                _switch_member_key(member_id),
                _switch_pair_key(home_user_id, member_id),
            )
        finally:
            await r.aclose()

    @staticmethod
    async def switch_failures(home_user_id, member_id) -> int:
        """Read-only view (max of both counters) for tests and diagnostics.
        Never use it as the gate: that is reserve_switch_attempt's job."""
        r = await _redis()
        try:
            pair = await r.get(_switch_pair_key(home_user_id, member_id))
            member = await r.get(_switch_member_key(member_id))
        finally:
            await r.aclose()
        counts = []
        for val in (pair, member):
            try:
                counts.append(int(val or 0))
            except (TypeError, ValueError):
                counts.append(0)
        return max(counts)
