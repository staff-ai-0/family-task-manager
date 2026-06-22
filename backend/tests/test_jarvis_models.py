"""Jarvis must only offer / default to models the family-task-manager LiteLLM
key reaches END-TO-END. Being *granted* isn't enough — verified on prod
(2026-06-22) that the granted Anthropic (haiku/claude-sonnet) + OpenAI (gpt-4o)
routes 401 upstream and qwen2.5/mistral aliases 400 as invalid; only
gemini-2.5-flash actually returns a completion. Tracked in jctux/platform#86;
re-expand this set as upstreams are fixed.
"""
from app.api.routes.jarvis import ALLOWED_MODELS
from app.core.config import settings

# Models that work end-to-end with the FTM key (prod-probe verified).
WORKING_MODELS = {"gemini-2.5-flash"}


def test_all_offered_models_work_end_to_end():
    broken = ALLOWED_MODELS - WORKING_MODELS
    assert not broken, f"Jarvis offers models that don't work with the key: {broken}"


def test_default_jarvis_model_works_end_to_end():
    assert settings.JARVIS_MODEL in WORKING_MODELS, (
        f"default JARVIS_MODEL={settings.JARVIS_MODEL!r} is not a working model"
    )


def test_qwen3_not_offered_until_platform_grants_it():
    # The model that triggered the original 401; keep it out until platform#86.
    assert "qwen3" not in ALLOWED_MODELS
