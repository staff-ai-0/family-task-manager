"""Recipe URL importer (W7.5) — mocked HTML fetch + LLM."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.exceptions import ValidationError
from app.services.recipe_importer import (
    _strip_html,
    import_recipe_from_url,
)


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test")
    monkeypatch.setattr(
        config.settings, "LITELLM_API_BASE", "https://litellm.test"
    )


class TestStripHtml:
    def test_drops_script_and_style(self):
        html = "<html><script>bad();</script><style>x{}</style><p>Hello</p></html>"
        assert "bad()" not in _strip_html(html)
        assert "x{}" not in _strip_html(html)
        assert "Hello" in _strip_html(html)

    def test_truncates_long_pages(self):
        html = "<html>" + ("x" * 200000) + "</html>"
        assert len(_strip_html(html)) <= 60_000


class TestImport:
    async def test_invalid_url_rejected(self):
        with pytest.raises(ValidationError):
            await import_recipe_from_url("ftp://nope")
        with pytest.raises(ValidationError):
            await import_recipe_from_url("")

    async def test_no_api_key(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
        with pytest.raises(ValidationError):
            await import_recipe_from_url("https://example.com")

    async def test_happy_path(self, monkeypatch):
        # Mock the httpx.AsyncClient.get
        mock_resp = MagicMock()
        mock_resp.text = "<html><h1>Tortilla espanola</h1><p>3 eggs, 1 potato</p></html>"
        mock_resp.raise_for_status = MagicMock()

        class _MockClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def get(self, url): return mock_resp

        monkeypatch.setattr(
            "app.services.recipe_importer.httpx.AsyncClient", _MockClient
        )

        # Mock OpenAI completion
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = """{
          "name": "Tortilla espanola",
          "description": "Classic Spanish omelette",
          "ingredients_text": "3 eggs\\n1 potato\\nolive oil",
          "prep_minutes": 25,
          "confidence": 0.9
        }"""
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        monkeypatch.setattr(
            "app.services.recipe_importer.OpenAI", lambda *a, **kw: client
        )

        result = await import_recipe_from_url("https://example.com/tortilla")
        assert result.name == "Tortilla espanola"
        assert result.prep_minutes == 25
        assert result.confidence == 0.9
        assert "3 eggs" in result.ingredients_text

    async def test_missing_name_raises(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.text = "<html>nothing useful</html>"
        mock_resp.raise_for_status = MagicMock()

        class _MockClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def get(self, url): return mock_resp

        monkeypatch.setattr(
            "app.services.recipe_importer.httpx.AsyncClient", _MockClient
        )
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = (
            '{"name": "", "ingredients_text": null, "prep_minutes": null, "confidence": 0}'
        )
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        monkeypatch.setattr(
            "app.services.recipe_importer.OpenAI", lambda *a, **kw: client
        )

        with pytest.raises(ValidationError):
            await import_recipe_from_url("https://example.com/x")
