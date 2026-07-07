"""Business logic for recruiter-facing evaluation display operations."""

import uuid
from typing import Any

from src.core.exceptions import ForbiddenException, NotFoundException
from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.candidate import Candidate
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.interview_evaluation import InterviewEvaluation
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)
from src.schemas.candidate import (
    AIRejectionFeedbackResponse,
    InterviewTranscriptResponse,
    TranscriptTurn,
)
from src.schemas.evaluation import (
    InterviewEvaluationResponse,
    RecruiterEvaluationListItem,
)
from src.utils.candidates import generate_rejection_feedback


class EvaluationService:
    """Service layer for recruiter evaluation pages and reports."""

    def __init__(
        self,
        candidate_assessment_repo: CandidateAssessmentRepository,
        evaluation_repo: EvaluationRepository,
        session_repo: InterviewSessionRepository,
    ) -> None:
        """Initialize the service with repositories used by evaluation views."""
        self._ca_repo = candidate_assessment_repo
        self._evaluation_repo = evaluation_repo
        self._session_repo = session_repo

    async def list_recruiter_evaluations(
        self,
        recruiter_id: uuid.UUID,
    ) -> list[RecruiterEvaluationListItem]:
        """Return compact evaluation cards for all assessments owned by a recruiter."""
        rows = await self._evaluation_repo.list_by_recruiter(recruiter_id)
        return [
            self._build_list_item(evaluation, ca, candidate, assessment)
            for evaluation, ca, candidate, assessment in rows
        ]

    async def get_candidate_evaluation(
        self,
        ca_id: uuid.UUID,
        recruiter_id: uuid.UUID,
    ) -> InterviewEvaluationResponse:
        """Return the full evaluation report after enforcing recruiter ownership."""
        ca = await self._get_owned_candidate_assessment(
            ca_id,
            recruiter_id,
            resource_name="evaluation",
        )
        evaluation = await self._evaluation_repo.get_by_candidate_assessment_id(ca_id)
        if evaluation is None:
            raise NotFoundException("Evaluation not found for this candidate.")

        response = InterviewEvaluationResponse.model_validate(
            evaluation,
            from_attributes=True,
        )
        response.candidate_name = ca.candidate.full_name if ca.candidate else None
        response.candidate_email = ca.candidate.email if ca.candidate else None
        response.assessment_title = ca.assessment.title if ca.assessment else None
        response.role_name = ca.assessment.role_name if ca.assessment else None
        response.recruiter_decision = ca.recruiter_decision
        response.recruiter_feedback = ca.recruiter_feedback
        return response

    async def get_interview_transcript(
        self,
        ca_id: uuid.UUID,
        recruiter_id: uuid.UUID,
    ) -> InterviewTranscriptResponse:
        """Return the interview transcript after enforcing recruiter ownership."""
        ca = await self._get_owned_candidate_assessment(
            ca_id,
            recruiter_id,
            resource_name="transcript",
        )
        session = await self._session_repo.get_by_candidate_assessment_id(ca_id)

        turns: list[TranscriptTurn] = []
        total_elapsed_secs = 0
        if session is not None:
            total_elapsed_secs = session.total_elapsed_secs or 0
            turns = [
                _build_transcript_turn(raw_turn, index)
                for index, raw_turn in enumerate(session.transcript, start=1)
                if isinstance(raw_turn, dict)
            ]

        return InterviewTranscriptResponse(
            candidate_assessment_id=ca_id,
            candidate_name=ca.candidate.full_name if ca.candidate else None,
            assessment_title=ca.assessment.title if ca.assessment else None,
            total_elapsed_secs=total_elapsed_secs,
            turns=turns,
        )

    async def create_rejection_feedback(
        self,
        ca_id: uuid.UUID,
        recruiter_id: uuid.UUID,
    ) -> AIRejectionFeedbackResponse:
        """Draft candidate-facing rejection feedback from persisted evidence."""
        ca = await self._get_owned_candidate_assessment(
            ca_id,
            recruiter_id,
            resource_name="evaluation",
        )
        evaluation = await self._evaluation_repo.get_by_candidate_assessment_id(ca_id)
        if evaluation is None:
            raise NotFoundException("Evaluation not found for this candidate.")

        feedback = await generate_rejection_feedback(
            candidate_name=ca.candidate.full_name if ca.candidate else "Candidate",
            role_name=ca.assessment.role_name,
            assessment_title=ca.assessment.title,
            overall_summary=evaluation.overall_summary,
            recommendation_reasoning=evaluation.recommendation_reasoning,
            strengths=list(evaluation.strengths or []),
            concerns=list(evaluation.concerns or []),
        )
        return AIRejectionFeedbackResponse(feedback=feedback)

    async def _get_owned_candidate_assessment(
        self,
        ca_id: uuid.UUID,
        recruiter_id: uuid.UUID,
        *,
        resource_name: str,
    ) -> CandidateAssessment:
        ca = await self._ca_repo.get_by_id(ca_id)
        if ca is None:
            raise NotFoundException("Candidate registration not found.")
        if ca.assessment is None:
            raise NotFoundException("Assessment not found for this candidate.")
        if ca.assessment.recruiter_id != recruiter_id:
            raise ForbiddenException(f"You do not have access to this {resource_name}.")
        return ca

    def _build_list_item(
        self,
        evaluation: InterviewEvaluation,
        ca: CandidateAssessment,
        candidate: Candidate,
        assessment: Assessment,
    ) -> RecruiterEvaluationListItem:
        return RecruiterEvaluationListItem(
            candidate_assessment_id=ca.id,
            candidate_name=candidate.full_name,
            candidate_email=candidate.email,
            assessment_id=assessment.id,
            assessment_title=assessment.title,
            role_name=assessment.role_name,
            recruiter_decision=ca.recruiter_decision,
            interview_started_at=ca.interview_started_at,
            interview_ended_at=ca.interview_ended_at,
            generated_at=evaluation.generated_at,
            overall_score=evaluation.overall_score,
            hiring_recommendation=evaluation.hiring_recommendation,
            recommendation_reasoning=evaluation.recommendation_reasoning,
            overall_summary=evaluation.overall_summary,
            overall_technical_skill_score=evaluation.overall_technical_skill_score,
            behavioural_cultural_score=evaluation.behavioural_cultural_score,
            communication_score=evaluation.communication_score,
            rank_in_assessment=evaluation.rank_in_assessment,
            percentile_in_assessment=evaluation.percentile_in_assessment,
            total_candidates_evaluated=evaluation.total_candidates_evaluated,
            strengths=evaluation.strengths,
            concerns=evaluation.concerns,
            validated_violation_count=_validated_violation_count(
                evaluation.violation_summary,
            ),
            skill_scores=evaluation.skill_scores,
        )


def _validated_violation_count(violation_summary: object) -> int:
    if not isinstance(violation_summary, dict):
        return 0
    raw_count = violation_summary.get("validated_violation_count", 0) or 0
    try:
        return int(raw_count)
    except (TypeError, ValueError):
        return 0


def _build_transcript_turn(
    raw_turn: dict[str, Any],
    fallback_turn_number: int,
) -> TranscriptTurn:
    metadata = raw_turn.get("metadata")
    parsed_metadata: dict[str, Any] = (
        dict(metadata) if isinstance(metadata, dict) else {}
    )
    return TranscriptTurn(
        turn_number=_safe_int(raw_turn.get("turn_number"), fallback_turn_number),
        turn_id=_first_string(raw_turn.get("turn_id")),
        speaker=str(raw_turn.get("speaker", "unknown")),
        text=str(raw_turn.get("text", "")),
        tone=raw_turn.get("tone"),
        timestamp=_first_string(raw_turn.get("timestamp")),
        elapsed_secs=_safe_elapsed_secs(parsed_metadata.get("elapsed_secs")),
        question_id=_first_string(
            raw_turn.get("question_id"),
            parsed_metadata.get("question_id"),
        ),
        section=_first_string(
            raw_turn.get("current_section"),
            raw_turn.get("section"),
            parsed_metadata.get("current_section"),
            parsed_metadata.get("section"),
        ),
        skill=_first_string(
            raw_turn.get("current_skill"),
            raw_turn.get("skill"),
            parsed_metadata.get("current_skill"),
            parsed_metadata.get("skill"),
        ),
        difficulty=_first_string(
            raw_turn.get("question_difficulty"),
            raw_turn.get("difficulty"),
            parsed_metadata.get("question_difficulty"),
            parsed_metadata.get("difficulty"),
        ),
        question_type=_first_string(
            raw_turn.get("question_type"),
            parsed_metadata.get("question_type"),
        ),
        response_type=_first_string(
            raw_turn.get("response_type"),
            parsed_metadata.get("response_type"),
        ),
    )


def _first_string(*values: object) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return fallback


def _safe_elapsed_secs(value: object) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
