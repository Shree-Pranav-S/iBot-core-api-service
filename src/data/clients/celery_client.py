"""Celery client configuration for core API background workloads."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery import Celery
from kombu import Queue

from src.config.settings import settings

T = TypeVar("T")
_celery_loop: asyncio.AbstractEventLoop | None = None


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine without closing the underlying event loop."""
    global _celery_loop
    if _celery_loop is None:
        _celery_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_celery_loop)
    return _celery_loop.run_until_complete(coro)


celery_app = Celery(
    "core_api_service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "src.handlers.celery_tasks.assessment_tasks",
        "src.handlers.celery_tasks.notification_tasks",
    ],
)

celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    task_default_queue="core.default",
    task_ignore_result=True,
    task_publish_retry=True,
    task_publish_retry_policy={
        "interval_max": 2.0,
        "interval_start": 0.2,
        "interval_step": 0.5,
        "max_retries": 3,
    },
    task_queues=(
        Queue("core.default"),
        Queue("core.assessment"),
        Queue("core.email"),
    ),
    task_routes={
        "core.process_assessment": {"queue": "core.assessment"},
        "core.send_invitation_email": {"queue": "core.email"},
    },
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
    worker_prefetch_multiplier=1,
)
