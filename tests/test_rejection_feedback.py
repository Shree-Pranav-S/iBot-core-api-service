import pytest

from src.config.settings import settings
from src.utils.candidates import generate_rejection_feedback


@pytest.mark.asyncio  # type: ignore[misc]
async def test_rejection_feedback_uses_evidence_based_fallback_without_api_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "FALLBACK_GROQ_API_KEY", "")

    feedback = await generate_rejection_feedback(
        candidate_name="Maya Desai",
        role_name="Platform Engineer",
        assessment_title="Platform Engineering",
        overall_summary="Strong collaboration with limited production examples.",
        recommendation_reasoning="The role requires deeper operational ownership.",
        strengths=["Clear communication"],
        concerns=["Providing more specific production evidence"],
    )

    assert "Maya" in feedback
    assert "clear communication" in feedback.lower()
    assert "specific production evidence" in feedback.lower()
    assert "score" not in feedback.lower()
    assert len(feedback) <= 2000
