"""Security and cryptography utilities."""

import uuid
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from src.config.settings import settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""

    return password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash."""

    return bool(password_context.verify(plain_password, hashed_password))


def create_access_token(
    *, recruiter_id: uuid.UUID, email: str, expires_delta: timedelta | None = None
) -> str:
    """Create a JWT access token understood by the gateway."""

    now = datetime.now(UTC)
    delta = expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = now + delta
    claims = {
        "sub": str(recruiter_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(
        claims,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
