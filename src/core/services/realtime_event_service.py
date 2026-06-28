"""Publish recruiter-scoped dashboard events over Redis pub/sub."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from src.data.clients.redis_client import async_redis
from src.schemas.realtime import RecruiterEventType, RecruiterRealtimeEvent

logger = logging.getLogger(__name__)
RECRUITER_CHANNEL_PREFIX = "recruiter-dashboard"


def recruiter_event_channel(recruiter_id: uuid.UUID | str) -> str:
    """Return the private Redis channel for one recruiter."""

    return f"{RECRUITER_CHANNEL_PREFIX}:{recruiter_id}"


async def publish_recruiter_event(
    *,
    recruiter_id: uuid.UUID | str,
    event_type: RecruiterEventType,
    payload: dict[str, Any],
    redis_client: Redis | None = None,
) -> bool:
    """
    Publish a dashboard update after its database transaction commits.

    Pub/sub is deliberately best-effort: durable state remains in Postgres and
    the frontend revalidates its queries whenever the SSE stream reconnects.
    """

    event = RecruiterRealtimeEvent(
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        payload=payload,
    )
    try:
        client = redis_client or async_redis
        await client.publish(
            recruiter_event_channel(recruiter_id),
            event.model_dump_json(),
        )
        logger.info(
            "Published recruiter dashboard event",
            extra={
                "recruiter_id": str(recruiter_id),
                "event_id": str(event.event_id),
                "event_type": event_type.value,
            },
        )
        return True
    except Exception:
        logger.exception(
            "Could not publish recruiter dashboard event",
            extra={
                "recruiter_id": str(recruiter_id),
                "event_type": event_type.value,
            },
        )
        return False
