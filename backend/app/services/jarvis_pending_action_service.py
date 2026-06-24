"""Service for the Jarvis HITL gate: create/approve/reject pending actions.

Flow
----
1.  Jarvis (or any caller) detects a destructive tool call.
2.  ``PendingActionService.create`` inserts a ``JarvisPendingAction`` row with
    status ``"pending"`` and returns it.  The tool is NOT executed inline.
3.  The SSE stream emits a ``confirm`` event referencing the action id.
4.  The parent calls ``POST /api/jarvis/actions/{id}/approve``.
5.  ``PendingActionService.approve`` re-verifies ownership + expiry, binds an
    ``McpContext``, calls ``dispatch_tool``, marks the row ``"approved"``, and
    returns the dispatch result.
6.  ``PendingActionService.reject`` marks the row ``"rejected"`` without
    executing anything.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.confirm import summarize
from app.mcp.context import McpContext, use_context
from app.mcp.dispatch import dispatch_tool
from app.models.jarvis_pending_action import JarvisPendingAction


class PendingActionService:
    @staticmethod
    async def create(
        db: AsyncSession,
        ctx: McpContext,
        tool: str,
        args: dict,
    ) -> JarvisPendingAction:
        """Queue a destructive tool call for human approval.

        Returns the newly created ``JarvisPendingAction`` (status ``"pending"``).
        """
        pa = JarvisPendingAction(
            family_id=ctx.family_id,
            user_id=ctx.user_id,
            tool_name=tool,
            params=args,
            summary=summarize(tool, args),
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(pa)
        await db.commit()
        await db.refresh(pa)
        return pa

    @staticmethod
    async def approve(
        db: AsyncSession,
        action_id: UUID,
        current_user,  # app.models.user.User
    ) -> dict:
        """Execute the queued tool on behalf of the approving parent.

        Raises:
            PermissionError: if the action belongs to a different family.
            ValueError: if the action is already resolved or expired.
        """
        pa = await db.get(JarvisPendingAction, action_id)
        if pa is None:
            raise ValueError(f"PendingAction {action_id} not found")

        # Multi-tenant gate: user must belong to the same family as the action.
        if str(pa.family_id) != str(current_user.family_id):
            raise PermissionError("Not allowed to approve actions from another family")

        # Expiry check first: an expired row (regardless of status) raises "expired".
        exp = pa.expires_at
        exp = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
        if pa.status == "expired" or (pa.status == "pending" and datetime.now(timezone.utc) > exp):
            if pa.status != "expired":
                pa.status = "expired"
                pa.resolved_at = datetime.now(timezone.utc)
                await db.commit()
            raise ValueError("Action has expired")

        if pa.status != "pending":
            raise ValueError(f"Action already resolved with status '{pa.status}'")

        # Bind a fresh McpContext scoped to the approver's family + session.
        role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        ctx = McpContext(
            family_id=pa.family_id,
            user_id=current_user.id,
            role=role,
            db=db,
        )
        async with use_context(ctx):
            result = await dispatch_tool(pa.tool_name, dict(pa.params or {}))

        if not result.get("ok"):
            # Do NOT mark approved — leave the row pending so it can be retried.
            raise ValueError(f"Tool execution failed: {result.get('error')}")

        pa.status = "approved"
        pa.resolved_at = datetime.now(timezone.utc)
        await db.commit()

        return result

    @staticmethod
    async def reject(
        db: AsyncSession,
        action_id: UUID,
        current_user,
    ) -> None:
        """Discard the queued action without executing it.

        Raises:
            PermissionError: if the action belongs to a different family.
            ValueError: if the action is already resolved.
        """
        pa = await db.get(JarvisPendingAction, action_id)
        if pa is None:
            raise ValueError(f"PendingAction {action_id} not found")

        if str(pa.family_id) != str(current_user.family_id):
            raise PermissionError("Not allowed to reject actions from another family")

        if pa.status != "pending":
            raise ValueError(f"Action already resolved with status '{pa.status}'")

        pa.status = "rejected"
        pa.resolved_at = datetime.now(timezone.utc)
        await db.commit()

    @staticmethod
    async def list_pending(
        db: AsyncSession,
        family_id: UUID,
    ) -> list[JarvisPendingAction]:
        """Return all pending (non-expired) actions for a family."""
        result = await db.execute(
            select(JarvisPendingAction)
            .where(
                JarvisPendingAction.family_id == family_id,
                JarvisPendingAction.status == "pending",
                JarvisPendingAction.expires_at > datetime.now(timezone.utc),
            )
            .order_by(JarvisPendingAction.created_at.desc())
        )
        return list(result.scalars().all())
