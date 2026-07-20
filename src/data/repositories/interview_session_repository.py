"""Repository for durable interview session state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import InvalidSessionAppendException
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.interview_session import InterviewSession

TAB_SWITCH_VIOLATION_TYPE = "tab_switch"
MAX_ALLOWED_TAB_SWITCHES = 5
TAB_SWITCH_VIOLATION_ID = "proctoring:tab_switch"
FACE_PROCTORING_POLICIES: dict[str, tuple[int, int]] = {
    # (minimum duration for a violation, continuous duration for termination)
    "face_absent": (5_000, 30_000),
    "multiple_faces": (3_000, 20_000),
}


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


def _metadata(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    value = item.get("metadata")
    return value if isinstance(value, dict) else {}


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def tab_switch_count(violations: object) -> int:
    """Return the authoritative tab occurrence count across old and new records."""

    if not isinstance(violations, list):
        return 0
    tab_violations = [
        item
        for item in violations
        if isinstance(item, dict)
        and item.get("violation_type") == TAB_SWITCH_VIOLATION_TYPE
    ]
    declared_counts = [
        count
        for item in tab_violations
        for count in (
            _positive_int(_metadata(item).get("occurrence_count")),
            _positive_int(_metadata(item).get("tab_switch_count")),
        )
        if count is not None
    ]
    return max([len(tab_violations), *declared_counts], default=0)


def _event_ids(items: list[dict[str, Any]]) -> list[str]:
    """Collect ordered event IDs from both legacy and canonical metadata."""

    result: list[str] = []
    for item in items:
        metadata = _metadata(item)
        candidates = metadata.get("event_ids")
        if not isinstance(candidates, list):
            candidates = []
        legacy_id = str(metadata.get("event_id") or "")
        for candidate in [*candidates, legacy_id]:
            value = str(candidate or "")
            if value and value not in result:
                result.append(value)
    return result


def _replace_violation_type(
    violations: list[dict[str, Any]],
    *,
    violation_type: str,
    replacement: dict[str, Any],
) -> list[dict[str, Any]]:
    """Replace every legacy record of one type with one canonical record."""

    result: list[dict[str, Any]] = []
    inserted = False
    for item in violations:
        if isinstance(item, dict) and item.get("violation_type") == violation_type:
            if not inserted:
                result.append(replacement)
                inserted = True
            continue
        result.append(item)
    if not inserted:
        result.append(replacement)
    return result


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
        """Atomically count a tab switch while storing one low violation."""

        session = await self._locked_session(session_id)
        if session.candidate_assessment_id != candidate_assessment_id:
            raise InvalidSessionAppendException(
                "candidate_assessment_id does not match the interview session"
            )

        current = list(session.violations or [])
        current_count = tab_switch_count(current)
        if (
            session.status not in {"INITIALIZING", "IN_PROGRESS"}
            or session.active_connection_id != connection_id
        ):
            return {
                "appended": False,
                "recorded": False,
                "tab_switch_count": current_count,
                "terminated": session.status == "TERMINATED",
                "status": session.status,
            }

        tab_violations = [
            item
            for item in current
            if isinstance(item, dict)
            and item.get("violation_type") == TAB_SWITCH_VIOLATION_TYPE
        ]
        event_ids = _event_ids(tab_violations)
        incoming_event_id = str(event_id)
        if incoming_event_id in event_ids:
            return {
                "appended": False,
                "recorded": False,
                "tab_switch_count": current_count,
                "terminated": session.status == "TERMINATED",
                "status": session.status,
            }

        occurrence_count = current_count + 1
        terminated = occurrence_count >= MAX_ALLOWED_TAB_SWITCHES
        first_violation = tab_violations[0] if tab_violations else {}
        first_metadata = _metadata(first_violation)
        first_occurred_at = str(
            first_metadata.get("first_occurred_at")
            or first_violation.get("timestamp")
            or occurred_at.isoformat()
        )
        event_ids.append(incoming_event_id)
        violation = {
            "violation_id": TAB_SWITCH_VIOLATION_ID,
            "turn_number": int(
                first_violation.get("turn_number")
                or max(1, len(session.transcript or []))
            ),
            "violation_type": TAB_SWITCH_VIOLATION_TYPE,
            "candidate_transcript": "",
            "severity": "low",
            "timestamp": first_occurred_at,
            "metadata": {
                "source": "browser_visibility",
                "affects_evaluation": True,
                "occurrence_count": occurrence_count,
                "tab_switch_count": occurrence_count,
                "event_ids": event_ids,
                "first_occurred_at": first_occurred_at,
                "last_occurred_at": occurred_at.isoformat(),
                "termination_threshold_count": MAX_ALLOWED_TAB_SWITCHES,
                "termination_triggered": terminated,
            },
        }
        violations = _replace_violation_type(
            current,
            violation_type=TAB_SWITCH_VIOLATION_TYPE,
            replacement=violation,
        )
        appended = not tab_violations
        session.violations = violations
        session.last_updated_at = func.now()
        if terminated:
            await self._terminate_session(
                session,
                candidate_assessment_id=candidate_assessment_id,
            )
        await self._session.flush()
        return {
            "appended": appended,
            "recorded": True,
            "tab_switch_count": occurrence_count,
            "terminated": terminated,
            "status": session.status,
        }

    async def record_proctoring_event(
        self,
        session_id: str | uuid.UUID,
        *,
        connection_id: str,
        candidate_assessment_id: uuid.UUID,
        event_id: uuid.UUID,
        event_type: str,
        condition_started_at: datetime,
        observed_duration_ms: int,
        sample_count: int,
        max_face_count: int,
        min_confidence: float | None,
        max_confidence: float | None,
        source: str,
        detector_version: str,
        model_name: str,
    ) -> dict[str, Any]:
        """Count a qualified face episode while storing one high violation."""

        session = await self._locked_session(session_id)
        if session.candidate_assessment_id != candidate_assessment_id:
            raise InvalidSessionAppendException(
                "candidate_assessment_id does not match the interview session"
            )

        policy = FACE_PROCTORING_POLICIES.get(event_type)
        if policy is None:
            raise InvalidSessionAppendException("unsupported proctoring event type")
        minimum_duration_ms, termination_duration_ms = policy
        if observed_duration_ms < minimum_duration_ms:
            raise InvalidSessionAppendException(
                f"{event_type} must persist for at least {minimum_duration_ms}ms"
            )
        if source == "camera_state" and event_type != "face_absent":
            raise InvalidSessionAppendException(
                "camera_state can only report a face_absent event"
            )
        if event_type == "face_absent" and max_face_count != 0:
            raise InvalidSessionAppendException(
                "face_absent cannot report a positive face count"
            )
        if event_type == "multiple_faces" and max_face_count < 2:
            raise InvalidSessionAppendException(
                "multiple_faces must report at least two faces"
            )
        if (
            min_confidence is not None
            and max_confidence is not None
            and min_confidence > max_confidence
        ):
            raise InvalidSessionAppendException(
                "min_confidence cannot exceed max_confidence"
            )

        if (
            session.status not in {"INITIALIZING", "IN_PROGRESS"}
            or session.active_connection_id != connection_id
        ):
            existing = [
                item
                for item in list(session.violations or [])
                if isinstance(item, dict) and item.get("violation_type") == event_type
            ]
            existing_metadata = _metadata(existing[0]) if existing else {}
            return {
                "appended": False,
                "recorded": False,
                "occurrence_count": int(
                    _positive_int(existing_metadata.get("occurrence_count"))
                    or len(existing)
                ),
                "terminated": session.status == "TERMINATED",
                "termination_reason": existing_metadata.get("termination_reason"),
                "status": session.status,
            }

        recorded_at = datetime.now(UTC)
        current = list(session.violations or [])
        existing = [
            item
            for item in current
            if isinstance(item, dict) and item.get("violation_type") == event_type
        ]
        existing_metadata = _metadata(existing[0]) if existing else {}
        episodes = self._face_episodes(existing)
        event_ids = _event_ids(existing)
        incoming_event_id = str(event_id)
        condition_started_at_value = condition_started_at.isoformat()

        episode = next(
            (
                item
                for item in episodes
                if item.get("condition_started_at") == condition_started_at_value
            ),
            None,
        )
        duplicate_event = incoming_event_id in event_ids
        previous_duration_ms = (
            int(episode.get("max_observed_duration_ms") or 0) if episode else 0
        )
        if duplicate_event and observed_duration_ms <= previous_duration_ms:
            return {
                "appended": False,
                "recorded": False,
                "occurrence_count": len(episodes) or len(existing),
                "terminated": False,
                "termination_reason": None,
                "status": session.status,
            }

        if incoming_event_id not in event_ids:
            event_ids.append(incoming_event_id)
        episode_payload = self._merge_face_episode(
            episode,
            event_id=incoming_event_id,
            condition_started_at=condition_started_at_value,
            recorded_at=recorded_at.isoformat(),
            observed_duration_ms=observed_duration_ms,
            sample_count=sample_count,
            max_face_count=max_face_count,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            source=source,
            detector_version=detector_version,
            model_name=model_name,
        )
        if episode is None:
            episodes.append(episode_payload)
        else:
            episodes[episodes.index(episode)] = episode_payload

        occurrence_count = len(episodes)
        max_observed_duration_ms = max(
            int(item.get("max_observed_duration_ms") or 0) for item in episodes
        )
        terminated = observed_duration_ms >= termination_duration_ms
        termination_reason = f"{event_type}_continuous_duration_exceeded"
        first_violation = existing[0] if existing else {}
        first_recorded_at = str(
            existing_metadata.get("first_recorded_at")
            or first_violation.get("timestamp")
            or recorded_at.isoformat()
        )
        violation = {
            "violation_id": f"proctoring:{event_type}",
            "turn_number": int(
                first_violation.get("turn_number")
                or max(1, len(session.transcript or []))
            ),
            "violation_type": event_type,
            "candidate_transcript": "",
            "severity": "high",
            "timestamp": first_recorded_at,
            "metadata": {
                "source": "browser_face_proctoring",
                "connection_id": connection_id,
                "occurrence_count": occurrence_count,
                "event_count": len(event_ids),
                "event_ids": event_ids,
                "episodes": episodes,
                "first_recorded_at": first_recorded_at,
                "recorded_at": recorded_at.isoformat(),
                "last_condition_started_at": condition_started_at_value,
                "max_observed_duration_ms": max_observed_duration_ms,
                "minimum_violation_duration_ms": minimum_duration_ms,
                "termination_duration_ms": termination_duration_ms,
                "termination_triggered": bool(
                    terminated or existing_metadata.get("termination_triggered")
                ),
                "termination_reason": (
                    termination_reason
                    if terminated
                    else existing_metadata.get("termination_reason")
                ),
                "affects_evaluation": True,
                "review_status": "server_qualified",
                "raw_frames_uploaded": False,
            },
        }
        session.violations = _replace_violation_type(
            current,
            violation_type=event_type,
            replacement=violation,
        )
        session.last_updated_at = func.now()
        if terminated:
            await self._terminate_session(
                session,
                candidate_assessment_id=candidate_assessment_id,
            )
        await self._session.flush()
        return {
            "appended": not existing,
            "recorded": True,
            "occurrence_count": occurrence_count,
            "terminated": terminated,
            "termination_reason": termination_reason if terminated else None,
            "status": session.status,
        }

    @staticmethod
    def _face_episodes(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Load canonical episodes or adapt legacy per-event violations."""

        episodes: list[dict[str, Any]] = []
        for violation in existing:
            metadata = _metadata(violation)
            raw_episodes = metadata.get("episodes")
            if isinstance(raw_episodes, list):
                for item in raw_episodes:
                    if isinstance(item, dict):
                        episodes.append(dict(item))
                if raw_episodes:
                    continue

            condition_started_at = str(
                metadata.get("condition_started_at") or violation.get("timestamp") or ""
            )
            if not condition_started_at:
                continue
            episodes.append(
                {
                    "condition_started_at": condition_started_at,
                    "first_recorded_at": str(
                        metadata.get("recorded_at")
                        or violation.get("timestamp")
                        or condition_started_at
                    ),
                    "last_recorded_at": str(
                        metadata.get("recorded_at")
                        or violation.get("timestamp")
                        or condition_started_at
                    ),
                    "max_observed_duration_ms": int(
                        metadata.get("observed_duration_ms") or 0
                    ),
                    "sample_count": int(metadata.get("sample_count") or 0),
                    "max_face_count": int(metadata.get("max_face_count") or 0),
                    "min_confidence": metadata.get("min_confidence"),
                    "max_confidence": metadata.get("max_confidence"),
                    "source": str(metadata.get("source") or "unknown"),
                    "detector_version": str(
                        metadata.get("detector_version") or "unknown"
                    ),
                    "model_name": str(metadata.get("model_name") or "unknown"),
                    "event_ids": _event_ids([violation]),
                }
            )
        return episodes

    @staticmethod
    def _merge_face_episode(
        existing: dict[str, Any] | None,
        *,
        event_id: str,
        condition_started_at: str,
        recorded_at: str,
        observed_duration_ms: int,
        sample_count: int,
        max_face_count: int,
        min_confidence: float | None,
        max_confidence: float | None,
        source: str,
        detector_version: str,
        model_name: str,
    ) -> dict[str, Any]:
        """Merge a warning/termination packet into its continuous episode."""

        current = dict(existing or {})
        raw_event_ids = current.get("event_ids")
        event_ids = (
            [str(item) for item in raw_event_ids if str(item)]
            if isinstance(raw_event_ids, list)
            else []
        )
        if event_id not in event_ids:
            event_ids.append(event_id)

        current_min = current.get("min_confidence")
        combined_min = min_confidence
        if isinstance(current_min, int | float) and not isinstance(current_min, bool):
            combined_min = (
                float(current_min)
                if combined_min is None
                else min(float(current_min), combined_min)
            )
        current_max = current.get("max_confidence")
        combined_max = max_confidence
        if isinstance(current_max, int | float) and not isinstance(current_max, bool):
            combined_max = (
                float(current_max)
                if combined_max is None
                else max(float(current_max), combined_max)
            )

        return {
            "condition_started_at": condition_started_at,
            "first_recorded_at": str(current.get("first_recorded_at") or recorded_at),
            "last_recorded_at": recorded_at,
            "max_observed_duration_ms": max(
                int(current.get("max_observed_duration_ms") or 0),
                observed_duration_ms,
            ),
            "sample_count": max(int(current.get("sample_count") or 0), sample_count),
            "max_face_count": max(
                int(current.get("max_face_count") or 0),
                max_face_count,
            ),
            "min_confidence": combined_min,
            "max_confidence": combined_max,
            "source": (
                "camera_state"
                if source == "camera_state" or current.get("source") == "camera_state"
                else source
            ),
            "detector_version": detector_version,
            "model_name": model_name,
            "event_ids": event_ids,
        }

    async def _terminate_session(
        self,
        session: InterviewSession,
        *,
        candidate_assessment_id: uuid.UUID,
    ) -> None:
        """Atomically terminate both durable session lifecycle records."""

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
