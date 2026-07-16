"""Repository for durable interview session state."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import InvalidSessionAppendException
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.interview_session import InterviewSession

TAB_SWITCH_VIOLATION_TYPE = "tab_switch"
MAX_ALLOWED_TAB_SWITCHES = 5


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _session_dict(session: InterviewSession) -> dict[str, Any]:
    return {
        column.key: getattr(session, column.key)
        for column in InterviewSession.__mapper__.column_attrs
    }


def _append_unique(
    items: list[dict[str, Any]] | None,
    item: dict[str, Any],
    *,
    id_key: str,
) -> tuple[list[dict[str, Any]], bool]:
    item_id = str(item.get(id_key) or "")
    if not item_id:
        raise InvalidSessionAppendException(
            f"{id_key} is required for idempotent append"
        )

    current = list(items or [])
    if any(str(existing.get(id_key) or "") == item_id for existing in current):
        return current, False
    return [*current, item], True


class InterviewSessionRepository:
    """Read and mutate interview state through one injected session."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the active database session."""
        self._session = session

    async def get_by_candidate_assessment_id(
        self,
        candidate_assessment_id: str | uuid.UUID,
    ) -> InterviewSession | None:
        """Return the interview session model for a candidate assessment."""

        result = await self._session.execute(
            select(InterviewSession).where(
                InterviewSession.candidate_assessment_id
                == _uuid(candidate_assessment_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_session_by_candidate_assessment_id(
        self,
        candidate_assessment_id: str | uuid.UUID,
    ) -> dict[str, Any]:
        """Return the session belonging to a candidate assessment."""

        session = await self.get_by_candidate_assessment_id(candidate_assessment_id)
        return _session_dict(session) if session else {}

    async def get_or_create_session(
        self,
        candidate_assessment_id: str | uuid.UUID,
    ) -> dict[str, Any]:
        """Create the one durable session for a candidate when absent."""

        assessment_id = _uuid(candidate_assessment_id)
        statement = (
            insert(InterviewSession)
            .values(
                candidate_assessment_id=assessment_id,
                status="INITIALIZING",
                transcript=[],
                violations=[],
                total_elapsed_secs=0,
                total_pause_secs=0,
            )
            .on_conflict_do_nothing(
                index_elements=[InterviewSession.candidate_assessment_id],
            )
        )
        await self._session.execute(statement)
        result = await self._session.execute(
            select(InterviewSession)
            .where(
                InterviewSession.candidate_assessment_id == assessment_id,
            )
            .with_for_update()
        )
        return _session_dict(result.scalar_one())

    async def append_transcript_turn(
        self,
        session_id: str | uuid.UUID,
        turn: dict[str, Any],
        *,
        total_elapsed_secs: int | None = None,
    ) -> bool:
        """Append one transcript turn, idempotently keyed by ``turn_id``."""

        session = await self._locked_session(session_id)
        transcript, appended = _append_unique(
            session.transcript,
            turn,
            id_key="turn_id",
        )
        if appended:
            session.transcript = transcript
        if total_elapsed_secs is not None:
            session.total_elapsed_secs = max(
                int(session.total_elapsed_secs or 0),
                max(0, int(total_elapsed_secs)),
            )
        session.last_updated_at = func.now()
        await self._session.flush()
        return appended

    async def append_violation(
        self,
        session_id: str | uuid.UUID,
        violation: dict[str, Any],
    ) -> bool:
        """Append one violation, idempotently keyed by ``violation_id``."""

        session = await self._locked_session(session_id)
        violations, appended = _append_unique(
            session.violations,
            violation,
            id_key="violation_id",
        )
        if appended:
            session.violations = violations
            session.last_updated_at = func.now()
            await self._session.flush()
        return appended

    async def record_tab_switch(
        self,
        session_id: str | uuid.UUID,
        *,
        connection_id: str,
        candidate_assessment_id: uuid.UUID,
        event_id: uuid.UUID,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        """Atomically append one low-severity tab switch and enforce the limit."""

        session = await self._locked_session(session_id)
        if session.candidate_assessment_id != candidate_assessment_id:
            raise InvalidSessionAppendException(
                "candidate_assessment_id does not match the interview session"
            )

        current = list(session.violations or [])
        current_count = sum(
            1
            for item in current
            if str(item.get("violation_type") or "") == TAB_SWITCH_VIOLATION_TYPE
        )
        if (
            session.status not in {"INITIALIZING", "IN_PROGRESS"}
            or session.active_connection_id != connection_id
        ):
            return {
                "appended": False,
                "tab_switch_count": current_count,
                "terminated": session.status == "TERMINATED",
                "status": session.status,
            }

        violation = {
            "violation_id": f"tab-switch:{event_id}",
            "turn_number": max(1, len(session.transcript or [])),
            "violation_type": TAB_SWITCH_VIOLATION_TYPE,
            "candidate_transcript": "",
            "severity": "low",
            "timestamp": occurred_at.isoformat(),
            "metadata": {
                "source": "browser_visibility",
                "event_id": str(event_id),
            },
        }
        violations, appended = _append_unique(
            current,
            violation,
            id_key="violation_id",
        )
        if not appended:
            return {
                "appended": False,
                "tab_switch_count": current_count,
                "terminated": session.status == "TERMINATED",
                "status": session.status,
            }

        tab_switch_count = current_count + 1
        terminated = tab_switch_count > MAX_ALLOWED_TAB_SWITCHES
        session.violations = violations
        session.last_updated_at = func.now()
        if terminated:
            session.status = "TERMINATED"
            session.reconnect_deadline = None
            session.active_connection_id = None
            await self._session.execute(
                update(CandidateAssessment)
                .where(CandidateAssessment.id == candidate_assessment_id)
                .values(
                    status="TERMINATED",
                    interview_ended_at=func.coalesce(
                        CandidateAssessment.interview_ended_at,
                        func.now(),
                    ),
                    updated_at=func.now(),
                )
            )
        await self._session.flush()
        return {
            "appended": True,
            "tab_switch_count": tab_switch_count,
            "terminated": terminated,
            "status": session.status,
        }

    async def update_elapsed_time(
        self,
        session_id: str | uuid.UUID,
        *,
        elapsed_secs: int,
        total_pause_secs: int,
    ) -> None:
        """Persist monotonically increasing elapsed and pause totals."""

        statement = (
            update(InterviewSession)
            .where(InterviewSession.id == _uuid(session_id))
            .values(
                total_elapsed_secs=func.greatest(
                    InterviewSession.total_elapsed_secs,
                    max(0, int(elapsed_secs)),
                ),
                total_pause_secs=func.greatest(
                    InterviewSession.total_pause_secs,
                    max(0, int(total_pause_secs)),
                ),
                last_updated_at=func.now(),
            )
        )
        await self._session.execute(statement)

    async def mark_session_in_progress(
        self,
        session_id: str | uuid.UUID,
    ) -> None:
        """Mark a session active and clear its reconnect deadline."""

        statement = (
            update(InterviewSession)
            .where(InterviewSession.id == _uuid(session_id))
            .values(
                status="IN_PROGRESS",
                reconnect_deadline=None,
                last_updated_at=func.now(),
            )
        )
        await self._session.execute(statement)

    async def complete_session(
        self,
        session_id: str | uuid.UUID,
        *,
        total_elapsed_secs: int,
    ) -> None:
        """Mark a session completed before holistic evaluation."""

        statement = (
            update(InterviewSession)
            .where(InterviewSession.id == _uuid(session_id))
            .values(
                status="COMPLETED",
                total_elapsed_secs=max(0, int(total_elapsed_secs)),
                reconnect_deadline=None,
                active_connection_id=None,
                last_updated_at=func.now(),
            )
        )
        await self._session.execute(statement)

    async def _locked_session(
        self,
        session_id: str | uuid.UUID,
    ) -> InterviewSession:
        result = await self._session.execute(
            select(InterviewSession)
            .where(InterviewSession.id == _uuid(session_id))
            .with_for_update()
        )
        return result.scalar_one()
