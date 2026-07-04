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
        """Validate registration password complexity."""
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


class ForgotPasswordRequest(AppBaseModel):
    """POST /auth/forgot-password request body."""

    email: EmailStr
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Validate reset password complexity."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v


class VerifyOTPRequest(AppBaseModel):
    """POST /auth/verify-otp request body."""

    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=4, pattern=r"^\d{4}$")


class ResendOTPRequest(AppBaseModel):
    """POST /auth/resend-otp request body."""

    email: EmailStr
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Validate replacement password complexity for OTP resend."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v


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
