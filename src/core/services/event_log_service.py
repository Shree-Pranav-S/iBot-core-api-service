"""Business service for durable event recording."""

import logging
from collections.abc import Sequence

from src.data.repositories.event_logs_repository import EventLogsRepository
from src.data.repositories.unit_of_work import UnitOfWork
from src.schemas.event_log import EventLogCreate

logger = logging.getLogger(__name__)


class EventLogService:
    def __init__(self, repository: EventLogsRepository) -> None:
        self._repository = repository

    async def record(self, event: EventLogCreate) -> None:
        await self._repository.create(event)

    async def record_many(self, events: Sequence[EventLogCreate]) -> None:
        await self._repository.create_many(events)


async def record_event_in_background(event: EventLogCreate) -> None:
    """Write an event in its own transaction for workers and callbacks."""

    async with UnitOfWork() as unit_of_work:
        await EventLogService(unit_of_work.event_logs).record(event)


async def try_record_event_in_background(event: EventLogCreate) -> None:
    """Best-effort logging that never changes the primary operation outcome."""

    try:
        await record_event_in_background(event)
    except Exception:
        logger.exception(
            "Failed to persist event log",
            extra={
                "event_name": event.event_name.value,
                "correlation_id": event.correlation_id,
            },
        )
