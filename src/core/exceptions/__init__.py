"""Custom exceptions used across core-api-service."""

from src.core.exceptions.base import (
    AppException,
    AuthenticationException,
    BadGatewayException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    InternalServerException,
    NotFoundException,
)

__all__ = [
    "AppException",
    "AuthenticationException",
    "BadRequestException",
    "ConflictException",
    "ForbiddenException",
    "InternalServerException",
    "BadGatewayException",
    "NotFoundException",
]
