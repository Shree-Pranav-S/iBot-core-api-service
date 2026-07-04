import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
logger = logging.getLogger(__name__)
AfterCommitCallback = Callable[[], None]
_AFTER_COMMIT_CALLBACKS_KEY = "after_commit_callbacks"


def register_after_commit_callback(
    session: AsyncSession,
    callback: AfterCommitCallback,
) -> None:
    """Register a callback to run only after the request transaction commits."""
    callbacks = session.info.setdefault(_AFTER_COMMIT_CALLBACKS_KEY, [])
    callbacks.append(callback)


def run_after_commit_callbacks(session: AsyncSession) -> None:
    """Run and clear callbacks registered for the completed transaction."""
    callbacks = session.info.pop(_AFTER_COMMIT_CALLBACKS_KEY, [])
    for callback in callbacks:
        callback()


async def get_or_create_engine() -> AsyncEngine:
    """Return the shared async database engine, creating it on first use."""
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
    global _session_factory

    if _session_factory is not None:
        return _session_factory

    engine = await get_or_create_engine()
    _session_factory = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    logger.info("Session factory ready")
    return _session_factory


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Manage one async database session and transaction boundary."""
    session_factory = await get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            run_after_commit_callbacks(session)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped AsyncSession for FastAPI dependencies."""
    async with async_session_scope() as session:
        yield session


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
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed.")
        _engine = None
        _session_factory = None
