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
