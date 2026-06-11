"""Recruiter authentication endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db_session
from src.core.services.auth_service import AuthService
from src.data.repositories.auth_repository import AuthRepository
from src.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RecruiterRegisterRequest,
    RecruiterResponse,
    TokenRefreshRequest,
    TokenResponse,
)
from src.schemas.common import APIResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuthService:
    """Build the auth service from request-scoped dependencies."""

    return AuthService(AuthRepository(session))


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
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[RecruiterResponse]:
    """Return the recruiter profile for the authenticated session."""

    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing identity header — ensure request passes through the gateway.",
        )

    try:
        recruiter_id = uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-Id header format.",
        )

    service = AuthService(AuthRepository(session))
    recruiter = await service._repository.get_recruiter_by_id(recruiter_id)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recruiter not found.",
        )

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
