"""Repository for CSV upload log data access."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.csv_upload_log import CSVUploadLog

logger = logging.getLogger(__name__)


class CSVUploadLogRepository:
    """Data access layer for CSV upload batch tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        recruiter_id: uuid.UUID,
        assessment_id: uuid.UUID,
        total_rows: int,
        successful_rows: int = 0,
        failed_rows: int = 0,
        row_results: list[dict] | None = None,
        overall_status: str = "PROCESSING",
    ) -> CSVUploadLog:
        """Create and flush a new CSV upload log record."""
        log = CSVUploadLog(
            recruiter_id=recruiter_id,
            assessment_id=assessment_id,
            total_rows=total_rows,
            successful_rows=successful_rows,
            failed_rows=failed_rows,
            row_results=row_results or [],
            overall_status=overall_status,
        )
        self._session.add(log)
        await self._session.flush()
        await self._session.refresh(log)
        logger.info(
            "CSVUploadLog created",
            extra={"upload_log_id": str(log.id)},
        )
        return log

    async def get_by_id(self, log_id: uuid.UUID) -> CSVUploadLog | None:
        """Return a CSVUploadLog by UUID."""
        statement = select(CSVUploadLog).where(CSVUploadLog.id == log_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
