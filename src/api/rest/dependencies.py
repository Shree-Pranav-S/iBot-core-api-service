"""Common FastAPI dependencies for the REST layer."""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from src.data.clients.redis_client import get_async_redis
from src.data.repositories.unit_of_work import UnitOfWork


async def get_unit_of_work() -> AsyncGenerator[UnitOfWork, None]:
    """Yield a request-scoped transaction and its repositories."""
    async with UnitOfWork() as unit_of_work:
        yield unit_of_work


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    async for client in get_async_redis():
        yield client


__all__ = ["Redis", "UnitOfWork", "get_redis_client", "get_unit_of_work"]
