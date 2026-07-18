"""Automatic assessment expiry and candidate-window guards."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from src.core.services.interview_session_service import InterviewSessionService
from src.data.clients.celery_client import celery_app
from src.data.repositories.assessment_repository import AssessmentRepository


async def test_expiry_repository_returns_only_rows_closed_by_atomic_update() -> None:
    db = AsyncMock()
    result = Mock()
    expired = {
        "id": uuid4(),
        "recruiter_id": uuid4(),
        "title": "Backend Hiring",
        "role_name": "Backend Engineer",
    }
    result.mappings.return_value.all.return_value = [expired]
    db.execute.return_value = result
    repository = AssessmentRepository(db)

    rows = await repository.close_expired_assessments()

    assert rows == [expired]
    db.flush.assert_awaited_once()
    statement = str(db.execute.await_args.args[0])
    assert "window_end <= now()" in statement
    assert "status !=" in statement


def test_periodic_expiry_task_is_scheduled_every_minute() -> None:
    schedule = celery_app.conf.beat_schedule["close-expired-assessments-every-minute"]

    assert schedule["task"] == "core.close_expired_assessments"
    assert schedule["schedule"] == 60.0


def test_unstarted_candidate_token_expires_with_assessment_window() -> None:
    now = datetime.now(UTC)
    context = {
        "session_token_expires_at": now + timedelta(hours=1),
        "window_end": now - timedelta(seconds=1),
        "interview_started_at": None,
        "session_status": "INITIALIZING",
        "candidate_assessment_status": "INVITED",
    }

    assert InterviewSessionService._validate_active_token(context) is not None

    context["interview_started_at"] = now - timedelta(minutes=5)
    assert InterviewSessionService._validate_active_token(context) is None
