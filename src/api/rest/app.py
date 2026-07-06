"""FastAPI application factory for core-api-service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.middleware.error_handler import register_exception_handlers
from src.api.middleware.logging import request_logging_middleware
from src.api.rest.routes.assessments import router as assessments_router
from src.api.rest.routes.auth import router as auth_router
from src.api.rest.routes.candidates import router as candidates_router
from src.api.rest.routes.health import router as health_router
from src.api.rest.routes.internal_interview import router as internal_interview_router
from src.api.rest.routes.interview import router as interview_router
from src.api.rest.routes.notifications import router as notifications_router
from src.api.rest.routes.realtime import router as realtime_router
from src.config.settings import settings
from src.data.clients.postgres_client import close_db, init_db
from src.data.clients.redis_client import close_redis, init_redis
from src.observability.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and dispose process-wide database and Redis resources."""
    await init_db()
    await init_redis()
    try:
        yield
    finally:
        await close_redis()
        await close_db()


def create_app() -> FastAPI:
    """Create and configure the core API FastAPI application."""
    configure_logging()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    register_exception_handlers(app)
    app.middleware("http")(request_logging_middleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(assessments_router)
    app.include_router(candidates_router)
    app.include_router(internal_interview_router)
    app.include_router(interview_router)
    app.include_router(notifications_router)
    app.include_router(realtime_router)
    return app


app = create_app()
