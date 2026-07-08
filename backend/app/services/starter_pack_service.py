"""StarterPackService — apply age-preset ES/MX starter packs (P1-W3).

Turns the static pack data in app/data/starter_packs.py into real,
family-scoped rows:
- chores  → TaskTemplate (is_bonus=False, POINTS economy)
- gigs    → GigOffering  (points = $MXN cash, /gigs board economy)
- rewards → Reward       (points redemption)

Idempotent: an item whose title already exists in the family (case-
insensitive match on either language, against both title columns where the
model has them) is skipped, so re-applying a pack — or applying two bands
that share an item title — never duplicates rows.
"""
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.data.starter_packs import STARTER_PACKS
from app.models.gig import GigCategory, GigOffering
from app.models.reward import Reward, RewardCategory
from app.models.task_template import TaskTemplate
from app.schemas.onboarding import (
    StarterPack,
    StarterPackApplyRequest,
    StarterPackApplyResult,
    StarterPackList,
)

log = logging.getLogger(__name__)


def _norm(title: str | None) -> str:
    return (title or "").strip().lower()


class StarterPackService:

    @staticmethod
    def list_packs() -> StarterPackList:
        """All packs, in a stable band order (static data — no DB)."""
        return StarterPackList(packs=[
            StarterPack(age_band=band, **pack)
            for band, pack in STARTER_PACKS.items()
        ])

    @staticmethod
    def get_pack(age_band: str) -> dict:
        pack = STARTER_PACKS.get(age_band)
        if not pack:
            valid = ", ".join(STARTER_PACKS.keys())
            raise ValidationException(
                f"Unknown age band {age_band!r}. Valid bands: {valid}"
            )
        return pack

    @staticmethod
    def _select(items: list[dict], ids: list[str] | None) -> list[dict]:
        """None → all items; explicit list → only matching ids (unknown ids
        are ignored so a stale client selection can't 500 the apply)."""
        if ids is None:
            return items
        wanted = set(ids)
        return [i for i in items if i["id"] in wanted]

    @staticmethod
    async def apply(
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        payload: StarterPackApplyRequest,
    ) -> StarterPackApplyResult:
        pack = StarterPackService.get_pack(payload.age_band)
        lang = payload.lang
        result = StarterPackApplyResult(age_band=payload.age_band)

        chores = StarterPackService._select(pack["chores"], payload.chore_ids)
        gigs = StarterPackService._select(pack["gigs"], payload.gig_ids)
        rewards = StarterPackService._select(pack["rewards"], payload.reward_ids)

        # ── Existing titles per model (family-scoped, both languages) ────────
        existing_tpl = {
            _norm(t)
            for row in (await db.execute(
                select(TaskTemplate.title, TaskTemplate.title_es)
                .where(TaskTemplate.family_id == family_id)
            )).all()
            for t in row
            if t
        }
        existing_gig = {
            _norm(t)
            for t in (await db.execute(
                select(GigOffering.title)
                .where(GigOffering.family_id == family_id)
            )).scalars()
        }
        existing_reward = {
            _norm(t)
            for t in (await db.execute(
                select(Reward.title).where(Reward.family_id == family_id)
            )).scalars()
        }

        def _exists(existing: set[str], item: dict) -> bool:
            return (
                _norm(item["title_es"]) in existing
                or _norm(item["title_en"]) in existing
            )

        # ── Chores → TaskTemplate (both language columns available) ──────────
        for item in chores:
            if _exists(existing_tpl, item):
                result.skipped.chores += 1
                result.skipped_titles.append(item[f"title_{lang}"])
                continue
            db.add(TaskTemplate(
                title=item["title_en"],
                title_es=item["title_es"],
                points=item["points"],
                interval_days=item["interval_days"],
                is_bonus=False,
                family_id=family_id,
                created_by=created_by,
            ))
            existing_tpl.update({_norm(item["title_es"]), _norm(item["title_en"])})
            result.created.chores += 1

        # ── Gigs → GigOffering (single title column → UI language) ───────────
        for item in gigs:
            if _exists(existing_gig, item):
                result.skipped.gigs += 1
                result.skipped_titles.append(item[f"title_{lang}"])
                continue
            db.add(GigOffering(
                title=item[f"title_{lang}"],
                points=item["points"],
                difficulty=item["difficulty"],
                category=GigCategory(item["category"]),
                family_id=family_id,
                created_by=created_by,
            ))
            existing_gig.add(_norm(item[f"title_{lang}"]))
            result.created.gigs += 1

        # ── Rewards → Reward (single title column → UI language) ─────────────
        for item in rewards:
            if _exists(existing_reward, item):
                result.skipped.rewards += 1
                result.skipped_titles.append(item[f"title_{lang}"])
                continue
            db.add(Reward(
                title=item[f"title_{lang}"],
                points_cost=item["points_cost"],
                category=RewardCategory(item["category"]),
                icon=item.get("icon"),
                requires_parent_approval=item.get("requires_approval", False),
                family_id=family_id,
                is_active=True,
            ))
            existing_reward.add(_norm(item[f"title_{lang}"]))
            result.created.rewards += 1

        await db.commit()

        # Advance the getting-started checklist — a pack apply IS creating
        # tasks/rewards. Best-effort, mirrors the individual create hooks.
        try:
            from app.services.onboarding_service import OnboardingService
            if result.created.chores:
                await OnboardingService.advance(family_id, "task_created", db)
            if result.created.rewards:
                await OnboardingService.advance(family_id, "reward_created", db)
            await db.commit()
        except Exception:
            log.warning("onboarding advance after pack apply failed", exc_info=True)

        return result
