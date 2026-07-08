"""Recruiter evaluation access exceptions."""

from src.core.exceptions.base import ForbiddenException, NotFoundException


class EvaluationNotFoundException(NotFoundException):
    message = "Evaluation not found for this candidate."
    error_code = "EVALUATION_NOT_FOUND"


class EvaluationAccessDeniedException(ForbiddenException):
    message = "You do not have access to this evaluation."
    error_code = "EVALUATION_ACCESS_DENIED"
