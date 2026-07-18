from typing import Any

import pytest

from src.utils import candidates


async def test_invitation_cta_remains_visible_in_dark_mode_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeTransactionalEmails:
        async def send_transac_email(self, **kwargs: Any) -> dict[str, str]:
            captured.update(kwargs)
            return {"message_id": "test-message"}

    class FakeBrevo:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.transactional_emails = FakeTransactionalEmails()

    monkeypatch.setattr(candidates, "AsyncBrevo", FakeBrevo)

    invitation_link = "https://example.test/interview?token=test-token"
    await candidates.send_invitation_email(
        candidate_name="Asha Rao",
        recipient_email="asha@example.test",
        assessment_title="Backend Hiring",
        role_name="Backend Engineer",
        invitation_link=invitation_link,
        interview_duration_mins=30,
    )

    html = captured["html_content"]
    assert isinstance(html, str)
    assert '<meta name="color-scheme" content="light only"' in html
    assert '<meta name="supported-color-schemes" content="light only"' in html
    assert 'class="interview-cta-cell"' in html
    assert 'bgcolor="#4f46e5"' in html
    assert "background-color:#4f46e5 !important" in html
    assert "background-image:linear-gradient" in html
    assert "-webkit-text-fill-color:#ffffff !important" in html
    assert '<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"' in html
    assert 'role="button"' in html
    assert "Start Your Interview &#8594;" in html
    assert html.count(f'href="{invitation_link}"') >= 3
