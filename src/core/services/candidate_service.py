"""Business logic for bulk candidate upload, assessment matching, and invitation dispatch."""

import asyncio
import csv
import io
import logging
import uuid
from pathlib import Path

from src.config.settings import settings
from src.core.exceptions import (
    AssessmentAccessDeniedException,
    AssessmentNotFoundException,
    BadRequestException,
    CandidateAccessDeniedException,
    CandidateNotFoundException,
    CandidateRegistrationNotFoundException,
    CsvValidationException,
    DuplicateEnrollmentException,
)
from src.core.services.realtime_event_service import publish_recruiter_event
from src.data.clients.postgres_client import async_session_scope
from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.candidate import Candidate
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.event_logs_repository import EventLogsRepository
from src.data.repositories.notification_log_repository import (
    NotificationLogRepository,
)
from src.handlers.celery_tasks.notification_tasks import enqueue_invitation_email
from src.schemas.candidate import BulkUploadResponse, CSVRowResult
from src.schemas.event_log import EventLogCreate, EventName, EventSource
from src.schemas.realtime import RecruiterEventType
from src.utils.candidates import (
    download_resume,
    parse_resume_from_file,
    send_hiring_decision_email,
    temporary_resume_path,
    write_temporary_resume,
)

logger = logging.getLogger(__name__)

# Required CSV column headers (case-insensitive)
REQUIRED_COLUMNS = {"name", "email", "resume"}

COMPLETED_ENROLLMENT_STATUSES = frozenset({"COMPLETED", "EVALUATED"})


def _find_reusable_resume_enrollment(
    enrollments: list[CandidateAssessment],
) -> CandidateAssessment | None:
    """Return the most recent enrollment with a completed parsed resume."""
    for enrollment in enrollments:
        if (
            enrollment.resume_parse_status == "COMPLETED"
            and enrollment.resume_parsed is not None
        ):
            return enrollment
    return None


class CandidateService:
    """Service layer managing bulk CSV upload, role matching, and invitation dispatch."""

    def __init__(
        self,
        candidate_repo: CandidateRepository,
        ca_repo: CandidateAssessmentRepository,
        assessment_repo: AssessmentRepository,
        event_logs_repo: EventLogsRepository,
    ) -> None:
        """Initialize the candidate service with its repositories."""
        self._candidate_repo = candidate_repo
        self._ca_repo = ca_repo
        self._assessment_repo = assessment_repo
        self._event_logs_repo = event_logs_repo

    async def _assert_no_window_overlap(
        self,
        candidate_id: uuid.UUID,
        new_assessment: Assessment,
    ) -> None:
        """Block enrollment when an active assessment window overlaps the new one."""
        all_enrollments = await self._ca_repo.get_all_by_candidate_id(candidate_id)
        new_start = new_assessment.window_start
        new_end = new_assessment.window_end

        for enrollment in all_enrollments:
            existing_assessment = enrollment.assessment
            if existing_assessment is None:
                continue

            ex_start = existing_assessment.window_start
            ex_end = existing_assessment.window_end
            overlaps = new_start < ex_end and ex_start < new_end
            if overlaps and enrollment.status not in COMPLETED_ENROLLMENT_STATUSES:
                raise CsvValidationException(
                    f"Candidate already has an active enrollment in "
                    f"'{existing_assessment.title}' (ID: {existing_assessment.id}) "
                    f"whose interview window overlaps with the new assessment. "
                    f"The candidate must complete that assessment first."
                )

    async def get_candidates_for_assessment(
        self, assessment_id: uuid.UUID, recruiter_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessments for a given assessment, enforcing recruiter ownership."""
        assessment = await self._assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise AssessmentNotFoundException()
        if assessment.recruiter_id != recruiter_id:
            raise AssessmentAccessDeniedException()
        return await self._ca_repo.get_all_by_assessment(assessment_id)

    async def bulk_upload_from_csv(
        self,
        recruiter_id: uuid.UUID,
        assessment_id: uuid.UUID,
        file_bytes: bytes,
        filename: str,
    ) -> BulkUploadResponse:
        """
        Parse the uploaded CSV and enroll each row into the selected assessment.

        The CSV must contain columns: name, email, resume.
        The target assessment is chosen in the UI and passed separately.
        """
        matched_assessment = await self._assessment_repo.get_by_id(assessment_id)
        if matched_assessment is None:
            raise AssessmentNotFoundException()
        if matched_assessment.recruiter_id != recruiter_id:
            raise AssessmentAccessDeniedException()

        assessment_id_str = str(assessment_id)

        # Parse CSV
        try:
            text = file_bytes.decode("utf-8-sig")  # handles BOM
        except UnicodeDecodeError:
            raise CsvValidationException("CSV file must be UTF-8 encoded.")

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise CsvValidationException(
                "CSV file appears to be empty or has no headers."
            )

        normalized_headers = {h.strip().lower() for h in reader.fieldnames}
        missing = REQUIRED_COLUMNS - normalized_headers
        if missing:
            raise CsvValidationException(
                f"CSV is missing required columns: {', '.join(sorted(missing))}. "
                f"Expected: name, email, resume."
            )

        rows = list(reader)
        if not rows:
            raise CsvValidationException("CSV file contains no data rows.")

        total_rows = len(rows)
        upload_id = uuid.uuid4()
        row_results: list[CSVRowResult] = []
        failure_events: list[EventLogCreate] = []
        successful_rows = 0
        failed_rows = 0

        processed_ca_records: list[
            tuple[CandidateAssessment, Assessment, str, str]
        ] = []

        for row_idx, raw_row in enumerate(rows, start=1):
            # Normalize keys
            row = {
                k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k
            }

            email = row.get("email", "")
            name = row.get("name", "")
            resume_placeholder = row.get("resume", "")

            if not email or not name or not resume_placeholder:
                reason = "Missing required fields: name, email, or resume."
                result = CSVRowResult(
                    row=row_idx,
                    email=email or "(empty)",
                    status="failed",
                    reason=reason,
                )
                row_results.append(result)
                failure_events.append(
                    EventLogCreate(
                        event_name=EventName.CSV_ROW_FAILED,
                        source_service=EventSource.CORE_API,
                        correlation_id=str(upload_id),
                        recruiter_id=recruiter_id,
                        metadata={
                            "filename": filename,
                            "row_number": row_idx,
                            "email": result.email,
                            "assessment_id": assessment_id_str,
                            "reason_code": "MISSING_REQUIRED_FIELDS",
                        },
                        error_message=reason,
                    )
                )
                failed_rows += 1
                continue

            # Create or enroll candidate for this assessment row
            try:
                existing_candidate = await self._candidate_repo.get_by_email(email)

                existing_ca = None
                if existing_candidate is not None:
                    existing_ca = await self._ca_repo.get_by_candidate_and_assessment(
                        existing_candidate.id, matched_assessment.id
                    )
                    if existing_ca is not None:
                        reason = "Candidate is already registered for this assessment."
                        row_results.append(
                            CSVRowResult(
                                row=row_idx,
                                email=email,
                                status="failed",
                                reason=reason,
                            )
                        )
                        failure_events.append(
                            EventLogCreate(
                                event_name=EventName.CSV_ROW_FAILED,
                                source_service=EventSource.CORE_API,
                                correlation_id=str(upload_id),
                                recruiter_id=recruiter_id,
                                metadata={
                                    "filename": filename,
                                    "row_number": row_idx,
                                    "email": email,
                                    "assessment_id": assessment_id_str,
                                    "reason_code": "CANDIDATE_ALREADY_REGISTERED",
                                },
                                error_message=reason,
                            )
                        )
                        failed_rows += 1
                        continue

                    candidate = existing_candidate
                    if name and candidate.full_name != name:
                        candidate.full_name = name
                        await self._candidate_repo.update_candidate(candidate)
                else:
                    candidate = await self._candidate_repo.create_candidate(
                        full_name=name,
                        email=email,
                        created_by=recruiter_id,
                    )

                await self._assert_no_window_overlap(candidate.id, matched_assessment)

                ca_record = await self._ca_repo.create(
                    candidate_id=candidate.id,
                    assessment_id=matched_assessment.id,
                    resume_file_path=resume_placeholder,
                )

                processed_ca_records.append(
                    (ca_record, matched_assessment, name, email)
                )

                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email,
                        status="success",
                        reason=None,
                    )
                )
                successful_rows += 1

            except BadRequestException as exc:
                reason = str(exc)
                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email,
                        status="failed",
                        reason=reason,
                    )
                )
                failure_events.append(
                    EventLogCreate(
                        event_name=EventName.CSV_ROW_FAILED,
                        source_service=EventSource.CORE_API,
                        correlation_id=str(upload_id),
                        recruiter_id=recruiter_id,
                        metadata={
                            "filename": filename,
                            "row_number": row_idx,
                            "email": email,
                            "assessment_id": assessment_id_str,
                            "reason_code": "ROW_VALIDATION_FAILED",
                        },
                        error_message=reason,
                    )
                )
                failed_rows += 1
            except Exception as exc:
                logger.exception(
                    "Failed to process CSV row %d for email %s", row_idx, email
                )
                reason = "The row could not be processed because of an internal error."
                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email,
                        status="failed",
                        reason=reason,
                    )
                )
                failure_events.append(
                    EventLogCreate(
                        event_name=EventName.CSV_ROW_FAILED,
                        source_service=EventSource.CORE_API,
                        correlation_id=str(upload_id),
                        recruiter_id=recruiter_id,
                        metadata={
                            "filename": filename,
                            "row_number": row_idx,
                            "email": email,
                            "assessment_id": assessment_id_str,
                            "reason_code": "ROW_PROCESSING_FAILED",
                            "exception_type": type(exc).__name__,
                        },
                        error_message=reason,
                    )
                )
                failed_rows += 1

        await self._event_logs_repo.create_many(failure_events)
        overall_status = "COMPLETED" if failed_rows == 0 else "COMPLETED_WITH_ERRORS"

        # Queue post-commit work so workers only see durable candidate rows.
        for (
            ca_record,
            assessment,
            candidate_name,
            recipient_email,
        ) in processed_ca_records:
            invitation_link = settings.interview_invitation_url(
                ca_record.invitation_token
            )

            def _trigger_email(
                c_id: uuid.UUID = ca_record.id,
                c_name: str = candidate_name,
                c_email: str = recipient_email,
                a_title: str = assessment.title,
                a_role: str = assessment.role_name,
                a_link: str = invitation_link,
                a_dur: int = assessment.interview_duration_mins,
            ) -> None:
                enqueue_invitation_email(
                    ca_record_id=c_id,
                    candidate_name=c_name,
                    recipient_email=c_email,
                    assessment_title=a_title,
                    role_name=a_role,
                    invitation_link=a_link,
                    interview_duration_mins=a_dur,
                )

            self._ca_repo.register_after_commit_callback(_trigger_email)
            if ca_record.resume_file_path:

                def _trigger_resume(
                    c_id: uuid.UUID = ca_record.id,
                    r_url: str = str(ca_record.resume_file_path),
                ) -> None:
                    asyncio.create_task(
                        self.process_candidate_resume_in_background(
                            ca_record_id=c_id,
                            resume_url=r_url,
                        )
                    )

                self._ca_repo.register_after_commit_callback(_trigger_resume)

        return BulkUploadResponse(
            upload_id=upload_id,
            total_rows=total_rows,
            successful_rows=successful_rows,
            failed_rows=failed_rows,
            row_results=row_results,
            overall_status=overall_status,
        )

    async def create_single_candidate(
        self,
        recruiter_id: uuid.UUID,
        name: str,
        email: str,
        assessment_id: uuid.UUID,
        resume_file_bytes: bytes,
        resume_filename: str,
    ) -> CandidateAssessment:
        """Create a single candidate and dispatch processing and email."""
        # Verify assessment belongs to recruiter
        matched_assessment = await self._assessment_repo.get_by_id(assessment_id)
        if (
            matched_assessment is None
            or matched_assessment.recruiter_id != recruiter_id
        ):
            raise CsvValidationException(
                f"No assessment found with ID '{assessment_id}' for your account."
            )

        existing_candidate = await self._candidate_repo.get_by_email(email)
        if existing_candidate is not None:
            existing_enrollments = await self._ca_repo.get_all_by_candidate_id(
                existing_candidate.id
            )
            if existing_enrollments:
                raise CsvValidationException(
                    "A candidate with this email already exists. "
                    "Use Enroll to add them to another assessment."
                )

            # Older delete flows could leave a candidate row behind after its final
            # enrollment was removed. Such rows are not visible in the UI, but the
            # global email constraint still blocks recreation until they are removed.
            logger.warning(
                "Removing orphan candidate before recreation",
                extra={
                    "candidate_id": str(existing_candidate.id),
                    "email": existing_candidate.email,
                },
            )
            await self._candidate_repo.delete_candidate(existing_candidate)

        candidate = await self._candidate_repo.create_candidate(
            full_name=name,
            email=email,
            created_by=recruiter_id,
        )

        await self._assert_no_window_overlap(candidate.id, matched_assessment)

        existing_ca = await self._ca_repo.get_by_candidate_and_assessment(
            candidate.id, matched_assessment.id
        )
        if existing_ca is not None:
            raise DuplicateEnrollmentException()

        ca_record = await self._ca_repo.create(
            candidate_id=candidate.id,
            assessment_id=matched_assessment.id,
            resume_file_path=resume_filename,
        )

        temp_file_path = await write_temporary_resume(
            ca_record.id,
            resume_file_bytes,
        )

        invitation_link = settings.interview_invitation_url(ca_record.invitation_token)

        def _trigger_single_email() -> None:
            enqueue_invitation_email(
                ca_record_id=ca_record.id,
                candidate_name=name,
                recipient_email=email,
                assessment_title=matched_assessment.title,
                role_name=matched_assessment.role_name,
                invitation_link=invitation_link,
                interview_duration_mins=matched_assessment.interview_duration_mins,
            )

        self._ca_repo.register_after_commit_callback(_trigger_single_email)

        def _trigger_single_resume() -> None:
            asyncio.create_task(
                self.process_candidate_resume_in_background(
                    ca_record_id=ca_record.id,
                    temp_file_path=str(temp_file_path),
                )
            )

        self._ca_repo.register_after_commit_callback(_trigger_single_resume)

        return ca_record

    async def get_all_candidates_for_recruiter(
        self, recruiter_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessments for all assessments owned by the recruiter."""
        return await self._ca_repo.get_all_by_recruiter(recruiter_id)

    async def get_unique_candidates_for_recruiter(
        self, recruiter_id: uuid.UUID
    ) -> list:
        """Return unique candidates enrolled in any of this recruiter's assessments."""
        return await self._candidate_repo.get_distinct_by_recruiter_enrollments(
            recruiter_id
        )

    async def enroll_existing_candidate(
        self,
        recruiter_id: uuid.UUID,
        candidate_id: uuid.UUID,
        assessment_id: uuid.UUID,
        resume_file_bytes: bytes | None,
        resume_filename: str | None,
    ) -> tuple[CandidateAssessment, Candidate]:
        """
        Enroll an existing candidate into a new assessment.

        Checks for time window overlaps across the candidate's existing enrollments.
        If a window conflict exists, the conflicting enrollment must be COMPLETED or EVALUATED
        for the enrollment to proceed. A new resume may optionally be supplied;
        if omitted the previous enrollment's resume path is reused.
        """
        # Verify assessment belongs to recruiter
        new_assessment = await self._assessment_repo.get_by_id(assessment_id)
        if new_assessment is None or new_assessment.recruiter_id != recruiter_id:
            raise AssessmentNotFoundException()

        # Verify candidate exists
        candidate = await self._candidate_repo.get_by_id(candidate_id)
        if candidate is None:
            raise CandidateNotFoundException()

        # Prevent duplicate registration
        existing_ca = await self._ca_repo.get_by_candidate_and_assessment(
            candidate_id, assessment_id
        )
        if existing_ca is not None:
            raise DuplicateEnrollmentException()

        all_enrollments = await self._ca_repo.get_all_by_candidate_id(candidate_id)

        has_recruiter_enrollment = any(
            enrollment.assessment is not None
            and enrollment.assessment.recruiter_id == recruiter_id
            for enrollment in all_enrollments
        )
        if not has_recruiter_enrollment and candidate.created_by != recruiter_id:
            raise CandidateAccessDeniedException(
                "You do not have permission to enroll this candidate."
            )

        await self._assert_no_window_overlap(candidate_id, new_assessment)

        reusable_enrollment = _find_reusable_resume_enrollment(all_enrollments)

        if resume_file_bytes and resume_filename:
            resume_path = resume_filename
            resume_parse_status = "PENDING"
            resume_parsed = None
        elif reusable_enrollment is not None:
            resume_path = reusable_enrollment.resume_file_path
            resume_parse_status = "COMPLETED"
            resume_parsed = reusable_enrollment.resume_parsed
        else:
            resume_path = "placeholder_resume.pdf"
            for enrollment in all_enrollments:
                if (
                    enrollment.resume_file_path
                    and enrollment.resume_file_path != "placeholder_resume.pdf"
                ):
                    resume_path = enrollment.resume_file_path
                    break
            resume_parse_status = "PENDING"
            resume_parsed = None
            if resume_path == "placeholder_resume.pdf":
                logger.warning(
                    "Enrolling candidate %s without resume and no prior parsed resume",
                    candidate_id,
                )

        ca_record = await self._ca_repo.create(
            candidate_id=candidate_id,
            assessment_id=assessment_id,
            resume_file_path=resume_path,
            resume_parse_status=resume_parse_status,
            resume_parsed=resume_parsed,
        )

        invitation_link = settings.interview_invitation_url(ca_record.invitation_token)

        def _trigger_enroll_email() -> None:
            enqueue_invitation_email(
                ca_record_id=ca_record.id,
                candidate_name=candidate.full_name,
                recipient_email=candidate.email,
                assessment_title=new_assessment.title,
                role_name=new_assessment.role_name,
                invitation_link=invitation_link,
                interview_duration_mins=new_assessment.interview_duration_mins,
            )

        self._ca_repo.register_after_commit_callback(_trigger_enroll_email)

        if resume_file_bytes and resume_filename:
            temp_file_path = await write_temporary_resume(
                ca_record.id, resume_file_bytes
            )

            def _trigger_enroll_resume() -> None:
                asyncio.create_task(
                    self.process_candidate_resume_in_background(
                        ca_record_id=ca_record.id,
                        temp_file_path=str(temp_file_path),
                    )
                )

            self._ca_repo.register_after_commit_callback(_trigger_enroll_resume)

        return ca_record, candidate

    async def update_recruiter_decision(
        self,
        ca_id: uuid.UUID,
        recruiter_id: uuid.UUID,
        decision: str,
        feedback: str | None = None,
    ) -> CandidateAssessment:
        """Validate ownership and persist the recruiter decision."""
        ca = await self._ca_repo.get_by_id(ca_id)
        if ca is None:
            raise CandidateRegistrationNotFoundException()

        if ca.assessment.recruiter_id != recruiter_id:
            raise CandidateAccessDeniedException(
                "You do not have permission to update this candidate."
            )

        previous_decision = ca.recruiter_decision
        candidate_name = ca.candidate.full_name if ca.candidate else ""
        recipient_email = ca.candidate.email if ca.candidate else ""
        assessment_title = ca.assessment.title if ca.assessment else ""
        role_name = ca.assessment.role_name if ca.assessment else ""
        updated = await self._ca_repo.update_recruiter_decision(
            ca,
            decision=decision,
            feedback=feedback,
        )

        if previous_decision != decision and recipient_email:
            asyncio.create_task(
                self.dispatch_decision_with_logging(
                    ca_record_id=updated.id,
                    candidate_name=candidate_name,
                    recipient_email=recipient_email,
                    assessment_title=assessment_title,
                    role_name=role_name,
                    decision=decision,
                    feedback=feedback,
                )
            )

        return updated

    async def delete_candidate_from_assessment(
        self, ca_id: uuid.UUID, recruiter_id: uuid.UUID
    ) -> None:
        """Delete a candidate assessment and remove the candidate if no enrollments remain."""
        ca = await self._ca_repo.get_by_id(ca_id)
        if ca is None:
            raise CandidateRegistrationNotFoundException()

        if ca.assessment.recruiter_id != recruiter_id:
            raise CandidateAccessDeniedException(
                "You do not have permission to delete this candidate."
            )

        candidate_id = ca.candidate_id
        await self._ca_repo.delete(ca)

        remaining_enrollments = await self._ca_repo.get_all_by_candidate_id(
            candidate_id
        )
        if not remaining_enrollments:
            candidate = await self._candidate_repo.get_by_id(candidate_id)
            if candidate is not None:
                await self._candidate_repo.delete_candidate(candidate)

    async def process_candidate_resume_in_background(
        self, ca_record_id, resume_url=None, temp_file_path=None
    ):
        """Parse a candidate resume asynchronously and publish the result state."""
        try:
            if resume_url:
                temp_file_path = str(temporary_resume_path(ca_record_id))
                await download_resume(resume_url, temp_file_path)

            if not temp_file_path:
                logger.warning(
                    "No resume_url or temp_file_path provided for ca_record_id %s",
                    ca_record_id,
                )
                return

            resume_parsed = await parse_resume_from_file(temp_file_path)

            async with async_session_scope() as session:
                repository = CandidateAssessmentRepository(session)
                await repository.save_parsed_resume_success(ca_record_id, resume_parsed)
                realtime_context = await repository.get_realtime_context(ca_record_id)
            if realtime_context:
                await publish_recruiter_event(
                    recruiter_id=realtime_context["recruiter_id"],
                    event_type=RecruiterEventType.RESUME_PARSING_COMPLETED,
                    payload={
                        **realtime_context,
                        "resume_parse_status": "COMPLETED",
                    },
                )

        except Exception as exc:
            logger.exception("Failed to parse resume for ca_record %s", ca_record_id)
            try:
                async with async_session_scope() as session:
                    repository = CandidateAssessmentRepository(session)
                    await repository.save_parsed_resume_failed(ca_record_id, str(exc))
                    realtime_context = await repository.get_realtime_context(
                        ca_record_id
                    )
                if realtime_context:
                    await publish_recruiter_event(
                        recruiter_id=realtime_context["recruiter_id"],
                        event_type=RecruiterEventType.RESUME_PARSING_FAILED,
                        payload={
                            **realtime_context,
                            "resume_parse_status": "FAILED",
                        },
                    )
            except Exception:
                logger.exception(
                    "Could not persist failed resume parsing state for %s",
                    ca_record_id,
                )
        finally:
            if temp_file_path:
                try:
                    await asyncio.to_thread(
                        Path(temp_file_path).unlink,
                        missing_ok=True,
                    )
                except OSError:
                    logger.warning(
                        "Could not remove temporary resume %s",
                        temp_file_path,
                        exc_info=True,
                    )

    async def dispatch_decision_with_logging(
        self,
        ca_record_id,
        candidate_name,
        recipient_email,
        assessment_title,
        role_name,
        decision,
        feedback=None,
    ):
        """Send a hiring decision email and persist delivery status."""
        notification_type = "APPROVAL" if decision == "APPROVED" else "REJECTION"
        try:
            await send_hiring_decision_email(
                candidate_name=candidate_name,
                recipient_email=recipient_email,
                assessment_title=assessment_title,
                role_name=role_name,
                decision=decision,
                feedback=feedback,
            )

            async with async_session_scope() as session:
                await NotificationLogRepository(session).log_decision_sent(
                    ca_record_id, recipient_email, notification_type
                )
        except Exception as exc:
            logger.exception(
                "Failed to dispatch hiring decision email for candidate %s",
                ca_record_id,
            )
            try:
                async with async_session_scope() as session:
                    await NotificationLogRepository(session).log_decision_failed(
                        ca_record_id,
                        recipient_email,
                        notification_type,
                        f"{type(exc).__name__}: {exc}",
                    )
            except Exception:
                pass
