"""Repository for notification log data access."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.notification_log import NotificationLog

logger = logging.getLogger(__name__)


class NotificationLogRepository:
    """Data access layer for recording dispatched notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        candidate_assessment_id: uuid.UUID,
        notification_type: str,
        recipient_email: str,
        delivery_status: str = "SENT",
        error_message: str | None = None,
    ) -> NotificationLog:
        """Create and flush a new notification log record."""
        log = NotificationLog(
            candidate_assessment_id=candidate_assessment_id,
            notification_type=notification_type,
            recipient_email=recipient_email,
            delivery_status=delivery_status,
            error_message=error_message,
        )
        self._session.add(log)
        await self._session.flush()
        await self._session.refresh(log)
        logger.info(
            "NotificationLog created",
            extra={
                "notification_log_id": str(log.id),
                "type": notification_type,
                "recipient": recipient_email,
                "status": delivery_status,
            },
        )
        return log

    async def log_invitation_sent(self, ca_record_id, recipient_email):
        await self.create(
            candidate_assessment_id=ca_record_id,
            notification_type="INVITATION",
            recipient_email=recipient_email,
            delivery_status="SENT",
        )
        await self._session.flush()

    async def log_invitation_failed(self, ca_record_id, recipient_email, error_message):
        await self.create(
            candidate_assessment_id=ca_record_id,
            notification_type="INVITATION",
            recipient_email=recipient_email,
            delivery_status="FAILED",
            error_message=error_message,
        )
        await self._session.flush()

    @classmethod
    async def log_invitation_sent_in_background(
        cls, ca_record_id: uuid.UUID, recipient_email: str
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.log_invitation_sent(ca_record_id, recipient_email)
            await session.commit()

    @classmethod
    async def log_invitation_failed_in_background(
        cls, ca_record_id: uuid.UUID, recipient_email: str, error_message: str
    ) -> None:
        from src.data.clients.postgres_client import get_session_factory

        SessionLocal = await get_session_factory()
        async with SessionLocal() as session:
            repo = cls(session)
            await repo.log_invitation_failed(
                ca_record_id, recipient_email, error_message
            )
            await session.commit()
