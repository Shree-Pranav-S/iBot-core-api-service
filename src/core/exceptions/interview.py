"""Interview session and invitation exceptions."""

from src.core.exceptions.base import (
    AuthenticationException,
    BadRequestException,
    ForbiddenException,
    InternalServerException,
    NotFoundException,
)


class InvalidInvitationException(AuthenticationException):
    message = "Invalid interview invitation."
    error_code = "INTERVIEW_INVALID_INVITATION"


class InvalidSessionTokenException(AuthenticationException):
    message = "Invalid interview session token."
    error_code = "INTERVIEW_INVALID_SESSION_TOKEN"


class SessionExpiredException(AuthenticationException):
    message = "This interview session has expired."
    error_code = "INTERVIEW_SESSION_EXPIRED"


class SessionClosedException(ForbiddenException):
    message = "This interview session is already closed."
    error_code = "INTERVIEW_SESSION_CLOSED"


class ReconnectTimeoutException(ForbiddenException):
    message = "The five-minute reconnection window has expired."
    error_code = "INTERVIEW_RECONNECT_TIMEOUT"


class InvitationNotFoundException(NotFoundException):
    message = "Candidate invitation token not found."
    error_code = "INTERVIEW_INVITATION_NOT_FOUND"


class InterviewSessionNotFoundException(NotFoundException):
    message = "Interview session not found."
    error_code = "INTERVIEW_SESSION_NOT_FOUND"


class InterviewConfigurationException(InternalServerException):
    message = "Interview configuration is invalid."
    error_code = "INTERVIEW_CONFIGURATION_ERROR"


class SessionBootstrapFailedException(InternalServerException):
    message = "Failed to bootstrap interview session."
    error_code = "INTERVIEW_SESSION_BOOTSTRAP_FAILED"


class InterviewConnectionFailedException(InternalServerException):
    message = "Interview connection authorization failed."
    error_code = "INTERVIEW_CONNECTION_FAILED"


class SessionTokenExpiryMissingException(InternalServerException):
    message = "Session token expiry is missing."
    error_code = "INTERVIEW_SESSION_TOKEN_EXPIRY_MISSING"


class InterviewContextNotFoundException(NotFoundException):
    message = "Candidate assessment context not found."
    error_code = "INTERVIEW_CONTEXT_NOT_FOUND"


class InvalidSessionAppendException(BadRequestException):
    message = "Session append requires a valid identifier."
    error_code = "INTERVIEW_INVALID_SESSION_APPEND"
