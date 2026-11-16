"""Profile switcher (UX-E4): a parent on a shared device hands it to a kid.

Security model: the caller authenticates with a "home" token, minted by
`share` from the PARENT's live access token. It is its own JWT type
(`type: "home"`), NOT a refresh token, so a copy taken out of the browser's
cookie jar cannot be traded at /api/auth/refresh for a parent session. A
kid's PIN then mints a switched (`sw`) session for that kid. Every failure of
target or PIN returns the same generic 403 so the endpoint is not an oracle
for which ids/PINs exist, and unknown/invalid targets never touch the Redis
throttle.
"""

from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_home_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.family import Family
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.schemas.user import ProfileEntry
from app.services.member_prefs_service import (
    PIN_MAX_FAILURES,
    MemberPrefsService,
    color_hex,
    resolve_color_name,
)

GENERIC_DETAIL = "Invalid profile or PIN"


def _generic_403() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GENERIC_DETAIL)


class ProfileSwitchService:
    @staticmethod
    def share(user: User, access_token: str) -> str:
        """Mint the home token for a parent who shares this device.

        `user` comes from get_current_user (valid ACCESS token, active, not
        deleted, family active; it does NOT check approval, so that is checked
        here, as resolve_home does on every later use). A switched (`sw`)
        session is refused even if it somehow carried a parent role: a kid
        session must never produce anything that leads back to a parent."""
        payload = decode_token(access_token, expected_type="access")
        if (
            payload.get("sw")
            or user.role != UserRole.PARENT
            or user.approval_status != APPROVAL_APPROVED
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return create_home_token(str(user.id), user.token_version)

    @staticmethod
    async def resolve_home(db: AsyncSession, token: str) -> User:
        """Validate a home token (type "home", never refresh/access) and load
        the parent it belongs to."""
        payload = decode_token(token, expected_type="home")
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Home session is no longer valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
        row = (
            await db.execute(
                select(User, Family.is_active, Family.deleted_at)
                .join(Family, Family.id == User.family_id)
                .where(User.id == payload.get("sub"))
            )
        ).one_or_none()
        if row is None:
            raise unauthorized
        user, family_active, family_deleted_at = row
        if (
            payload.get("ver") != user.token_version
            or user.deleted_at is not None
            or not user.is_active
            or user.approval_status != APPROVAL_APPROVED
            or family_active is False
            or family_deleted_at is not None
        ):
            raise unauthorized
        if payload.get("sw") or user.role != UserRole.PARENT:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return user

    @staticmethod
    def new_home_token(home: User) -> str:
        return create_home_token(str(home.id), home.token_version)

    @staticmethod
    def _eligible_filters(home: User):
        return (
            User.family_id == home.family_id,
            User.role.in_([UserRole.CHILD, UserRole.TEEN]),
            User.is_active.is_(True),
            User.approval_status == APPROVAL_APPROVED,
            User.deleted_at.is_(None),
        )

    @staticmethod
    async def list_profiles(db: AsyncSession, home: User) -> List[ProfileEntry]:
        rows = (
            await db.execute(
                select(User)
                .where(*ProfileSwitchService._eligible_filters(home))
                .order_by(User.name)
            )
        ).scalars().all()
        prefs = await MemberPrefsService.get_family_prefs(home.family_id)
        out: List[ProfileEntry] = []
        for u in rows:
            entry = prefs.get(str(u.id)) or {}
            out.append(
                ProfileEntry(
                    id=u.id,
                    name=u.name,
                    role=u.role.value,
                    # Hex, not the palette name: the picker paints it directly.
                    color=color_hex(resolve_color_name(u.id, entry)),
                    has_pin=bool(entry.get("pin_hash")),
                )
            )
        return out

    @staticmethod
    async def switch(
        db: AsyncSession, home: User, user_id, pin: str
    ) -> Tuple[User, str, str]:
        # Validate the target FIRST: no Redis access for an invalid target.
        target = (
            await db.execute(
                select(User).where(
                    User.id == user_id, *ProfileSwitchService._eligible_filters(home)
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise _generic_403()

        # Reserve first: this attempt is counted before bcrypt runs, so
        # concurrent guesses cannot all slip past the cap (see
        # MemberPrefsService.reserve_switch_attempt).
        member_count, pair_count = await MemberPrefsService.reserve_switch_attempt(
            home.id, target.id
        )
        if member_count > PIN_MAX_FAILURES or pair_count > PIN_MAX_FAILURES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Try again in a few minutes.",
            )

        verdict = await MemberPrefsService.verify_member_pin(
            home.family_id, target.id, pin
        )
        if verdict is not True:  # None (no PIN set) or False (wrong)
            raise _generic_403()  # already counted by the reservation
        await MemberPrefsService.refund_switch_attempt(home.id, target.id)

        access = create_access_token(
            {
                "sub": str(target.id),
                "role": target.role.value,
                "family_id": str(target.family_id),
                "sw": True,
            }
        )
        refresh = create_refresh_token(
            str(target.id), target.token_version, switched=True
        )
        return target, access, refresh

    @staticmethod
    async def return_to_parent(
        db: AsyncSession, home: User, password: str
    ) -> Tuple[User, str, str]:
        if not home.password_hash or not verify_password(password, home.password_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid password"
            )
        access = create_access_token(
            {
                "sub": str(home.id),
                "role": home.role.value,
                "family_id": str(home.family_id),
            }
        )
        refresh = create_refresh_token(str(home.id), home.token_version)
        return home, access, refresh
