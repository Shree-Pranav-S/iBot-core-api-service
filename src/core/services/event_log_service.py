"""Business service for durable event recording."""

import logging

from src.data.clients.postgres_client import async_session_scope
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.schemas.event_log import EventLogCreate

logger = logging.getLogger(__name__)


class EventLogService:
    """Service wrapper for writing individual durable event records."""

    def __init__(self, repository: EventLogsRepository) -> None:
        """Initialize the service with its event log repository."""
        self._repository = repository

    async def record(self, event: EventLogCreate) -> None:
        """Persist one event log record."""
        await self._repository.create(event)


async def try_record_event_in_background(event: EventLogCreate) -> None:
    """Best-effort logging that never changes the primary operation outcome."""

    try:
        async with async_session_scope() as session:
            await EventLogService(EventLogsRepository(session)).record(event)
    except Exception:
        logger.exception(
            "Failed to persist event log",
            extra={
                "event_name": event.event_name.value,
                "correlation_id": event.correlation_id,
            },
        )
