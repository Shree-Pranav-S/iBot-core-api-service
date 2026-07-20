"""Atomic tab-switch violation persistence and termination contracts."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.services.interview_session_service import _tab_switch_count
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)


def _tab_violation(
    event_id: object,
    *,
    occurrence_count: int | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"event_id": str(event_id)}
    if occurrence_count is not None:
        metadata = {
            "event_ids": [str(event_id)],
            "occurrence_count": occurrence_count,
            "tab_switch_count": occurrence_count,
        }
    return {
        "violation_id": "proctoring:tab_switch",
        "violation_type": "tab_switch",
        "severity": "low",
        "metadata": metadata,
    }


def test_durable_tab_switch_count_ignores_other_violation_types() -> None:
    violations = [
        _tab_violation(uuid4()),
        {"violation_type": "prompt_injection", "severity": "critical"},
        _tab_violation(uuid4()),
        "invalid-entry",
    ]

    assert _tab_switch_count(violations) == 2
    assert _tab_switch_count([_tab_violation(uuid4(), occurrence_count=4)]) == 4
    assert _tab_switch_count(None) == 0


def _session(
    *,
    candidate_assessment_id: object,
    connection_id: str = "connection-current",
    violations: list[dict[str, object]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_assessment_id=candidate_assessment_id,
        active_connection_id=connection_id,
        status="IN_PROGRESS",
        violations=list(violations or []),
        transcript=[],
        reconnect_deadline=None,
        last_updated_at=None,
    )


@pytest.mark.parametrize(  # type: ignore[misc]
    ("existing_count", "expected_count", "terminated"),
    [(3, 4, False), (4, 5, True)],
)
async def test_tab_switch_uses_one_low_violation_and_terminates_on_fifth(
    existing_count: int,
    expected_count: int,
    terminated: bool,
) -> None:
    candidate_assessment_id = uuid4()
    first_event_id = uuid4()
    current = (
        [_tab_violation(first_event_id, occurrence_count=existing_count)]
        if existing_count
        else []
    )
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    session = _session(
        candidate_assessment_id=candidate_assessment_id,
        violations=current,
    )
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    outcome = await repository.record_tab_switch(
        uuid4(),
        connection_id="connection-current",
        candidate_assessment_id=candidate_assessment_id,
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )

    assert outcome["appended"] is False
    assert outcome["recorded"] is True
    assert outcome["tab_switch_count"] == expected_count
    assert outcome["terminated"] is terminated
    assert len(session.violations) == 1
    violation = session.violations[0]
    assert violation["severity"] == "low"
    assert violation["metadata"]["occurrence_count"] == expected_count
    assert violation["metadata"]["termination_triggered"] is terminated
    assert session.status == ("TERMINATED" if terminated else "IN_PROGRESS")
    assert db.execute.await_count == (1 if terminated else 0)
    db.flush.assert_awaited_once()


async def test_duplicate_or_stale_tab_switch_is_not_counted() -> None:
    candidate_assessment_id = uuid4()
    event_id = uuid4()
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    session = _session(
        candidate_assessment_id=candidate_assessment_id,
        violations=[_tab_violation(event_id)],
    )
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    duplicate = await repository.record_tab_switch(
        uuid4(),
        connection_id="connection-current",
        candidate_assessment_id=candidate_assessment_id,
        event_id=event_id,
        occurred_at=datetime.now(UTC),
    )
    stale = await repository.record_tab_switch(
        uuid4(),
        connection_id="connection-replaced",
        candidate_assessment_id=candidate_assessment_id,
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )

    assert duplicate == {
        "appended": False,
        "recorded": False,
        "tab_switch_count": 1,
        "terminated": False,
        "status": "IN_PROGRESS",
    }
    assert stale == duplicate
    db.flush.assert_not_awaited()


async def test_first_tab_switch_creates_one_canonical_low_violation() -> None:
    candidate_assessment_id = uuid4()
    session = _session(candidate_assessment_id=candidate_assessment_id)
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    outcome = await repository.record_tab_switch(
        uuid4(),
        connection_id="connection-current",
        candidate_assessment_id=candidate_assessment_id,
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )

    assert outcome["appended"] is True
    assert outcome["recorded"] is True
    assert outcome["tab_switch_count"] == 1
    assert len(session.violations) == 1
    assert session.violations[0]["violation_id"] == "proctoring:tab_switch"
    assert session.violations[0]["metadata"]["affects_evaluation"] is True


async def test_legacy_tab_violations_are_consolidated_without_losing_count() -> None:
    candidate_assessment_id = uuid4()
    current = [_tab_violation(uuid4()) for _ in range(3)]
    session = _session(
        candidate_assessment_id=candidate_assessment_id,
        violations=current,
    )
    db = AsyncMock()
    repository = InterviewSessionRepository(db)
    repository._locked_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    outcome = await repository.record_tab_switch(
        uuid4(),
        connection_id="connection-current",
        candidate_assessment_id=candidate_assessment_id,
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )

    assert outcome["tab_switch_count"] == 4
    assert len(session.violations) == 1
    assert session.violations[0]["metadata"]["occurrence_count"] == 4
