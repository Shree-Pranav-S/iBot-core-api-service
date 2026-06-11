"""
Auth schemas.

Covers recruiter self-registration, login, and JWT token responses.
"""

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from src.schemas.base import AppBaseModel, ORMBaseModel

# ── Request schemas ───────────────────────────────────────────────────────────


class RecruiterRegisterRequest(AppBaseModel):
    """POST /auth/register request body."""

    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    company_name: str = Field(..., min_length=2, max_length=120)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v


class LoginRequest(AppBaseModel):
    """POST /auth/login request body."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenRefreshRequest(AppBaseModel):
    """POST /auth/refresh request body."""

    refresh_token: str


class LogoutRequest(AppBaseModel):
    """POST /auth/logout request body."""

    refresh_token: str


# ── Response schemas ──────────────────────────────────────────────────────────


class RecruiterResponse(ORMBaseModel):
    """Recruiter representation returned after register or profile fetch."""

    id: uuid.UUID
    full_name: str
    email: str
    company_name: str
    is_active: bool
    created_at: datetime


class TokenResponse(AppBaseModel):
    """JWT token payload returned on successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenPayload(AppBaseModel):
    """Decoded JWT payload — used internally by auth dependencies."""

    sub: uuid.UUID  # recruiter id
    email: str
    role: str = "recruiter"
    exp: int  # expiry unix timestamp
