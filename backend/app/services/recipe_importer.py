"""Recipe URL importer (W7.5).

Fetches a webpage, strips noise, and asks the LiteLLM-routed vision model
to extract structured recipe data (text-only — vision is overkill for HTML).
Returns the parsed recipe for the caller to review and persist via the
standard POST /api/meals/recipes endpoint.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi.concurrency import run_in_threadpool
from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.metrics import record_llm_call
from app.services.budget.receipt_scanner_service import LLM_TIMEOUT, RECEIPT_MODEL


# Strip cap so we keep the prompt comfortably under the model's context.
MAX_HTML_CHARS = 60_000
FETCH_TIMEOUT_SECONDS = 12.0


RECIPE_PROMPT = """Extract the recipe from this HTML page text. Return ONLY valid JSON, no markdown.

{
  "name": "<recipe title>",
  "description": "<one-sentence summary or null>",
  "ingredients_text": "<one ingredient per line, no bullets or numbering>",
  "prep_minutes": <total active time in minutes, integer, or null>,
  "confidence": <0.0-1.0>
}

Rules:
- Strip site branding from name. Just the dish name.
- ingredients_text MUST be plain text, one ingredient per line, no markdown bullets.
- prep_minutes is total active prep + cook time; ignore "ready in 24h" claims that are mostly passive.
- Set confidence 0 and other fields null if the page is not a recipe."""


@dataclass
class ImportedRecipe:
    name: str
    description: Optional[str]
    ingredients_text: Optional[str]
    prep_minutes: Optional[int]
    confidence: float
    source_url: str


def _strip_html(html: str) -> str:
    """Remove script/style and collapse whitespace. Cheap, not perfect."""
    # Drop script + style blocks first (greedy was a bug source elsewhere — use non-greedy).
    no_script = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    no_style = re.sub(r"<style[\s\S]*?</style>", " ", no_script, flags=re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    no_entities = (
        no_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    collapsed = re.sub(r"\s+", " ", no_entities).strip()
    return collapsed[:MAX_HTML_CHARS]


async def import_recipe_from_url(url: str) -> ImportedRecipe:
    if not settings.LITELLM_API_KEY:
        raise ValidationError(
            "Recipe import not configured. Set LITELLM_API_KEY."
        )
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        raise ValidationError("Invalid URL — must start with http(s)://")

    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValidationError(f"Could not fetch URL: {exc}")

    text_block = _strip_html(resp.text or "")
    if not text_block:
        raise ValidationError("Page returned no readable text.")

    client = OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=settings.LITELLM_API_KEY,
        timeout=LLM_TIMEOUT,  # connect fails fast; read capped at 60s
    )
    try:
        # Sync OpenAI client (blocking I/O) — offload to a worker thread so a
        # slow provider can't stall the async event loop.
        record_llm_call()  # best-effort outbound-LLM counter
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=RECEIPT_MODEL,
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": f"{RECIPE_PROMPT}\n\nPAGE TEXT:\n{text_block}"},
                ],
            )
        )
    except Exception as exc:
        raise ValidationError(f"Recipe extraction failed: {exc}")

    body = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{[\s\S]*\}", body)
    if not match:
        raise ValidationError("Could not parse recipe from page.")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        raise ValidationError("Recipe parser returned invalid JSON.")

    try:
        prep = int(data["prep_minutes"]) if data.get("prep_minutes") else None
    except (TypeError, ValueError):
        prep = None
    try:
        confidence = float(data.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    name = str(data.get("name") or "").strip()[:200]
    if not name:
        raise ValidationError("No recipe name detected on the page.")

    return ImportedRecipe(
        name=name,
        description=(data.get("description") or None),
        ingredients_text=(data.get("ingredients_text") or None),
        prep_minutes=prep,
        confidence=max(0.0, min(1.0, confidence)),
        source_url=url,
    )
