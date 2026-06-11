import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import settings

_engine: AsyncEngine | None = None
logger = logging.getLogger(__name__)


async def get_or_create_engine() -> AsyncEngine:
    global _engine

    if _engine is None:
        logger.info("Creating async engine")
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=10,
            max_overflow=10,
            pool_timeout=10,
            pool_recycle=3600,
            pool_pre_ping=True,
            connect_args={
                "timeout": 180,
                "command_timeout": 2400,
                "server_settings": {"statement_timeout": "2400000"},
            },
        )

    return _engine


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Creates an async session factory."""
    engine = await get_or_create_engine()
    SessionLocal = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    logger.info("Session factory ready")
    return SessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields an async database session."""
    logger.info("Entering get_db_session")
    SessionLocal = await get_session_factory()
    async with SessionLocal() as session:
        try:
            logger.info("Yielding DB session")
            yield session
            await session.commit()
            logger.info("DB session committed")
        except Exception:
            logger.exception("DB session rollback due to exception")
            await session.rollback()
            raise
        finally:
            logger.info("Exiting get_db_session")


async def init_db() -> None:
    """Fail fast if Postgres is unreachable."""

    engine = await get_or_create_engine()
    try:
        async with engine.connect():
            logger.info("Database connection established.")
    except Exception as exc:
        logger.exception("Database connection failed: %s", exc)
        raise


async def ping_db() -> bool:
    """Lightweight health check used by the health endpoint."""

    engine = await get_or_create_engine()
    try:
        async with engine.connect():
            return True
    except Exception:
        logger.exception("Database health check failed.")
        return False


async def close_db() -> None:
    """Dispose the shared engine during shutdown."""

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed.")
