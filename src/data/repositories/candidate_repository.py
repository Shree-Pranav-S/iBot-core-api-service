"""Repository for candidate data access."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.candidate import Candidate

logger = logging.getLogger(__name__)


class CandidateRepository:
    """Data access layer for creating and retrieving candidate records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> Candidate | None:
        """Return a Candidate by email address (case-insensitive)."""
        statement = select(Candidate).where(Candidate.email == email.lower().strip())
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(self, candidate_id: uuid.UUID) -> Candidate | None:
        """Return a Candidate by UUID."""
        statement = select(Candidate).where(Candidate.id == candidate_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create_candidate(
        self,
        *,
        full_name: str,
        email: str,
        created_by: uuid.UUID,
    ) -> Candidate:
        """Create and flush a new candidate record."""
        candidate = Candidate(
            full_name=full_name,
            email=email.lower().strip(),
            created_by=created_by,
        )
        self._session.add(candidate)
        await self._session.flush()
        await self._session.refresh(candidate)
        logger.info("Candidate created", extra={"candidate_id": str(candidate.id)})
        return candidate
