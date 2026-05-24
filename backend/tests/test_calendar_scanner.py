"""Calendar scanner tests with mocked LiteLLM (W2.2)."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.core.exceptions import ValidationError
from app.services.calendar_scanner_service import scan_calendar_document


def _mock_completion(json_text: str):
    msg = MagicMock()
    msg.content = json_text
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    monkeypatch.setattr(
        config.settings, "LITELLM_API_BASE", "https://litellm.test"
    )


class TestCalendarScanner:
    async def test_no_api_key_raises(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
        with pytest.raises(ValidationError):
            await scan_calendar_document(b"x", "image/png")

    async def test_parses_events(self):
        payload = """{
          "doc_type": "school_flyer",
          "events": [
            {"title": "Soccer practice", "start_iso": "2026-06-01T15:00:00", "end_iso": "2026-06-01T17:00:00", "all_day": false, "location": "Field 3", "description": "Bring water"},
            {"title": "Picture day", "start_iso": "2026-06-05T00:00:00", "all_day": true}
          ],
          "confidence": 0.92
        }"""
        with patch(
            "app.services.calendar_scanner_service.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = _mock_completion(payload)
            mock_openai.return_value = client
            result = await scan_calendar_document(b"fake", "image/jpeg")
        assert result.doc_type == "school_flyer"
        assert result.confidence == pytest.approx(0.92)
        assert len(result.events) == 2
        assert result.events[0].title == "Soccer practice"
        assert result.events[0].start_ts == datetime(2026, 6, 1, 15, 0, 0)
        assert result.events[1].all_day is True

    async def test_skips_events_without_date(self):
        payload = """{
          "doc_type": "other",
          "events": [
            {"title": "No date here", "start_iso": null, "all_day": false},
            {"title": "Has date", "start_iso": "2026-06-10T09:00:00"}
          ],
          "confidence": 0.4
        }"""
        with patch("app.services.calendar_scanner_service.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = _mock_completion(payload)
            mock_openai.return_value = client
            result = await scan_calendar_document(b"x", "image/png")
        assert len(result.events) == 1
        assert result.events[0].title == "Has date"

    async def test_bad_json_raises(self):
        with patch("app.services.calendar_scanner_service.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = _mock_completion(
                "not json at all"
            )
            mock_openai.return_value = client
            with pytest.raises(ValidationError):
                await scan_calendar_document(b"x", "image/png")
