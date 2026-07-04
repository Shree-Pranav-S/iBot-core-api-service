"""Database operations for durable event logs."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.event_log import EventLog
from src.schemas.event_log import EventLogCreate


class EventLogsRepository:
    """Persist immutable events and support retention-driven soft deletion."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the active database session."""
        self._session = session

    async def create(self, event: EventLogCreate) -> EventLog:
        """Create and flush one durable event log record."""
        record = EventLog(
            event_name=event.event_name.value,
            source_service=event.source_service.value,
            correlation_id=event.correlation_id,
            candidate_assessment_id=event.candidate_assessment_id,
            recruiter_id=event.recruiter_id,
            metadata_json=event.metadata,
            error_message=event.error_message,
            duration_ms=event.duration_ms,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def create_many(
        self,
        events: Sequence[EventLogCreate],
    ) -> list[EventLog]:
        """Create and flush multiple durable event log records."""
        records = [
            EventLog(
                event_name=event.event_name.value,
                source_service=event.source_service.value,
                correlation_id=event.correlation_id,
                candidate_assessment_id=event.candidate_assessment_id,
                recruiter_id=event.recruiter_id,
                metadata_json=event.metadata,
                error_message=event.error_message,
                duration_ms=event.duration_ms,
            )
            for event in events
        ]
        if records:
            self._session.add_all(records)
            await self._session.flush()
        return records
