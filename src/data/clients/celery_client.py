"""Celery client configuration for core API background workloads."""

from celery import Celery
from kombu import Queue

from src.config.settings import settings

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
