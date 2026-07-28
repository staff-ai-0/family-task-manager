"""Guards the single construction point for the LiteLLM-proxied LLM client.

Seven call sites across six services used to build their own OpenAI client,
and four of them imported the shared timeout *from the budget receipt
scanner* — so a calendar scan depended on a budget module for a core
constant. These tests pin both the client's contract and the fact that it
stays in one place.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import llm
from app.core.exceptions import ValidationError

APP_ROOT = Path(llm.__file__).resolve().parent.parent


class TestGetLlmClient:
    def test_client_targets_the_proxy_v1_endpoint_with_the_virtual_key(self):
        with patch.object(llm, "settings") as mock_settings, patch.object(
            llm, "OpenAI"
        ) as mock_openai:
            mock_settings.LITELLM_API_KEY = "sk-fake"
            mock_settings.LITELLM_API_BASE = "http://proxy:4000"
            llm.get_llm_client()

        kwargs = mock_openai.call_args.kwargs
        assert kwargs["base_url"] == "http://proxy:4000/v1"
        assert kwargs["api_key"] == "sk-fake"

    def test_trailing_slash_on_the_base_does_not_double_up(self):
        with patch.object(llm, "settings") as mock_settings, patch.object(
            llm, "OpenAI"
        ) as mock_openai:
            mock_settings.LITELLM_API_KEY = "sk-fake"
            mock_settings.LITELLM_API_BASE = "http://proxy:4000/"
            llm.get_llm_client()

        assert mock_openai.call_args.kwargs["base_url"] == "http://proxy:4000/v1"

    def test_timeout_fails_connect_fast_but_lets_a_slow_provider_answer(self):
        """A single scalar timeout would cut off a healthy-but-slow model at 5s,
        and no timeout at all would let a hung provider block the event loop."""
        assert llm.LLM_TIMEOUT.connect == 5.0
        assert llm.LLM_TIMEOUT.read == llm.LLM_REQUEST_TIMEOUT_SECONDS

        with patch.object(llm, "settings") as mock_settings, patch.object(
            llm, "OpenAI"
        ) as mock_openai:
            mock_settings.LITELLM_API_KEY = "sk-fake"
            mock_settings.LITELLM_API_BASE = "http://proxy:4000"
            llm.get_llm_client()

        assert mock_openai.call_args.kwargs["timeout"] is llm.LLM_TIMEOUT

    def test_missing_key_refuses_before_any_client_is_built(self):
        with patch.object(llm, "settings") as mock_settings, patch.object(
            llm, "OpenAI"
        ) as mock_openai:
            mock_settings.LITELLM_API_KEY = ""
            with pytest.raises(llm.LLMNotConfiguredError, match="not configured"):
                llm.get_llm_client()
            mock_openai.assert_not_called()

    def test_not_configured_stays_catchable_as_a_validation_error(self):
        """Call sites already catch ValidationError; the new type must not slip
        past them as an unhandled 500."""
        assert issubclass(llm.LLMNotConfiguredError, ValidationError)


class TestOneHomeForTheClient:
    """Regression guards against the duplication coming back."""

    def _service_sources(self):
        for path in sorted((APP_ROOT / "services").rglob("*.py")):
            yield path, path.read_text()

    def test_no_service_imports_the_openai_sdk_directly(self):
        offenders = [
            str(path.relative_to(APP_ROOT))
            for path, source in self._service_sources()
            if "from openai import" in source or "\nimport openai" in source
        ]
        assert not offenders, (
            f"{offenders} build their own LLM client — use "
            "app.core.llm.get_llm_client() so the timeout and the "
            "'not configured' refusal stay identical everywhere"
        )

    def test_no_module_reaches_into_the_budget_scanner_for_llm_config(self):
        offenders = [
            str(path.relative_to(APP_ROOT))
            for path, source in self._service_sources()
            if "receipt_scanner_service import LLM_TIMEOUT" in source
            or "receipt_scanner_service import RECEIPT_MODEL" in source
        ]
        assert not offenders, (
            f"{offenders} import LLM config from a budget module; "
            "app.core.llm owns it"
        )

    def test_every_llm_service_shares_the_one_factory(self):
        """Each of the six services that talk to LiteLLM must go through it."""
        expected = [
            "services/jarvis_service.py",
            "services/calendar_scanner_service.py",
            "services/recipe_importer.py",
            "services/task_proof_validator.py",
            "services/budget/category_ai_service.py",
            "services/budget/receipt_scanner_service.py",
        ]
        for rel in expected:
            source = (APP_ROOT / rel).read_text()
            assert "get_llm_client" in source, f"{rel} no longer uses the factory"
