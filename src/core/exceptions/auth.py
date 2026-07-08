"""Authentication and recruiter account exceptions."""

from src.core.exceptions.base import (
    AuthenticationException,
    BadRequestException,
    ConflictException,
    NotFoundException,
)


class EmailAlreadyRegisteredException(ConflictException):
    message = "A recruiter with this email already exists."
    error_code = "AUTH_EMAIL_ALREADY_REGISTERED"


class InvalidCredentialsException(AuthenticationException):
    message = "Invalid email or password."
    error_code = "AUTH_INVALID_CREDENTIALS"


class InactiveAccountException(AuthenticationException):
    message = "Recruiter account is inactive."
    error_code = "AUTH_INACTIVE_ACCOUNT"


class InvalidRefreshTokenException(AuthenticationException):
    message = "Invalid or revoked refresh token."
    error_code = "AUTH_INVALID_REFRESH_TOKEN"


class ExpiredRefreshTokenException(AuthenticationException):
    message = "Expired refresh token."
    error_code = "AUTH_EXPIRED_REFRESH_TOKEN"


class InactiveOrMissingRecruiterException(AuthenticationException):
    message = "Recruiter account is inactive or not found."
    error_code = "AUTH_RECRUITER_INACTIVE_OR_MISSING"


class RecruiterNotFoundException(NotFoundException):
    message = "Recruiter not found."
    error_code = "AUTH_RECRUITER_NOT_FOUND"


class AccountNotFoundException(NotFoundException):
    message = "No account found with this email address."
    error_code = "AUTH_ACCOUNT_NOT_FOUND"


class PasswordResetUnavailableException(BadRequestException):
    message = "Password reset service is unavailable."
    error_code = "AUTH_PASSWORD_RESET_UNAVAILABLE"


class OtpExpiredException(BadRequestException):
    message = "OTP expired or not requested."
    error_code = "AUTH_OTP_EXPIRED"


class InvalidOtpException(BadRequestException):
    message = "Invalid OTP."
    error_code = "AUTH_INVALID_OTP"


class OtpStillActiveException(BadRequestException):
    message = "Please wait for the current OTP to expire before requesting a new one."
    error_code = "AUTH_OTP_STILL_ACTIVE"


class InactiveAccountOperationException(BadRequestException):
    message = "This account is inactive."
    error_code = "AUTH_INACTIVE_ACCOUNT_OPERATION"


class MissingIdentityHeaderException(AuthenticationException):
    message = "Missing identity header."
    error_code = "AUTH_MISSING_IDENTITY_HEADER"


class InvalidUserIdHeaderException(BadRequestException):
    message = "Invalid X-User-Id header format."
    error_code = "AUTH_INVALID_USER_ID_HEADER"
