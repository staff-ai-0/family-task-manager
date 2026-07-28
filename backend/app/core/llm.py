"""Single construction point for the LiteLLM-proxied LLM client.

Every AI surface — receipt scan, calendar scan, recipe import, gig-proof
validation, transaction categorization, Jarvis — speaks to the same LiteLLM
proxy through the OpenAI-compatible SDK. Owning the client here keeps the
connect/read timeout split and the "not configured" refusal identical across
call sites, and stops core services (calendar, Jarvis) from importing a budget
module just to reach a shared constant.

Only the transport is shared: model alias, max_tokens and prompt stay at the
call site, since those are domain choices.
"""

import os

import httpx
from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import ValidationError

# Hard ceiling for any single LiteLLM request. A hung or slow provider must
# never block the event loop indefinitely.
LLM_REQUEST_TIMEOUT_SECONDS = 60.0
# Connect fails fast (5s) when the proxy is unreachable, while a healthy
# provider still gets the full read window to produce a response.
LLM_TIMEOUT = httpx.Timeout(LLM_REQUEST_TIMEOUT_SECONDS, connect=5.0)

# Default alias when no per-family override is stored in Redis. Named for its
# first consumer, but the calendar/recipe/proof paths share it so one env var
# moves the whole app between providers. It is also what the AI-settings model
# picker offers parents. Alternatives: "qwen-vl", "claude-haiku",
# "claude-sonnet", "gpt-4o".
RECEIPT_MODEL = settings.RECEIPT_MODEL

# Text-only classifier alias, kept separate from RECEIPT_MODEL so
# categorization can run on a cheap model while receipts stay vision-capable.
CATEGORIZER_MODEL = os.environ.get("CATEGORIZER_MODEL", "gemini-2.5-flash")


class LLMNotConfiguredError(ValidationError):
    """No LiteLLM virtual key — our misconfiguration, not the caller's input."""


def get_llm_client() -> OpenAI:
    """Build the OpenAI SDK client pointed at the LiteLLM proxy.

    The proxy owns authentication, translation to each provider's native
    format, per-key monthly budget enforcement and spend logging, so no call
    site may talk to an upstream provider directly.

    Raises:
        LLMNotConfiguredError: LITELLM_API_KEY is unset. Call sites that can
            degrade gracefully (returning None, or refusing with their own
            wording) check the key before they get here; this is the backstop
            so a missing key can never reach the network layer.
    """
    if not settings.LITELLM_API_KEY:
        raise LLMNotConfiguredError(
            "AI features are not configured. Please set LITELLM_API_KEY "
            "to a virtual key issued by the LiteLLM proxy."
        )
    return OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=settings.LITELLM_API_KEY,
        timeout=LLM_TIMEOUT,
    )
