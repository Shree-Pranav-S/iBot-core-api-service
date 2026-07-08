"""Candidate upload, enrollment, and resume exceptions."""

from src.core.exceptions.base import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)


class CandidateNotFoundException(NotFoundException):
    message = "Candidate not found."
    error_code = "CANDIDATE_NOT_FOUND"


class CandidateRegistrationNotFoundException(NotFoundException):
    message = "Candidate registration not found."
    error_code = "CANDIDATE_REGISTRATION_NOT_FOUND"


class CandidateAccessDeniedException(ForbiddenException):
    message = "You do not have access to this candidate."
    error_code = "CANDIDATE_ACCESS_DENIED"


class CsvValidationException(BadRequestException):
    message = "CSV validation failed."
    error_code = "CANDIDATE_CSV_VALIDATION_FAILED"


class ResumeParseFailedException(BadRequestException):
    message = "Failed to parse resume."
    error_code = "CANDIDATE_RESUME_PARSE_FAILED"


class ResumeDownloadFailedException(BadRequestException):
    message = "Failed to download resume."
    error_code = "CANDIDATE_RESUME_DOWNLOAD_FAILED"


class DuplicateEnrollmentException(BadRequestException):
    message = "Candidate is already enrolled in this assessment."
    error_code = "CANDIDATE_DUPLICATE_ENROLLMENT"


class InvalidResumeFileException(BadRequestException):
    message = "Uploaded resume must be a PDF (.pdf extension)."
    error_code = "CANDIDATE_INVALID_RESUME_FILE"


class EmptyResumeFileException(BadRequestException):
    message = "Uploaded resume file is empty."
    error_code = "CANDIDATE_EMPTY_RESUME_FILE"


class InvalidCsvFileException(BadRequestException):
    message = "Uploaded file must be a CSV (.csv extension)."
    error_code = "CANDIDATE_INVALID_CSV_FILE"


class EmptyCsvFileException(BadRequestException):
    message = "Uploaded CSV file is empty."
    error_code = "CANDIDATE_EMPTY_CSV_FILE"


class InvalidCandidateIdException(BadRequestException):
    message = "Invalid candidate_id format — must be a valid UUID."
    error_code = "CANDIDATE_INVALID_ID"
