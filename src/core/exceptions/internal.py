"""Internal service-to-service exceptions."""

from src.core.exceptions.base import ForbiddenException


class UnauthorizedInternalCallerException(ForbiddenException):
    message = "Forbidden internal service caller."
    error_code = "INTERNAL_UNAUTHORIZED_CALLER"
