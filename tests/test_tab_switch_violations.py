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


def _tab_violation(event_id: object) -> dict[str, object]:
    return {
        "violation_id": f"tab-switch:{event_id}",
        "violation_type": "tab_switch",
        "severity": "low",
    }


def test_durable_tab_switch_count_ignores_other_violation_types() -> None:
    violations = [
        _tab_violation(uuid4()),
        {"violation_type": "prompt_injection", "severity": "critical"},
        _tab_violation(uuid4()),
        "invalid-entry",
    ]

    assert _tab_switch_count(violations) == 2
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
    [(4, 5, False), (5, 6, True)],
)
async def test_tab_switch_terminates_only_after_more_than_five(
    existing_count: int,
    expected_count: int,
    terminated: bool,
) -> None:
    candidate_assessment_id = uuid4()
    current = [_tab_violation(uuid4()) for _ in range(existing_count)]
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

    assert outcome["appended"] is True
    assert outcome["tab_switch_count"] == expected_count
    assert outcome["terminated"] is terminated
    assert len(session.violations) == expected_count
    assert session.violations[-1]["severity"] == "low"
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
        "tab_switch_count": 1,
        "terminated": False,
        "status": "IN_PROGRESS",
    }
    assert stale == duplicate
    db.flush.assert_not_awaited()
