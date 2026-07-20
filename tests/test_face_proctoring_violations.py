"""Face presence/count violation persistence and termination contracts."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.core.exceptions import InvalidSessionAppendException
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)


def _session(
    candidate_assessment_id: UUID,
    *,
    connection_id: str = "connection-current",
) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_assessment_id=candidate_assessment_id,
        active_connection_id=connection_id,
        status="IN_PROGRESS",
        violations=[],
        transcript=[],
        reconnect_deadline=None,
        last_updated_at=None,
    )


def _event_kwargs(
    candidate_assessment_id: UUID,
    *,
    event_id: UUID | None = None,
    event_type: str = "face_absent",
    duration_ms: int = 5_000,
    source: str = "mediapipe_face_detector",
    started_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "connection_id": "connection-current",
        "candidate_assessment_id": candidate_assessment_id,
        "event_id": event_id or uuid4(),
        "event_type": event_type,
        "condition_started_at": started_at or datetime.now(UTC),
        "observed_duration_ms": duration_ms,
        "sample_count": 11,
        "max_face_count": 0 if event_type == "face_absent" else 2,
        "min_confidence": 0.72,
        "max_confidence": 0.94,
        "source": source,
        "detector_version": "mediapipe-tasks-vision@0.10.35",
        "model_name": "blaze_face_short_range_float16",
    }


@pytest.mark.parametrize(  # type: ignore[misc]
    ("event_type", "duration_ms"),
    [("face_absent", 5_000), ("multiple_faces", 3_000)],
)
async def test_face_proctoring_event_is_one_high_evaluation_violation(
    event_type: str,
    duration_ms: int,
) -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    outcome = await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            event_type=event_type,
            duration_ms=duration_ms,
        ),
    )

    assert outcome == {
        "appended": True,
        "recorded": True,
        "occurrence_count": 1,
        "terminated": False,
        "termination_reason": None,
        "status": "IN_PROGRESS",
    }
    assert len(session.violations) == 1
    violation = session.violations[0]
    assert violation["violation_id"] == f"proctoring:{event_type}"
    assert violation["violation_type"] == event_type
    assert violation["severity"] == "high"
    assert violation["metadata"]["affects_evaluation"] is True
    assert violation["metadata"]["review_status"] == "server_qualified"
    assert violation["metadata"]["occurrence_count"] == 1
    assert violation["metadata"]["raw_frames_uploaded"] is False
    db.flush.assert_awaited_once()


async def test_repeated_face_absence_updates_metadata_without_new_violation() -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    first_started_at = datetime.now(UTC)

    first = await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(candidate_assessment_id, started_at=first_started_at),
    )
    second = await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            started_at=first_started_at + timedelta(minutes=1),
        ),
    )

    assert first["appended"] is True
    assert second["appended"] is False
    assert second["recorded"] is True
    assert second["occurrence_count"] == 2
    assert len(session.violations) == 1
    metadata = session.violations[0]["metadata"]
    assert metadata["occurrence_count"] == 2
    assert metadata["event_count"] == 2
    assert len(metadata["episodes"]) == 2


@pytest.mark.parametrize(  # type: ignore[misc]
    ("event_type", "warning_ms", "termination_ms", "reason"),
    [
        (
            "face_absent",
            5_000,
            30_000,
            "face_absent_continuous_duration_exceeded",
        ),
        (
            "multiple_faces",
            3_000,
            20_000,
            "multiple_faces_continuous_duration_exceeded",
        ),
    ],
)
async def test_continuous_face_condition_terminates_and_updates_same_episode(
    event_type: str,
    warning_ms: int,
    termination_ms: int,
    reason: str,
) -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    started_at = datetime.now(UTC)

    await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            event_type=event_type,
            duration_ms=warning_ms,
            started_at=started_at,
        ),
    )
    outcome = await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            event_type=event_type,
            duration_ms=termination_ms,
            started_at=started_at,
        ),
    )

    assert outcome == {
        "appended": False,
        "recorded": True,
        "occurrence_count": 1,
        "terminated": True,
        "termination_reason": reason,
        "status": "TERMINATED",
    }
    assert session.status == "TERMINATED"
    assert session.active_connection_id is None
    assert len(session.violations) == 1
    metadata = session.violations[0]["metadata"]
    assert metadata["occurrence_count"] == 1
    assert metadata["event_count"] == 2
    assert metadata["max_observed_duration_ms"] == termination_ms
    assert metadata["termination_triggered"] is True
    assert metadata["termination_reason"] == reason
    db.execute.assert_awaited_once()
    assert db.flush.await_count == 2


@pytest.mark.parametrize(  # type: ignore[misc]
    ("event_type", "duration_ms"),
    [("face_absent", 29_999), ("multiple_faces", 19_999)],
)
async def test_face_termination_requires_full_continuous_threshold(
    event_type: str,
    duration_ms: int,
) -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    outcome = await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            event_type=event_type,
            duration_ms=duration_ms,
        ),
    )

    assert outcome["terminated"] is False
    assert session.status == "IN_PROGRESS"
    db.execute.assert_not_awaited()


async def test_face_event_is_transport_idempotent_and_rejects_stale_connection() -> (
    None
):
    candidate_assessment_id = uuid4()
    event_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    kwargs = _event_kwargs(candidate_assessment_id, event_id=event_id)

    first = await repository.record_proctoring_event(uuid4(), **kwargs)
    duplicate = await repository.record_proctoring_event(uuid4(), **kwargs)
    stale = await repository.record_proctoring_event(
        uuid4(),
        **{**kwargs, "connection_id": "connection-replaced", "event_id": uuid4()},
    )

    assert first["appended"] is True
    assert duplicate == {
        "appended": False,
        "recorded": False,
        "occurrence_count": 1,
        "terminated": False,
        "termination_reason": None,
        "status": "IN_PROGRESS",
    }
    assert stale == duplicate
    assert len(session.violations) == 1
    assert db.flush.await_count == 1


async def test_each_face_category_has_at_most_one_high_violation() -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(candidate_assessment_id, event_type="face_absent"),
    )
    await repository.record_proctoring_event(
        uuid4(),
        **_event_kwargs(
            candidate_assessment_id,
            event_type="multiple_faces",
            duration_ms=3_000,
        ),
    )

    assert len(session.violations) == 2
    assert {item["violation_type"] for item in session.violations} == {
        "face_absent",
        "multiple_faces",
    }
    assert all(item["severity"] == "high" for item in session.violations)


@pytest.mark.parametrize(  # type: ignore[misc]
    ("event_type", "duration_ms", "source"),
    [
        ("face_absent", 4_999, "mediapipe_face_detector"),
        ("multiple_faces", 2_999, "mediapipe_face_detector"),
        ("multiple_faces", 3_000, "camera_state"),
    ],
)
async def test_face_proctoring_event_rejects_invalid_policy_claims(
    event_type: str,
    duration_ms: int,
    source: str,
) -> None:
    candidate_assessment_id = uuid4()
    repository = InterviewSessionRepository(AsyncMock())
    repository._locked_session = AsyncMock(  # type: ignore[method-assign]
        return_value=_session(candidate_assessment_id)
    )

    with pytest.raises(InvalidSessionAppendException):
        await repository.record_proctoring_event(
            uuid4(),
            **_event_kwargs(
                candidate_assessment_id,
                event_type=event_type,
                duration_ms=duration_ms,
                source=source,
            ),
        )
