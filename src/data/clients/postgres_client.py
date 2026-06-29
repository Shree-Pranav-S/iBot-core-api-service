import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import settings

_engine: AsyncEngine | None = None
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
