"""Notification and email workflow exceptions."""

from src.core.exceptions.base import NotFoundException


class ReportContextNotFoundException(NotFoundException):
    message = "Report email context not found."
    error_code = "NOTIFICATION_REPORT_CONTEXT_NOT_FOUND"
