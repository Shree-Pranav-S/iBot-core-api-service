"""Authenticated recruiter Server-Sent Events stream."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from src.api.rest.dependencies import get_redis_client, require_recruiter_id
from src.core.services.realtime_event_service import recruiter_event_channel

router = APIRouter(prefix="/sse", tags=["realtime"])
KEEPALIVE_INTERVAL_SECONDS = 15.0


@router.get(
    "/recruiter-events",
    response_class=StreamingResponse,
    summary="Stream live dashboard updates for the authenticated recruiter",
)
async def stream_recruiter_events(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    redis_client: Redis = Depends(get_redis_client),
) -> StreamingResponse:
    """Subscribe only to the Redis channel belonging to the authenticated user."""

    async def event_stream() -> AsyncGenerator[str, None]:
        """Yield recruiter dashboard events and keep-alives as SSE frames."""
        pubsub = redis_client.pubsub()
        channel = recruiter_event_channel(recruiter_id)
        await pubsub.subscribe(channel)
        last_keepalive = time.monotonic()
        try:
            # Let EventSource reconnect quickly after a transient interruption.
            yield "retry: 3000\n\n"
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message.get("type") == "message":
                    yield f"event: recruiter-update\ndata: {message['data']}\n\n"
                    last_keepalive = time.monotonic()
                    continue

                if time.monotonic() - last_keepalive >= KEEPALIVE_INTERVAL_SECONDS:
                    yield ": keep-alive\n\n"
                    last_keepalive = time.monotonic()
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
