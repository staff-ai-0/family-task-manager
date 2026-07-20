"""Jarvis must only offer / default to models the family-task-manager LiteLLM
key reaches END-TO-END. Being *granted* isn't enough — verified on prod
(2026-06-22) that the granted Anthropic (haiku/claude-sonnet) + OpenAI (gpt-4o)
routes 401 upstream and qwen2.5/mistral aliases 400 as invalid; only
gemini-2.5-flash actually returned a completion at the time.

jctux/platform#86 resolved 2026-07-20: qwen3 (Ollama, platform reverted
vLLM->Ollama) confirmed serving 200 via the admin key, and the FTM virtual
key's grant now includes qwen3 + claude-haiku (the naming-drift the issue
also flagged — the app requested "claude-haiku", the key only granted
"haiku"). claude-sonnet/gpt-4o's Anthropic/OpenAI upstream fix was never
confirmed in that thread, so they stay out — re-expand only once verified.
"""
from app.api.routes.jarvis import ALLOWED_MODELS
from app.core.config import settings

# Models confirmed working end-to-end with the FTM key (platform#86).
WORKING_MODELS = {"gemini-2.5-flash", "qwen3", "claude-haiku"}


def test_all_offered_models_work_end_to_end():
    broken = ALLOWED_MODELS - WORKING_MODELS
    assert not broken, f"Jarvis offers models that don't work with the key: {broken}"


def test_default_jarvis_model_works_end_to_end():
    assert settings.JARVIS_MODEL in WORKING_MODELS, (
        f"default JARVIS_MODEL={settings.JARVIS_MODEL!r} is not a working model"
    )


def test_qwen3_and_claude_haiku_offered_now_platform_granted():
    # platform#86 fix: both now reach the LiteLLM proxy end-to-end.
    assert "qwen3" in ALLOWED_MODELS
    assert "claude-haiku" in ALLOWED_MODELS


def test_unconfirmed_upstreams_stay_out():
    # claude-sonnet/gpt-4o's Anthropic/OpenAI upstream fix was never
    # confirmed working end-to-end — don't re-offer on access-grant alone.
    assert "claude-sonnet" not in ALLOWED_MODELS
    assert "gpt-4o" not in ALLOWED_MODELS
