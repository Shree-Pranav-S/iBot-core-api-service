"""
Notification schemas.

Covers notification log entries and internal Celery task payloads
for each email type dispatched by the notification workers.
"""

import uuid
from datetime import datetime

from src.schemas.base import AppBaseModel, ORMBaseModel

# ── Notification log response ─────────────────────────────────────────────────


class NotificationLogResponse(ORMBaseModel):
    """Notification log entry as returned by the API."""

    id: uuid.UUID
    candidate_assessment_id: uuid.UUID
    notification_type: str
    recipient_email: str
    sent_at: datetime
    delivery_status: str
    error_message: str | None


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


# ── Internal Celery task payloads ─────────────────────────────────────────────
# These are not exposed via HTTP — they are used as typed dicts
# passed to Celery task arguments.


class SendInvitationPayload(AppBaseModel):
    """Payload for the send_invitation_email Celery task."""

    candidate_assessment_id: uuid.UUID
    recipient_email: str
    candidate_name: str
    assessment_title: str
    invitation_link: str
    window_start: datetime
    window_end: datetime
    interview_duration_mins: int


class SendReminderPayload(AppBaseModel):
    """Payload for the send_reminder_email Celery task."""

    candidate_assessment_id: uuid.UUID
    recipient_email: str
    candidate_name: str
    assessment_title: str
    invitation_link: str
    window_end: datetime
    reminder_type: str  # "24h" | "8h" | "1h"


class SendOutcomePayload(AppBaseModel):
    """Payload for the send_approval_email / send_rejection_email Celery tasks."""

    candidate_assessment_id: uuid.UUID
    recipient_email: str
    candidate_name: str
    decision: str  # APPROVED | REJECTED
    recruiter_feedback: str | None = None
    ai_concern_summary: str | None = None
