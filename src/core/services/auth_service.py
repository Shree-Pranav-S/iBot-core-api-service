"""Business logic for recruiter authentication."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from src.core.exceptions import AuthenticationException, ConflictException
from src.data.models.postgres.recruiter import Recruiter
from src.data.repositories.auth_repository import AuthRepository
from src.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RecruiterRegisterRequest,
    TokenRefreshRequest,
    TokenResponse,
)
from src.utils.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)


class AuthService:
    """Service layer for recruiter registration and login use cases."""

    def __init__(self, repository: AuthRepository) -> None:
        self._repository = repository

    async def register_recruiter(
        self,
        payload: RecruiterRegisterRequest,
    ) -> Recruiter:
        """Register a new recruiter after enforcing email uniqueness."""

        normalized_email = payload.email.lower()
        existing_recruiter = await self._repository.get_recruiter_by_email(
            normalized_email,
        )
        if existing_recruiter is not None:
            logger.info("Duplicate recruiter registration attempted")
            raise ConflictException("A recruiter with this email already exists.")

        return await self._repository.create_recruiter(
            full_name=payload.full_name,
            email=normalized_email,
            hashed_password=hash_password(payload.password),
            company_name=payload.company_name,
        )

    async def login(
        self,
        payload: LoginRequest,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenResponse:
        """Authenticate a recruiter, invalidate existing tokens, and return token pair."""

        normalized_email = payload.email.lower()
        recruiter = await self._repository.get_recruiter_by_email(normalized_email)
        if recruiter is None or not verify_password(
            payload.password,
            recruiter.hashed_password,
        ):
            logger.info("Recruiter login failed")
            raise AuthenticationException("Invalid email or password.")

        if not recruiter.is_active:
            logger.info(
                "Inactive recruiter login denied",
                extra={"recruiter_id": str(recruiter.id)},
            )
            raise AuthenticationException("Recruiter account is inactive.")

        # Revoke existing sessions to prevent multiple logins if configured (superseding sessions)
        await self._repository.revoke_all_recruiter_tokens(recruiter.id)

        # Issue 15-minute short-lived access token
        access_token = create_access_token(
            recruiter_id=recruiter.id,
            email=recruiter.email,
            expires_delta=timedelta(minutes=15),
        )

        # Generate new refresh token
        raw_refresh_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()

        # Save to recruiter_tokens with 7 days expiry
        await self._repository.create_refresh_token(
            recruiter_id=recruiter.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            user_agent=user_agent,
            ip_address=ip_address,
        )

        logger.info(
            "Recruiter login succeeded", extra={"recruiter_id": str(recruiter.id)}
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=15 * 60,
        )

    async def refresh_token(
        self,
        payload: TokenRefreshRequest,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenResponse:
        """Validate refresh token, perform rotation, and return a new token pair."""

        token_hash = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
        stored_token = await self._repository.get_refresh_token_by_hash(token_hash)

        if stored_token is None or stored_token.is_revoked:
            logger.warning("Revoked or invalid refresh token attempt")
            raise AuthenticationException("Invalid or revoked refresh token.")

        db_expires = stored_token.expires_at
        if db_expires.tzinfo is None:
            db_expires = db_expires.replace(tzinfo=UTC)

        if db_expires < datetime.now(UTC):
            logger.info("Expired refresh token attempt")
            raise AuthenticationException("Expired refresh token.")

        # Load recruiter
        recruiter = await self._repository.get_recruiter_by_id(
            stored_token.recruiter_id
        )
        if recruiter is None or not recruiter.is_active:
            raise AuthenticationException("Recruiter account is inactive or not found.")

        # Invalidate old refresh token (token rotation)
        await self._repository.revoke_refresh_token(token_hash)

        # Generate new token pair
        new_access_token = create_access_token(
            recruiter_id=recruiter.id,
            email=recruiter.email,
            expires_delta=timedelta(minutes=15),
        )
        new_raw_refresh_token = secrets.token_urlsafe(32)
        new_token_hash = hashlib.sha256(
            new_raw_refresh_token.encode("utf-8")
        ).hexdigest()

        # Save new refresh token hash to db
        await self._repository.create_refresh_token(
            recruiter_id=recruiter.id,
            token_hash=new_token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            user_agent=user_agent,
            ip_address=ip_address,
        )

        logger.info(
            "Token rotated successfully", extra={"recruiter_id": str(recruiter.id)}
        )
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_raw_refresh_token,
            expires_in=15 * 60,
        )

    async def logout(self, payload: LogoutRequest) -> None:
        """Revoke the recruiter refresh token session."""

        token_hash = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
        revoked = await self._repository.revoke_refresh_token(token_hash)
        if revoked:
            logger.info("Recruiter logged out successfully")
        else:
            logger.warning("Logout attempted with invalid token hash")
