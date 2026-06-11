"""Common FastAPI dependencies for the REST layer."""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres_client import get_db_session as get_postgres_session
from src.data.clients.redis_client import get_async_redis


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_postgres_session():
        yield session


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    async for client in get_async_redis():
        yield client


__all__ = ["AsyncSession", "Redis", "get_db_session", "get_redis_client"]
