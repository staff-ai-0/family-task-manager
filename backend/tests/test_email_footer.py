from app.core.config import settings
from app.services.email_service import _build_html, _build_welcome_html
from app.models.user import User, UserRole


def test_build_html_footer_uses_email_link_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://family.agent-ia.mx")
    html = _build_html(
        heading="H", body="B", btn_url="https://family.agent-ia.mx/x",
        btn_text="Go", link_label="or", expiry_note="e", ignore_note="i",
    )
    assert "https://family.agent-ia.mx" in html
    assert ">family.agent-ia.mx</a>" in html   # footer anchor text, not the button URL
    assert "gcp-family.agent-ia.mx" not in html


def test_welcome_html_footer_uses_email_link_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://family.agent-ia.mx")
    html = _build_welcome_html(
        variant="parent", lang="en", user_name="A", family_name="F",
        dashboard_url="https://family.agent-ia.mx/dashboard",
        guide_url="https://family.agent-ia.mx/help",
    )
    assert "https://family.agent-ia.mx" in html
    assert ">family.agent-ia.mx</a>" in html   # footer anchor text, not the button URL
    assert "gcp-family.agent-ia.mx" not in html
