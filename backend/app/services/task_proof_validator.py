"""AI photo validator for gig proof (W3.1).

Asks the vision model whether the photo plausibly shows that the named task
was completed. Returns a score (0.0–1.0) plus a one-line explanation.

Reuses the LiteLLM/Claude Vision pipeline from receipt_scanner_service so we
inherit the proxy's budget caps and centralized spend tracking.
"""

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi.concurrency import run_in_threadpool
from openai import OpenAI

from app.core.config import settings
from app.services.budget.receipt_scanner_service import LLM_TIMEOUT, RECEIPT_MODEL


PROOF_PROMPT = """You are validating photo proof that a household chore or task was completed by a child or teen.

TASK: {task_title}
{task_description_line}

Look at the image and answer in JSON only (no markdown):
{{
  "score": <0.0-1.0 — how likely the photo shows this task done, where 0.0 = clearly unrelated/fake, 0.5 = ambiguous, 1.0 = clearly shows the task completed>,
  "explanation": "one short sentence in the family's language: what you saw and why it does or does not match"
}}

Be lenient on framing and lighting — kids take messy photos. Be strict on relevance — a photo of an empty room when the task is "make bed" should score very low. A blank or off-topic photo (selfie, meme, random object) should score below 0.2."""


@dataclass
class ProofValidation:
    score: float
    explanation: str


def _strip_local_prefix(url: str) -> Optional[str]:
    """Map /uploads/... back to a local path inside the backend container."""
    if not url:
        return None
    if url.startswith("/uploads/"):
        return os.path.join("/app", url.lstrip("/"))
    return None


async def _load_image_bytes(url: str) -> tuple[bytes, str]:
    """Return (bytes, media_type) for either a local /uploads URL or a remote URL."""
    local_path = _strip_local_prefix(url)
    if local_path and os.path.exists(local_path):
        with open(local_path, "rb") as f:
            data = f.read()
        # naive type detection from suffix
        ext = local_path.rsplit(".", 1)[-1].lower()
        media_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "image/jpeg")
        return data, media_type
    # Remote fetch
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return resp.content, media_type


async def validate_proof_photo(
    proof_image_url: str,
    task_title: str,
    task_description: Optional[str] = None,
) -> Optional[ProofValidation]:
    """
    Returns a ProofValidation with score in [0.0, 1.0]. Returns None when
    the LiteLLM proxy is not configured — caller treats None as "no AI
    signal, fall back to manual review".
    """
    if not settings.LITELLM_API_KEY:
        return None

    try:
        image_bytes, media_type = await _load_image_bytes(proof_image_url)
    except Exception:
        return None

    desc_line = (
        f"DESCRIPTION: {task_description.strip()}\n"
        if task_description and task_description.strip()
        else ""
    )
    prompt = PROOF_PROMPT.format(
        task_title=task_title.strip(),
        task_description_line=desc_line,
    )

    client = OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=settings.LITELLM_API_KEY,
        timeout=LLM_TIMEOUT,  # connect fails fast; read capped at 60s
    )

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:{media_type};base64,{image_b64}"

    try:
        # Sync OpenAI client (blocking I/O) — offload to a worker thread so a
        # slow provider can't stall the async event loop.
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=RECEIPT_MODEL,
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        )
    except Exception:
        return None

    text = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    explanation = str(data.get("explanation", "") or "")[:500]
    return ProofValidation(score=score, explanation=explanation)
