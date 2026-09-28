"""Jarvis history must not leak the internal "[actions: …]" suffix (UX-A).

The suffix stays in storage — _load_history replays it to the model as
context — but GET /api/jarvis/history returns clean text plus an actions list.
"""
import pytest
from httpx import AsyncClient

from app.models.jarvis_message import JarvisMessage
from app.services.jarvis_service import (
    SYSTEM_BASE,
    SYSTEM_TEEN,
    JarvisService,
    split_actions_suffix,
)


class TestSplitActionsSuffix:
    def test_no_suffix(self):
        assert split_actions_suffix("Hola.") == ("Hola.", [])

    def test_one_action(self):
        assert split_actions_suffix("Listo.\n\n[actions: budget_spending_report(ok)]") == (
            "Listo.", ["budget_spending_report(ok)"],
        )

    def test_many_actions(self):
        text, actions = split_actions_suffix(
            "Hecho.\n\n[actions: shopping_add_item(ok), calendar_create_event(pending), x(err)]"
        )
        assert text == "Hecho."
        assert actions == ["shopping_add_item(ok)", "calendar_create_event(pending)", "x(err)"]

    def test_suffix_like_text_mid_message_is_untouched(self):
        content = "Hecho.\n\n[actions: x(ok)]\nY algo más que dijo el modelo."
        assert split_actions_suffix(content) == (content, [])

    def test_empty(self):
        assert split_actions_suffix("") == ("", [])


def test_prompts_require_formatted_money():
    for prompt in (SYSTEM_BASE, SYSTEM_TEEN):
        assert "thousands separators" in prompt
        assert "$13,849 MXN" in prompt


async def _seed(db, family_id, user_id, role, content):
    db.add(JarvisMessage(family_id=family_id, user_id=user_id, role=role, content=content, mode="copilot"))
    await db.commit()


@pytest.mark.asyncio
async def test_history_endpoint_strips_suffix_and_returns_actions(
    client: AsyncClient, auth_headers, db_session, test_family, test_parent_user,
):
    await _seed(db_session, test_family.id, test_parent_user.id, "user", "¿y [actions: x]?")
    await _seed(
        db_session, test_family.id, None, "assistant",
        "Gastaron $13,849 MXN.\n\n[actions: budget_spending_report(ok)]",
    )
    r = await client.get("/api/jarvis/history", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert [m["content"] for m in items] == ["¿y [actions: x]?", "Gastaron $13,849 MXN."]
    assert items[0]["actions"] == []
    assert items[1]["actions"] == ["budget_spending_report(ok)"]


@pytest.mark.asyncio
async def test_model_history_still_carries_the_suffix(db_session, test_family, test_parent_user):
    await _seed(
        db_session, test_family.id, None, "assistant",
        "Ok.\n\n[actions: budget_spending_report(ok)]",
    )
    rows = await JarvisService.list_history(db_session, test_family.id, user_id=test_parent_user.id)
    assert rows[-1].content.endswith("[actions: budget_spending_report(ok)]")
