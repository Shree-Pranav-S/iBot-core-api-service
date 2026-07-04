"""Common FastAPI dependencies for the REST layer."""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres_client import get_async_db
from src.data.clients.redis_client import get_async_redis


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async database session."""
    async for session in get_async_db():
        yield session


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    """Yield the request-scoped Redis client dependency."""
    async for client in get_async_redis():
        yield client


__all__ = ["AsyncSession", "Redis", "get_db_session", "get_redis_client"]
