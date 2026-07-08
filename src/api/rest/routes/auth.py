"""Recruiter authentication endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Request, status

from src.api.rest.dependencies import get_auth_service, require_recruiter_id
from src.core.exceptions import RecruiterNotFoundException
from src.core.services.auth_service import AuthService
from src.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RecruiterRegisterRequest,
    RecruiterResponse,
    ResendOTPRequest,
    TokenRefreshRequest,
    TokenResponse,
    VerifyOTPRequest,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=APIResponse[RecruiterResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Register recruiter",
    description="Create a recruiter account using name, email, company, and password.",
)
async def register_recruiter(
    payload: RecruiterRegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[RecruiterResponse]:
    """Register a recruiter and return the created account profile."""

    recruiter = await service.register_recruiter(payload)
    return APIResponse(
        message="Recruiter registered successfully.",
        data=RecruiterResponse.model_validate(recruiter),
    )


@router.post(
    "/login",
    response_model=APIResponse[TokenResponse],
    summary="Login recruiter",
    description="Authenticate a recruiter, start a session, and return token pair.",
)
async def login_recruiter(
    payload: LoginRequest,
    request: Request,
    user_agent: str | None = Header(default=None),
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[TokenResponse]:
    """Authenticate a recruiter and return an access token and refresh token."""

    ip_address = request.client.host if request.client else None
    token = await service.login(
        payload=payload,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return APIResponse(message="Login successful.", data=token)


@router.post(
    "/refresh",
    response_model=APIResponse[TokenResponse],
    summary="Refresh access token",
    description="Exchange a refresh token for a new access token and refresh token pair.",
)
async def refresh_token(
    payload: TokenRefreshRequest,
    request: Request,
    user_agent: str | None = Header(default=None),
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[TokenResponse]:
    """Rotate the refresh token and return a new token pair."""

    ip_address = request.client.host if request.client else None
    token = await service.refresh_token(
        payload=payload,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return APIResponse(message="Token refreshed successfully.", data=token)


@router.get(
    "/me",
    response_model=APIResponse[RecruiterResponse],
    summary="Get current recruiter profile",
    description=(
        "Returns the authenticated recruiter's profile. "
        "Relies on the X-User-Id header injected by the gateway after cookie validation. "
        "This endpoint has zero cookie handling code — the gateway is the sole auth layer."
    ),
)
async def get_current_recruiter(
    recruiter_id: uuid.UUID = Depends(require_recruiter_id),
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[RecruiterResponse]:
    """Return the recruiter profile for the authenticated session."""
    recruiter = await service.get_recruiter(recruiter_id)
    if recruiter is None:
        raise RecruiterNotFoundException()

    return APIResponse(
        message="Profile retrieved successfully.",
        data=RecruiterResponse.model_validate(recruiter),
    )


@router.post(
    "/logout",
    response_model=APIResponse[None],
    summary="Logout recruiter",
    description="Revoke the refresh token session. The gateway clears cookies; core-api revokes the DB record.",
)
async def logout_recruiter(
    payload: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[None]:
    """Revoke the recruiter session."""

    await service.logout(payload)
    return APIResponse(message="Logged out successfully.", data=None)


# ── Forgot-password endpoints ────────────────────────────────────────────────


@router.post(
    "/forgot-password",
    response_model=APIResponse[None],
    summary="Initiate password reset",
    description="Generate a 4-digit OTP and send it to the recruiter's email.",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[None]:
    """Send a password-reset OTP to the recruiter's email."""

    await service.initiate_password_reset(payload)
    return APIResponse(message="OTP sent to your email.", data=None)


@router.post(
    "/verify-otp",
    response_model=APIResponse[None],
    summary="Verify OTP and reset password",
    description="Verify the 4-digit OTP and update the recruiter's password.",
)
async def verify_otp(
    payload: VerifyOTPRequest,
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[None]:
    """Verify the OTP and update the password."""

    await service.verify_otp(payload)
    return APIResponse(message="Password updated successfully.", data=None)


@router.post(
    "/resend-otp",
    response_model=APIResponse[None],
    summary="Resend password reset OTP",
    description="Resend the 4-digit OTP if the previous one has expired.",
)
async def resend_otp(
    payload: ResendOTPRequest,
    service: AuthService = Depends(get_auth_service),
) -> APIResponse[None]:
    """Resend the password-reset OTP."""

    await service.resend_otp(payload)
    return APIResponse(message="OTP resent to your email.", data=None)
