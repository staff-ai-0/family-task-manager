"""
AI & Scanner settings

GET  /api/budget/ai-settings/models  — list available vision models + current selection
PUT  /api/budget/ai-settings/models  — update model selection (stored per-family in Redis)
GET  /api/budget/ai-settings/usage   — proxy to LiteLLM /key/info for spend data
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.dependencies import require_parent_role
from app.models import User

router = APIRouter()

# LiteLLM-registered model aliases. Add new entries when a model is
# registered in litellm_config.yaml on the platform side.
VISION_MODELS = [
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "qwen-vl", "label": "Qwen2-VL-2B-AWQ (on-prem, GPU 0)"},
    {"id": "claude-haiku", "label": "Claude Haiku"},
    {"id": "claude-sonnet", "label": "Claude Sonnet"},
    {"id": "gpt-4o", "label": "GPT-4o"},
]

_KNOWN_MODEL_IDS = {m["id"] for m in VISION_MODELS}


def _redis_model_key(family_id) -> str:
    return f"family_settings:{family_id}:receipt_model"


async def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/models")
async def get_vision_models(
    current_user: User = Depends(require_parent_role),
):
    r = await _redis()
    try:
        selected = await r.get(_redis_model_key(current_user.family_id))
    finally:
        await r.aclose()
    return {
        "current_model": selected or settings.RECEIPT_MODEL,
        "default_model": settings.RECEIPT_MODEL,
        "models": VISION_MODELS,
    }


class ModelUpdate(BaseModel):
    model: str


@router.put("/models")
async def set_vision_model(
    body: ModelUpdate,
    current_user: User = Depends(require_parent_role),
):
    if body.model not in _KNOWN_MODEL_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{body.model}'. Known: {sorted(_KNOWN_MODEL_IDS)}",
        )
    r = await _redis()
    try:
        await r.set(_redis_model_key(current_user.family_id), body.model)
    finally:
        await r.aclose()
    return {"model": body.model}


@router.get("/usage")
async def get_ai_usage(
    current_user: User = Depends(require_parent_role),
):
    """Proxy LiteLLM /key/info for the configured virtual key's spend data."""
    if not settings.LITELLM_API_KEY or not settings.LITELLM_API_BASE:
        raise HTTPException(status_code=503, detail="LiteLLM not configured")

    base = settings.LITELLM_API_BASE.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.LITELLM_API_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{base}/key/info", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"LiteLLM returned {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"LiteLLM unreachable: {exc}")

    info = data.get("info", data)
    return {
        "spend": info.get("spend", 0),
        "max_budget": info.get("max_budget"),
        "budget_duration": info.get("budget_duration"),
        "budget_reset_at": info.get("budget_reset_at"),
        "key_alias": info.get("key_alias") or info.get("key_name"),
        "models": info.get("models", []),
        "tpm_limit": info.get("tpm_limit"),
        "rpm_limit": info.get("rpm_limit"),
    }
