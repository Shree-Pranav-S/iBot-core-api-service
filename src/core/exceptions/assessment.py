"""Assessment and job-description workflow exceptions."""

from src.core.exceptions.base import (
    BadGatewayException,
    BadRequestException,
    ForbiddenException,
    InternalServerException,
    NotFoundException,
)


class AssessmentNotFoundException(NotFoundException):
    message = "Assessment not found."
    error_code = "ASSESSMENT_NOT_FOUND"


class AssessmentAccessDeniedException(ForbiddenException):
    message = "You do not have access to this assessment."
    error_code = "ASSESSMENT_ACCESS_DENIED"


class InvalidFocusAreasException(BadRequestException):
    message = "Invalid focus areas."
    error_code = "ASSESSMENT_INVALID_FOCUS_AREAS"


class JdParseFailedException(InternalServerException):
    message = "Failed to parse job description PDF."
    error_code = "ASSESSMENT_JD_PARSE_FAILED"


class LlmAnalysisFailedException(BadGatewayException):
    message = "Failed to analyze job description with LLM."
    error_code = "ASSESSMENT_LLM_ANALYSIS_FAILED"


class AssessmentValidationException(BadRequestException):
    message = "Assessment validation failed."
    error_code = "ASSESSMENT_VALIDATION_FAILED"


class InvalidAssessmentIdException(BadRequestException):
    message = "Invalid assessment_id format — must be a valid UUID."
    error_code = "ASSESSMENT_INVALID_ID"
