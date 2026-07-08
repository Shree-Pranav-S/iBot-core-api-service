"""Common FastAPI dependencies for the REST layer."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    InvalidUserIdHeaderException,
    MissingIdentityHeaderException,
    UnauthorizedInternalCallerException,
)
from src.core.services.assessment_service import AssessmentService
from src.core.services.auth_service import AuthService
from src.core.services.candidate_service import CandidateService
from src.core.services.evaluation_service import EvaluationService
from src.core.services.interview_session_service import InterviewSessionService
from src.core.services.notification_service import NotificationService
from src.data.clients.postgres_client import get_async_db
from src.data.clients.redis_client import get_async_redis
from src.data.repositories.assessment_context_repository import (
    AssessmentContextRepository,
)
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.auth_repository import AuthRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)
from src.data.repositories.notification_log_repository import NotificationLogRepository

INTERVIEW_ENGINE_SERVICE = "interview-engine"


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async database session."""
    async for session in get_async_db():
        yield session


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    """Yield the request-scoped Redis client dependency."""
    async for client in get_async_redis():
        yield client


async def require_interview_engine_service(
    x_internal_service: str = Header(..., alias="X-Internal-Service"),
) -> None:
    """Allow only interview-engine-service to call interview persistence APIs."""
    if x_internal_service != INTERVIEW_ENGINE_SERVICE:
        raise UnauthorizedInternalCallerException()


def require_recruiter_id(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> uuid.UUID:
    """Parse and validate the recruiter identity header from the gateway."""
    if not x_user_id:
        raise MissingIdentityHeaderException(
            "Missing identity header - ensure request passes through the gateway."
        )
    try:
        return uuid.UUID(x_user_id)
    except ValueError as exc:
        raise InvalidUserIdHeaderException() from exc


def get_auth_service(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
) -> AuthService:
    """Build the auth service from request-scoped dependencies."""
    return AuthService(AuthRepository(db), redis=redis)


def get_assessment_service(
    db: AsyncSession = Depends(get_db_session),
) -> AssessmentService:
    """Build the assessment service from request-scoped dependencies."""
    return AssessmentService(AssessmentRepository(db))


def get_candidate_service(
    db: AsyncSession = Depends(get_db_session),
) -> CandidateService:
    """Build the candidate service from request-scoped dependencies."""
    return CandidateService(
        candidate_repo=CandidateRepository(db),
        ca_repo=CandidateAssessmentRepository(db),
        assessment_repo=AssessmentRepository(db),
        event_logs_repo=EventLogsRepository(db),
    )


def get_evaluation_service(
    db: AsyncSession = Depends(get_db_session),
) -> EvaluationService:
    """Build the evaluation service from request-scoped dependencies."""
    return EvaluationService(
        candidate_assessment_repo=CandidateAssessmentRepository(db),
        evaluation_repo=EvaluationRepository(db),
        session_repo=InterviewSessionRepository(db),
    )


def get_notification_service(
    db: AsyncSession = Depends(get_db_session),
) -> NotificationService:
    """Build the notification service from request-scoped dependencies."""
    return NotificationService(NotificationLogRepository(db))


def get_interview_session_service() -> InterviewSessionService:
    """Build the interview session service for internal interview APIs."""
    return InterviewSessionService()


def get_event_logs_repository(
    db: AsyncSession = Depends(get_db_session),
) -> EventLogsRepository:
    """Build the event logs repository from a request-scoped session."""
    return EventLogsRepository(db)


def get_assessment_context_repository(
    db: AsyncSession = Depends(get_db_session),
) -> AssessmentContextRepository:
    """Build the assessment context repository from a request-scoped session."""
    return AssessmentContextRepository(db)


def get_interview_session_repository(
    db: AsyncSession = Depends(get_db_session),
) -> InterviewSessionRepository:
    """Build the interview session repository from a request-scoped session."""
    return InterviewSessionRepository(db)


def get_evaluation_repository(
    db: AsyncSession = Depends(get_db_session),
) -> EvaluationRepository:
    """Build the evaluation repository from a request-scoped session."""
    return EvaluationRepository(db)


def get_candidate_assessment_repository(
    db: AsyncSession = Depends(get_db_session),
) -> CandidateAssessmentRepository:
    """Build the candidate assessment repository from a request-scoped session."""
    return CandidateAssessmentRepository(db)


__all__ = [
    "INTERVIEW_ENGINE_SERVICE",
    "AsyncSession",
    "Redis",
    "get_assessment_context_repository",
    "get_assessment_service",
    "get_auth_service",
    "get_candidate_assessment_repository",
    "get_candidate_service",
    "get_db_session",
    "get_evaluation_repository",
    "get_evaluation_service",
    "get_event_logs_repository",
    "get_interview_session_repository",
    "get_interview_session_service",
    "get_notification_service",
    "get_redis_client",
    "require_interview_engine_service",
    "require_recruiter_id",
]
