"""Repository for recruiter authentication data access."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.recruiter import Recruiter
from src.data.models.postgres.recruiter_token import RecruiterToken

logger = logging.getLogger(__name__)


class AuthRepository:
    """Data access layer for recruiter registration, login, and token management."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recruiter_by_email(self, email: str) -> Recruiter | None:
        """Return a recruiter by normalized email address."""

        statement = select(Recruiter).where(Recruiter.email == email)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_recruiter_by_id(self, recruiter_id: uuid.UUID) -> Recruiter | None:
        """Return a recruiter by UUID."""

        statement = select(Recruiter).where(Recruiter.id == recruiter_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create_recruiter(
        self,
        *,
        full_name: str,
        email: str,
        hashed_password: str,
        company_name: str,
    ) -> Recruiter:
        """Create and flush a recruiter account."""

        recruiter = Recruiter(
            full_name=full_name,
            email=email,
            hashed_password=hashed_password,
            company_name=company_name,
            is_active=True,
        )
        self._session.add(recruiter)
        await self._session.flush()
        await self._session.refresh(recruiter)
        logger.info("Recruiter created", extra={"recruiter_id": str(recruiter.id)})
        return recruiter

    async def create_refresh_token(
        self,
        *,
        recruiter_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RecruiterToken:
        """Create and store a new refresh token."""

        token = RecruiterToken(
            recruiter_id=recruiter_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            is_revoked=False,
        )
        self._session.add(token)
        await self._session.flush()
        await self._session.refresh(token)
        logger.info("Refresh token stored", extra={"recruiter_id": str(recruiter_id)})
        return token

    async def get_refresh_token_by_hash(self, token_hash: str) -> RecruiterToken | None:
        """Fetch a refresh token by its hash."""

        statement = select(RecruiterToken).where(
            RecruiterToken.token_hash == token_hash
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token_hash: str) -> bool:
        """Revoke a refresh token by setting is_revoked = True."""

        statement = (
            update(RecruiterToken)
            .where(RecruiterToken.token_hash == token_hash)
            .values(is_revoked=True)
        )
        result = await self._session.execute(statement)
        return result.rowcount > 0

    async def revoke_all_recruiter_tokens(self, recruiter_id: uuid.UUID) -> None:
        """Revoke all tokens for a recruiter (e.g. on new login or security reset)."""

        statement = (
            update(RecruiterToken)
            .where(RecruiterToken.recruiter_id == recruiter_id)
            .where(RecruiterToken.is_revoked == False)
            .values(is_revoked=True)
        )
        await self._session.execute(statement)
        logger.info(
            "All refresh tokens revoked", extra={"recruiter_id": str(recruiter_id)}
        )
