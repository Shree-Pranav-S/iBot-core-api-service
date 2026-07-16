from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.api.rest.app import create_app
from src.api.rest.routes.evaluation import create_approval_feedback
from src.config.settings import settings
from src.core.exceptions import (
    EvaluationAccessDeniedException,
    EvaluationNotFoundException,
)
from src.core.services.evaluation_service import EvaluationService
from src.schemas.candidate import AIApprovalFeedbackResponse
from src.utils.candidates import generate_candidate_decision_feedback

EVIDENCE: dict[str, Any] = {
    "candidate_name": "Asha Rao",
    "role_name": "Platform Engineer",
    "assessment_title": "Platform Engineering Interview",
    "overall_summary": "Asha communicated clearly and solved the technical tasks.",
    "recommendation_reasoning": "Strong evidence across the priority skills.",
    "strengths": ["clear technical reasoning", "thoughtful communication"],
    "concerns": ["adding more detail to operational examples"],
}


@pytest.mark.parametrize(  # type: ignore[misc]
    ("decision", "expected", "excluded"),
    [
        ("APPROVED", "pleased to move forward", "not to move forward"),
        ("REJECTED", "not to move forward", "pleased to move forward"),
    ],
)
async def test_decision_feedback_has_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    expected: str,
    excluded: str,
) -> None:
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "FALLBACK_GROQ_API_KEY", "")

    feedback = await generate_candidate_decision_feedback(
        decision=decision,  # type: ignore[arg-type]
        **EVIDENCE,
    )

    assert expected in feedback
    assert excluded not in feedback
    assert len(feedback) <= 2000


async def test_approval_feedback_uses_owned_evaluation_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter_id = uuid4()
    candidate_assessment_id = uuid4()
    candidate_assessment_repo = AsyncMock()
    evaluation_repo = AsyncMock()
    session_repo = AsyncMock()
    candidate_assessment_repo.get_by_id.return_value = SimpleNamespace(
        id=candidate_assessment_id,
        candidate=SimpleNamespace(full_name="Asha Rao"),
        assessment=SimpleNamespace(
            recruiter_id=recruiter_id,
            role_name="Platform Engineer",
            title="Platform Engineering Interview",
        ),
    )
    evaluation_repo.get_by_candidate_assessment_id.return_value = SimpleNamespace(
        overall_summary=EVIDENCE["overall_summary"],
        recommendation_reasoning=EVIDENCE["recommendation_reasoning"],
        strengths=EVIDENCE["strengths"],
        concerns=EVIDENCE["concerns"],
    )
    generated = AsyncMock(return_value="We are pleased to move forward.")
    monkeypatch.setattr(
        "src.core.services.evaluation_service.generate_approval_feedback",
        generated,
    )
    service = EvaluationService(
        candidate_assessment_repo,
        evaluation_repo,
        session_repo,
    )

    result = await service.create_approval_feedback(
        candidate_assessment_id,
        recruiter_id,
    )

    assert result == AIApprovalFeedbackResponse(
        feedback="We are pleased to move forward."
    )
    generated.assert_awaited_once_with(**EVIDENCE)


async def test_approval_feedback_rejects_other_recruiter() -> None:
    candidate_assessment_repo = AsyncMock()
    candidate_assessment_repo.get_by_id.return_value = SimpleNamespace(
        candidate=SimpleNamespace(full_name="Asha Rao"),
        assessment=SimpleNamespace(recruiter_id=uuid4()),
    )
    service = EvaluationService(
        candidate_assessment_repo,
        AsyncMock(),
        AsyncMock(),
    )

    with pytest.raises(EvaluationAccessDeniedException):
        await service.create_approval_feedback(uuid4(), uuid4())


async def test_approval_feedback_requires_evaluation() -> None:
    recruiter_id = uuid4()
    candidate_assessment_repo = AsyncMock()
    candidate_assessment_repo.get_by_id.return_value = SimpleNamespace(
        candidate=SimpleNamespace(full_name="Asha Rao"),
        assessment=SimpleNamespace(
            recruiter_id=recruiter_id,
            role_name="Platform Engineer",
            title="Platform Engineering Interview",
        ),
    )
    evaluation_repo = AsyncMock()
    evaluation_repo.get_by_candidate_assessment_id.return_value = None
    service = EvaluationService(
        candidate_assessment_repo,
        evaluation_repo,
        AsyncMock(),
    )

    with pytest.raises(EvaluationNotFoundException):
        await service.create_approval_feedback(uuid4(), recruiter_id)


async def test_approval_route_response_shape() -> None:
    candidate_assessment_id = uuid4()
    recruiter_id = uuid4()
    service = SimpleNamespace(
        create_approval_feedback=AsyncMock(
            return_value=AIApprovalFeedbackResponse(feedback="Approval draft")
        )
    )

    response = await create_approval_feedback(
        candidate_assessment_id,
        recruiter_id,
        service,  # type: ignore[arg-type]
    )

    assert response.model_dump(mode="json") == {
        "success": True,
        "message": "Approval message draft generated successfully.",
        "data": {"feedback": "Approval draft"},
    }
    assert "/evaluations/{ca_id}/approval-feedback" in create_app().openapi()["paths"]
