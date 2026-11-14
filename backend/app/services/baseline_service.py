"""Chore baselines: parent reference photos per task template.

Every query is family-scoped. Files live under ``<UPLOADS_ROOT>/chore-baselines/``
with UUID names, plus a WebP thumbnail sibling (same scheme as proof photos)."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core import async_fs
from app.core.config import settings
from app.core.exceptions import BaselineLimitException, NotFoundException
from app.core.thumbnails import make_webp_thumbnail, thumb_filename
from app.core.type_utils import to_uuid_required
from app.core.upload_validation import assert_allowed_type
from app.models.chore_baseline import ChoreBaseline
from app.models.task_template import TaskTemplate
from app.models.user import User

MAX_BASELINES_PER_TEMPLATE = 4
BASELINE_STALE_DAYS = 30
MAX_BASELINES_TO_AI = 3

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
URL_PREFIX = "/uploads/chore-baselines/"


def baselines_dir() -> str:
    return os.path.join(settings.UPLOADS_ROOT, "chore-baselines")


class BaselineService:
    @staticmethod
    async def _template(
        db: AsyncSession, family_id: UUID, template_id: UUID, lock: bool = False
    ) -> TaskTemplate:
        q = select(TaskTemplate).where(
            TaskTemplate.id == template_id, TaskTemplate.family_id == family_id
        )
        if lock:
            # Serializes concurrent adds for this template (released at commit).
            q = q.with_for_update()
        t = (await db.execute(q)).scalar_one_or_none()
        if t is None:
            raise NotFoundException("Template not found")
        return t

    @staticmethod
    async def list(db: AsyncSession, family_id: UUID, template_id: UUID) -> List[ChoreBaseline]:
        await BaselineService._template(db, family_id, template_id)
        rows = await db.execute(
            select(ChoreBaseline)
            .where(ChoreBaseline.family_id == family_id, ChoreBaseline.template_id == template_id)
            .order_by(ChoreBaseline.position, ChoreBaseline.created_at)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def add(
        db: AsyncSession,
        user: User,
        template_id: UUID,
        file_bytes: bytes,
        content_type: str,
        caption: Optional[str] = None,
    ) -> ChoreBaseline:
        family_id = to_uuid_required(user.family_id)
        await BaselineService._template(db, family_id, template_id, lock=True)

        if (content_type or "").lower() not in ALLOWED_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported type {content_type}")
        # Authoritative check: sniff the real bytes, not the declared type.
        real_type = assert_allowed_type(file_bytes, ALLOWED_TYPES)

        count, max_pos = (await db.execute(
            select(func.count(ChoreBaseline.id), func.max(ChoreBaseline.position)).where(
                ChoreBaseline.family_id == family_id, ChoreBaseline.template_id == template_id
            )
        )).one()
        if count >= MAX_BASELINES_PER_TEMPLATE:
            raise BaselineLimitException("baseline_limit")

        fname = f"{uuid.uuid4().hex}.{_EXT[real_type]}"
        dest = baselines_dir()
        paths = [os.path.join(dest, fname), os.path.join(dest, thumb_filename(fname))]
        try:
            await async_fs.write_bytes(paths[0], file_bytes)
            thumb = await run_in_threadpool(make_webp_thumbnail, file_bytes)
            if thumb:
                await async_fs.write_bytes(paths[1], thumb)
            row = ChoreBaseline(
                family_id=family_id,
                template_id=template_id,
                image_url=f"{URL_PREFIX}{fname}",
                caption=((caption or "").strip() or None),
                position=(max_pos + 1) if max_pos is not None else 0,
                created_by=user.id,
            )
            db.add(row)
            await db.commit()
        except BaseException:
            await db.rollback()
            for path in paths:
                await async_fs.remove_if_exists(path)
            raise
        await db.refresh(row)
        return row

    @staticmethod
    async def delete(db: AsyncSession, family_id: UUID, template_id: UUID, baseline_id: UUID) -> None:
        await BaselineService._template(db, family_id, template_id)
        row = (await db.execute(
            select(ChoreBaseline).where(
                ChoreBaseline.id == baseline_id,
                ChoreBaseline.family_id == family_id,
                ChoreBaseline.template_id == template_id,
            )
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundException("Baseline not found")
        fname = row.image_url.rsplit("/", 1)[-1]
        await db.delete(row)
        await db.commit()
        d = baselines_dir()
        await async_fs.remove_if_exists(os.path.join(d, fname))
        await async_fs.remove_if_exists(os.path.join(d, thumb_filename(fname)))

    @staticmethod
    async def status(db: AsyncSession, family_id: UUID, now: Optional[datetime] = None) -> List[dict]:
        """One row per active proof-required (non-bonus) template; ``due`` when it has no
        baseline or its newest one is older than BASELINE_STALE_DAYS."""
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=BASELINE_STALE_DAYS)
        rows = (await db.execute(
            select(
                TaskTemplate.id,
                TaskTemplate.title,
                func.count(ChoreBaseline.id),
                func.max(ChoreBaseline.created_at),
            )
            .outerjoin(
                ChoreBaseline,
                (ChoreBaseline.template_id == TaskTemplate.id)
                & (ChoreBaseline.family_id == family_id),
            )
            .where(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active.is_(True),
                TaskTemplate.requires_proof.is_(True),
                # Bonus tasks never use baselines (inline auto-approve path).
                TaskTemplate.is_bonus.is_not(True),
            )
            .group_by(TaskTemplate.id, TaskTemplate.title)
            .order_by(TaskTemplate.title)
        )).all()
        return [
            {
                "template_id": tid,
                "title": title,
                "baseline_count": int(n),
                "last_baseline_at": last,
                "due": last is None or last < cutoff,
            }
            for tid, title, n, last in rows
        ]

    @staticmethod
    async def urls_for_ai(db: AsyncSession, family_id: UUID, template_id: UUID) -> List[str]:
        rows = await db.execute(
            select(ChoreBaseline.image_url)
            .where(ChoreBaseline.family_id == family_id, ChoreBaseline.template_id == template_id)
            .order_by(ChoreBaseline.created_at.desc(), ChoreBaseline.position.desc())
            .limit(MAX_BASELINES_TO_AI)
        )
        return [u for (u,) in rows.all()]
