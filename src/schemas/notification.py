"""
Notification schemas.

Covers recruiter-facing dashboard notifications.
"""

import uuid
from datetime import datetime

from src.schemas.base import AppBaseModel


class RecruiterDashboardNotification(AppBaseModel):
    """Human-friendly report notification shown in the recruiter dashboard."""

    id: uuid.UUID
    candidate_assessment_id: uuid.UUID
    notification_type: str
    title: str
    message: str
    candidate_name: str
    assessment_title: str
    role_name: str
    sent_at: datetime
