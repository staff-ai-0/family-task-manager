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


def get_llm_client(api_key: str | None = None) -> OpenAI:
    """Build the OpenAI SDK client pointed at the LiteLLM proxy.

    The proxy owns authentication, translation to each provider's native
    format, per-key monthly budget enforcement and spend logging, so no call
    site may talk to an upstream provider directly.

    Args:
        api_key: Optional per-call LiteLLM virtual key override. Support mode
            passes its dedicated key (spend attribution + budget isolation);
            every other call site keeps the app-wide LITELLM_API_KEY.

    Raises:
        LLMNotConfiguredError: no usable key — neither the override nor
            LITELLM_API_KEY is set. Call sites that can degrade gracefully
            check before they get here; this is the backstop so a missing
            key can never reach the network layer.
    """
    key = api_key or settings.LITELLM_API_KEY
    if not key:
        raise LLMNotConfiguredError(
            "AI features are not configured. Please set LITELLM_API_KEY "
            "to a virtual key issued by the LiteLLM proxy."
        )
    return OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=key,
        timeout=LLM_TIMEOUT,
    )
