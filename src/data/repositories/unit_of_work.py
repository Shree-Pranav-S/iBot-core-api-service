"""Transaction boundary and repository wiring for core-api data access."""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres_client import (
    get_session_factory,
    run_after_commit_callbacks,
)
from src.data.repositories.assessment_context_repository import (
    AssessmentContextRepository,
)
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.auth_repository import AuthRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.candidate_session_repository import (
    CandidateSessionRepository,
)
from src.data.repositories.evaluation_repository import EvaluationRepository
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.data.repositories.interview_session_repository import (
    InterviewSessionRepository,
)
from src.data.repositories.notification_log_repository import (
    NotificationLogRepository,
)


class UnitOfWork:
    """Own one session and expose repositories sharing its transaction."""

    def __init__(self) -> None:
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        session_factory = await get_session_factory()
        self._session = session_factory()
        self.assessments = AssessmentRepository(self._session)
        self.auth = AuthRepository(self._session)
        self.candidate_assessments = CandidateAssessmentRepository(self._session)
        self.candidates = CandidateRepository(self._session)
        self.evaluations = EvaluationRepository(self._session)
        self.event_logs = EventLogsRepository(self._session)
        self.notifications = NotificationLogRepository(self._session)
        self.interview_sessions = InterviewSessionRepository(self._session)
        self.candidate_sessions = CandidateSessionRepository(self._session)
        self.assessment_context = AssessmentContextRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                await session.commit()
                run_after_commit_callbacks(session)
            else:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        """Commit current work and dispatch its registered callbacks."""
        session = self._require_session()
        await session.commit()
        run_after_commit_callbacks(session)

    async def rollback(self) -> None:
        """Roll back current work."""
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before use.")
        return self._session
