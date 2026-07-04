"""Business logic for recruiter authentication."""

import hashlib
import json
import logging
import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from src.core.exceptions import (
    AuthenticationException,
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from src.core.services.event_log_service import try_record_event_in_background
from src.data.models.postgres.recruiter import Recruiter
from src.data.repositories.auth_repository import AuthRepository
from src.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RecruiterRegisterRequest,
    ResendOTPRequest,
    TokenRefreshRequest,
    TokenResponse,
    VerifyOTPRequest,
)
from src.schemas.event_log import EventLogCreate, EventName, EventSource
from src.utils.candidates import send_otp_email
from src.utils.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 60


class AuthService:
    """Service layer for recruiter registration and login use cases."""

    def __init__(self, repository: AuthRepository, redis: Redis | None = None) -> None:
        """Initialize the auth service with repository and optional Redis client."""
        self._repository = repository
        self._redis = redis

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

    # ── Forgot-password flow ──────────────────────────────────────────────────

    async def initiate_password_reset(self, payload: ForgotPasswordRequest) -> None:
        """Generate a 4-digit OTP, store in Redis, and send via email."""

        if self._redis is None:
            raise BadRequestException("Password reset service is unavailable.")

        normalized_email = payload.email.lower()
        recruiter = await self._repository.get_recruiter_by_email(normalized_email)
        if recruiter is None:
            raise NotFoundException("No account found with this email address.")

        if not recruiter.is_active:
            raise BadRequestException("This account is inactive.")

        otp = str(random.randint(1000, 9999))
        otp_data = json.dumps(
            {
                "otp": otp,
                "new_password_hash": hash_password(payload.new_password),
            }
        )
        redis_key = f"otp:{normalized_email}"
        await self._redis.set(redis_key, otp_data, ex=OTP_TTL_SECONDS)

        await send_otp_email(recipient_email=normalized_email, otp=otp)
        logger.info("Password reset OTP sent", extra={"email": normalized_email})

    async def verify_otp(self, payload: VerifyOTPRequest) -> None:
        """Verify the OTP and update the recruiter password."""

        if self._redis is None:
            raise BadRequestException("Password reset service is unavailable.")

        normalized_email = payload.email.lower()
        redis_key = f"otp:{normalized_email}"
        stored_data = await self._redis.get(redis_key)

        if stored_data is None:
            raise BadRequestException("OTP expired or not requested.")

        otp_record = json.loads(stored_data)
        if otp_record["otp"] != payload.otp:
            raise BadRequestException("Invalid OTP.")

        # Update password in database
        updated = await self._repository.update_password(
            email=normalized_email,
            hashed_password=otp_record["new_password_hash"],
        )
        if not updated:
            raise NotFoundException("Recruiter account not found.")

        # Clean up OTP from Redis
        await self._redis.delete(redis_key)

        # Revoke all existing sessions for security
        recruiter = await self._repository.get_recruiter_by_email(normalized_email)
        if recruiter:
            await self._repository.revoke_all_recruiter_tokens(recruiter.id)

            # Log the password reset event
            await try_record_event_in_background(
                EventLogCreate(
                    event_name=EventName.PASSWORD_RESETED,
                    source_service=EventSource.CORE_API,
                    correlation_id=str(recruiter.id),
                    recruiter_id=recruiter.id,
                    metadata={"email": normalized_email},
                )
            )

        logger.info("Password reset completed", extra={"email": normalized_email})

    async def resend_otp(self, payload: ResendOTPRequest) -> None:
        """Resend the OTP if the previous one has expired."""

        if self._redis is None:
            raise BadRequestException("Password reset service is unavailable.")

        normalized_email = payload.email.lower()
        redis_key = f"otp:{normalized_email}"

        # Check if an OTP is still active
        existing = await self._redis.get(redis_key)
        if existing is not None:
            raise BadRequestException(
                "Please wait for the current OTP to expire before requesting a new one."
            )

        recruiter = await self._repository.get_recruiter_by_email(normalized_email)
        if recruiter is None:
            raise NotFoundException("No account found with this email address.")

        if not recruiter.is_active:
            raise BadRequestException("This account is inactive.")

        otp = str(random.randint(1000, 9999))
        otp_data = json.dumps(
            {
                "otp": otp,
                "new_password_hash": hash_password(payload.new_password),
            }
        )
        await self._redis.set(redis_key, otp_data, ex=OTP_TTL_SECONDS)

        await send_otp_email(recipient_email=normalized_email, otp=otp)
        logger.info("Password reset OTP resent", extra={"email": normalized_email})

    async def get_recruiter(self, recruiter_id: uuid.UUID) -> Recruiter:
        """Return an active recruiter profile by identifier."""
        recruiter = await self._repository.get_recruiter_by_id(recruiter_id)
        if recruiter is None:
            raise NotFoundException("Recruiter not found.")
        return recruiter
