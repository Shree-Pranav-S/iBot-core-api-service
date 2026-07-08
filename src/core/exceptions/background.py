"""Background task (Celery) exceptions."""

from src.core.exceptions.base import AppException


class BackgroundTaskException(AppException):
    """Base class for non-HTTP background task failures."""

    error_code = "BACKGROUND_TASK_FAILED"


class AssessmentTaskFailedException(BackgroundTaskException):
    message = "Assessment background task failed."
    error_code = "BACKGROUND_ASSESSMENT_TASK_FAILED"


class NotificationTaskFailedException(BackgroundTaskException):
    message = "Notification background task failed."
    error_code = "BACKGROUND_NOTIFICATION_TASK_FAILED"
