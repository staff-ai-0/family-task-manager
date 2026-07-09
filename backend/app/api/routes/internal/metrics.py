"""Lightweight Prometheus metrics endpoint (hand-rolled text exposition).

Exposes a handful of cheap, app-level gauges plus in-process counters at
``GET /metrics`` in the Prometheus text-exposition format — with NO
``prometheus_client`` dependency.

Access control reuses the same internal-service secret as ``/api/internal/*``
(``settings.INTERNAL_API_TOKEN``). The endpoint fails CLOSED: if the token is
unset it rejects everything, and every caller must present the token via either
``Authorization: Bearer <token>`` (Prometheus ``authorization.credentials``) or
the ``X-Internal-Token`` header. This matters because the public Cloudflare
tunnel routes ``api-family.agent-ia.mx`` straight at the backend, so ``/metrics``
would otherwise be internet-reachable.

The gauges run as a few ``COUNT`` queries against a short-lived session opened
directly from ``AsyncSessionLocal`` (NOT the pooled request-scoped ``get_db``
dependency) so a scraper hammering this route can't tie up a pooled connection.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.metrics import snapshot

logger = logging.getLogger(__name__)

router = APIRouter()

# Prometheus text-exposition content type (version 0.0.4).
_PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _extract_token(authorization: str | None, x_internal_token: str | None) -> str:
    """Pull the presented secret from either supported header form."""
    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential:
            return credential.strip()
    return (x_internal_token or "").strip()


def _authorize(authorization: str | None, x_internal_token: str | None) -> None:
    """Fail-closed token check, constant-time. Reuses INTERNAL_API_TOKEN."""
    expected = settings.INTERNAL_API_TOKEN or ""
    presented = _extract_token(authorization, x_internal_token)
    if not expected or not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid internal token")


def _render(lines: list[tuple[str, str, str, float]]) -> str:
    """Render (name, type, help, value) rows into Prometheus text format."""
    out: list[str] = []
    for name, mtype, help_text, value in lines:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {mtype}")
        # Integers render without a trailing ``.0`` for readability; Prometheus
        # accepts both, but clean integers keep the payload tidy.
        rendered = str(int(value)) if float(value).is_integer() else repr(float(value))
        out.append(f"{name} {rendered}")
    return "\n".join(out) + "\n"


async def _gather_gauges() -> dict[str, int]:
    """Compute app-level gauges with a few COUNT queries (short-lived session)."""
    # Imported lazily so this module has no import-time model coupling and the
    # route file stays cheap to import at app startup.
    from app.models.family import Family
    from app.models.user import User
    from app.models.subscription import FamilySubscription, SubscriptionPlan
    from app.models.budget import BudgetReceiptDraft
    from app.models.task_assignment import TaskAssignment, AssignmentStatus

    async with AsyncSessionLocal() as session:
        families_total = await session.scalar(select(func.count()).select_from(Family))

        active_users = await session.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )

        # Paying tenants: an active subscription on any plan that isn't "free".
        nonfree_subs = await session.scalar(
            select(func.count())
            .select_from(FamilySubscription)
            .join(SubscriptionPlan, FamilySubscription.plan_id == SubscriptionPlan.id)
            .where(
                FamilySubscription.status == "active",
                SubscriptionPlan.name != "free",
            )
        )

        pending_drafts = await session.scalar(
            select(func.count())
            .select_from(BudgetReceiptDraft)
            .where(BudgetReceiptDraft.status == "pending")
        )

        overdue_assignments = await session.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .where(TaskAssignment.status == AssignmentStatus.OVERDUE)
        )

    return {
        "families_total": int(families_total or 0),
        "active_users": int(active_users or 0),
        "nonfree_subscriptions": int(nonfree_subs or 0),
        "pending_receipt_drafts": int(pending_drafts or 0),
        "overdue_assignments": int(overdue_assignments or 0),
    }


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(
    request: Request,
    authorization: str | None = Header(None),
    x_internal_token: str | None = Header(None),
) -> PlainTextResponse:
    """Prometheus scrape target. Token-guarded; O(few) COUNT queries."""
    _authorize(authorization, x_internal_token)

    counters = snapshot()

    # DB gauges are best-effort: if the DB hiccups we still return the process
    # counters (and up=1) rather than 500-ing the whole scrape.
    try:
        gauges = await _gather_gauges()
        db_up = 1
    except Exception:
        logger.exception("metrics: gauge collection failed")
        gauges = {
            "families_total": 0,
            "active_users": 0,
            "nonfree_subscriptions": 0,
            "pending_receipt_drafts": 0,
            "overdue_assignments": 0,
        }
        db_up = 0

    rows: list[tuple[str, str, str, float]] = [
        ("family_up", "gauge", "1 if the app answered this scrape.", 1),
        (
            "family_metrics_db_up",
            "gauge",
            "1 if the gauge COUNT queries succeeded, else 0.",
            db_up,
        ),
        (
            "family_families_total",
            "gauge",
            "Total number of families (tenants).",
            gauges["families_total"],
        ),
        (
            "family_active_users",
            "gauge",
            "Number of users with is_active = true.",
            gauges["active_users"],
        ),
        (
            "family_nonfree_subscriptions",
            "gauge",
            "Active subscriptions on a paid (non-free) plan.",
            gauges["nonfree_subscriptions"],
        ),
        (
            "family_pending_receipt_drafts",
            "gauge",
            "Receipt drafts awaiting human review (status=pending).",
            gauges["pending_receipt_drafts"],
        ),
        (
            "family_overdue_assignments",
            "gauge",
            "Task assignments currently in the OVERDUE state.",
            gauges["overdue_assignments"],
        ),
        (
            "family_llm_calls_total",
            "counter",
            "Outbound LLM/vision calls made by this worker since startup (best-effort, per-worker).",
            counters.get("llm_calls_total", 0),
        ),
    ]

    return PlainTextResponse(content=_render(rows), media_type=_PROM_CONTENT_TYPE)
