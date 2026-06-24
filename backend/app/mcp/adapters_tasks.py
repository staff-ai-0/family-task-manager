"""MCP adapters for the tasks domain.

Migrated from the legacy ``jarvis_tools`` handlers:
  - ``tasks_template_create`` (was ``create_task_template``) — mandatory chores
    clamp points to 0; gigs (is_bonus) award points.
  - ``tasks_template_*`` CRUD via the inherited BaseFamilyService classmethods.
  - ``tasks_today_list``   (was ``list_today_progress``)
  - ``tasks_pending_list`` (was ``list_pending_approvals``)
  - ``tasks_overdue_list`` (was ``list_overdue_tasks``)
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User


def _ser_template(t: TaskTemplate) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "is_bonus": t.is_bonus,
        "points": t.points,
    }


class TemplateAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.task_template_service import TaskTemplateService

        rows = await TaskTemplateService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_template(t) for t in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.task_template_service import TaskTemplateService

        return _ser_template(
            await TaskTemplateService.get_by_id(ctx.db, entity_id, ctx.family_id)
        )

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.schemas.task_template import TaskTemplateCreate
        from app.services.task_template_service import TaskTemplateService

        is_bonus = bool(data.get("is_bonus", False))
        points = int(data.get("points", 0))
        if not is_bonus:
            points = 0  # mandatory chores never award points
        payload = TaskTemplateCreate(
            title=str(data["title"])[:200],
            points=points,
            effort_level=int(data.get("effort_level", 1)),
            interval_days=int(data.get("interval_days", 1)),
            is_bonus=is_bonus,
        )
        tmpl = await TaskTemplateService.create_template(
            ctx.db, payload, ctx.family_id, ctx.user_id
        )
        return _ser_template(tmpl)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.task_template_service import TaskTemplateService

        tmpl = await TaskTemplateService.update_by_id(
            ctx.db, entity_id, ctx.family_id, data
        )
        return _ser_template(tmpl)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.task_template_service import TaskTemplateService

        await TaskTemplateService.delete_by_id(ctx.db, entity_id, ctx.family_id)


class TodayProgressAdapter(ServiceAdapter):
    """Read-only: today's per-member task progress."""

    async def list(self, ctx: McpContext) -> list[dict]:
        today = date.today()
        q = (
            select(
                TaskAssignment.assigned_to,
                func.count(TaskAssignment.id).label("total"),
                func.count()
                .filter(TaskAssignment.status == AssignmentStatus.COMPLETED)
                .label("done"),
            )
            .where(
                and_(
                    TaskAssignment.family_id == ctx.family_id,
                    TaskAssignment.assigned_date == today,
                )
            )
            .group_by(TaskAssignment.assigned_to)
        )
        rows = (await ctx.db.execute(q)).all()
        names = {
            u.id: u.name
            for u in (
                await ctx.db.execute(
                    select(User).where(User.family_id == ctx.family_id)
                )
            ).scalars().all()
        }
        return [
            {"name": names.get(uid, "?"), "done": int(d or 0), "total": int(t or 0)}
            for uid, t, d in rows
        ]


class PendingApprovalsAdapter(ServiceAdapter):
    """Read-only: gigs awaiting parent approval."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.task_assignment_service import TaskAssignmentService

        rows = await TaskAssignmentService.list_pending_approvals(
            ctx.db, ctx.family_id
        )
        names = {
            u.id: u.name
            for u in (
                await ctx.db.execute(
                    select(User).where(User.family_id == ctx.family_id)
                )
            ).scalars().all()
        }
        return [
            {
                "assignment_id": str(r.id),
                "title": r.template.title if r.template else "",
                "child": names.get(r.assigned_to, "?"),
                "points": r.template.award_points_per_completer if r.template else 0,
                "proof_text": r.proof_text,
                "ai_score": r.ai_validation_score,
            }
            for r in rows
        ]


class OverdueTasksAdapter(ServiceAdapter):
    """Read-only: overdue assignments across the family (last 14 days)."""

    async def list(self, ctx: McpContext) -> list[dict]:
        today = date.today()
        q = (
            select(TaskAssignment)
            .where(
                and_(
                    TaskAssignment.family_id == ctx.family_id,
                    TaskAssignment.status == AssignmentStatus.OVERDUE,
                    TaskAssignment.assigned_date >= today - timedelta(days=14),
                )
            )
            .order_by(TaskAssignment.assigned_date.desc())
            .limit(50)
        )
        rows = list((await ctx.db.execute(q)).scalars().all())
        names = {
            u.id: u.name
            for u in (
                await ctx.db.execute(
                    select(User).where(User.family_id == ctx.family_id)
                )
            ).scalars().all()
        }
        tmpl_ids = {r.template_id for r in rows}
        tmpls = {
            t.id: t
            for t in (
                await ctx.db.execute(
                    select(TaskTemplate).where(TaskTemplate.id.in_(tmpl_ids))
                )
            ).scalars().all()
        }
        return [
            {
                "title": tmpls.get(r.template_id).title if tmpls.get(r.template_id) else "",
                "child": names.get(r.assigned_to, "?"),
                "assigned_date": r.assigned_date.isoformat(),
            }
            for r in rows
        ]
