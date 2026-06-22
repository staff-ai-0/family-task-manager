"""Jarvis must only offer / default to models the family-task-manager LiteLLM
virtual key is actually granted — otherwise the proxy returns
401 key_model_access_denied (see jctux/platform#86, which tracks adding qwen3).
"""
from app.api.routes.jarvis import ALLOWED_MODELS
from app.core.config import settings

# Models the FTM virtual key is granted on the LiteLLM proxy, verbatim from the
# proxy's key_model_access list. Update this (and the issue) if platform grants
# more (e.g. re-adds qwen3).
KEY_GRANTED_MODELS = {
    "agent-custom", "gpt-4o", "claude-sonnet", "gemini-2.5-flash", "haiku",
    "mistral-small", "qwen2.5", "qwen2.5vl-frigate", "qwen2.5vl-frigate:latest",
    "qwen-vl",
}


def test_all_offered_models_are_key_granted():
    ungranted = ALLOWED_MODELS - KEY_GRANTED_MODELS
    assert not ungranted, f"Jarvis offers models the key can't access: {ungranted}"


def test_default_jarvis_model_is_key_granted():
    assert settings.JARVIS_MODEL in KEY_GRANTED_MODELS, (
        f"default JARVIS_MODEL={settings.JARVIS_MODEL!r} not in the key's grants"
    )


def test_qwen3_not_offered_until_platform_grants_it():
    # The exact model that triggered the 401; keep it out until platform#86 lands.
    assert "qwen3" not in ALLOWED_MODELS
