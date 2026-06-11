"""Async Redis client for core-api."""

import logging
from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from src.config.settings import settings

logger = logging.getLogger(__name__)

async_redis: Redis = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
    health_check_interval=settings.REDIS_HEALTHCHECK_INTERVAL,
    retry_on_timeout=True,
)


async def get_async_redis() -> AsyncGenerator[Redis, None]:
    """Yield the shared Redis client."""
    yield async_redis


async def init_redis() -> None:
    """Fail fast if Redis is unreachable."""
    try:
        await async_redis.ping()
        logger.info("Redis connection established.")
    except Exception as exc:
        logger.exception("Redis connection failed: %s", exc)
        raise


async def ping_redis() -> bool:
    """Lightweight health check used by the health endpoint."""

    try:
        return bool(await async_redis.ping())
    except Exception:
        logger.exception("Redis health check failed.")
        return False


async def close_redis() -> None:
    """Close the Redis connection pool during shutdown."""
    await async_redis.aclose()
    logger.info("Redis client closed.")
