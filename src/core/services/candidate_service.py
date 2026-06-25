"""Business logic for bulk candidate upload, role matching, and invitation dispatch."""

import asyncio
import csv
import io
import logging
import os
import uuid

from src.config.settings import settings
from src.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_repository import (
    CandidateAssessmentRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.csv_upload_log_repository import CSVUploadLogRepository
from src.data.repositories.notification_log_repository import (
    NotificationLogRepository,
)
from src.handlers.celery_tasks.notification_tasks import enqueue_invitation_email
from src.schemas.candidate import BulkUploadResponse, CSVRowResult
from src.utils.candidates import (
    download_resume,
    parse_resume_from_file,
    send_hiring_decision_email,
)

logger = logging.getLogger(__name__)

# Required CSV column headers (case-insensitive)
REQUIRED_COLUMNS = {"name", "email", "resume", "role"}


class CandidateService:
    """Service layer managing bulk CSV upload, role matching, and invitation dispatch."""

    def __init__(
        self,
        candidate_repo: CandidateRepository,
        ca_repo: CandidateAssessmentRepository,
        assessment_repo: AssessmentRepository,
        upload_log_repo: CSVUploadLogRepository,
    ) -> None:
        self._candidate_repo = candidate_repo
        self._ca_repo = ca_repo
        self._assessment_repo = assessment_repo
        self._upload_log_repo = upload_log_repo

    async def get_candidates_for_assessment(
        self, assessment_id: uuid.UUID, recruiter_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessments for a given assessment, enforcing recruiter ownership."""
        assessment = await self._assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise NotFoundException("Assessment not found.")
        if assessment.recruiter_id != recruiter_id:
            raise ForbiddenException("You do not have access to this assessment.")
        return await self._ca_repo.get_all_by_assessment(assessment_id)

    async def bulk_upload_from_csv(
        self,
        recruiter_id: uuid.UUID,
        file_bytes: bytes,
        filename: str,
    ) -> BulkUploadResponse:
        """
        Parse the uploaded CSV, match each candidate's role to an active assessment,
        create candidate and candidate-assessment records, and dispatch invitation emails.

        The CSV must contain columns: name, email, resume, role.
        Role matching is case-insensitive against active assessments owned by this recruiter.
        """
        # Parse CSV
        try:
            text = file_bytes.decode("utf-8-sig")  # handles BOM
        except UnicodeDecodeError:
            raise BadRequestException("CSV file must be UTF-8 encoded.")

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise BadRequestException("CSV file appears to be empty or has no headers.")

        normalized_headers = {h.strip().lower() for h in reader.fieldnames}
        missing = REQUIRED_COLUMNS - normalized_headers
        if missing:
            raise BadRequestException(
                f"CSV is missing required columns: {', '.join(sorted(missing))}. "
                f"Expected: name, email, resume, role."
            )

        rows = list(reader)
        if not rows:
            raise BadRequestException("CSV file contains no data rows.")

        # Load all active assessments owned by this recruiter
        all_assessments = await self._assessment_repo.get_all_by_recruiter(recruiter_id)
        # Build a role_name -> assessment lookup (case-insensitive)
        role_assessment_map: dict[str, object] = {
            a.role_name.strip().lower(): a for a in all_assessments
        }

        # Create the upload log record immediately
        total_rows = len(rows)
        # Use the first matching assessment for the log (or a placeholder UUID)
        # We defer associating to assessment_id until we know the overall dominant one.
        # For simplicity, use a sentinel and update per-row.
        # We'll use recruiter's first assessment for the log, or handle per-row.
        # Since CSV can have multiple roles, we'll use None and handle below.
        # Actually: create one log per CSV upload - use assessment_id from first successful row.

        row_results: list[CSVRowResult] = []
        successful_rows = 0
        failed_rows = 0

        # We collect which assessment_id to use for the log after processing.
        dominant_assessment_id: uuid.UUID | None = None
        processed_ca_records: list[tuple[CandidateAssessment, object, str, str]] = []

        for row_idx, raw_row in enumerate(rows, start=1):
            # Normalize keys
            row = {
                k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k
            }

            email = row.get("email", "")
            name = row.get("name", "")
            resume_placeholder = row.get("resume", "placeholder_resume.pdf")
            role = row.get("role", "")

            if not email or not name or not role:
                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email or "(empty)",
                        status="failed",
                        reason="Missing required fields: name, email, or role.",
                    )
                )
                failed_rows += 1
                continue

            # Role matching
            matched_assessment = role_assessment_map.get(role.lower())
            if matched_assessment is None:
                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email,
                        status="failed",
                        reason=(
                            f"No assessment found for role '{role}'. "
                            "Ensure an assessment with this role name exists and is active."
                        ),
                    )
                )
                failed_rows += 1
                continue

            #  Upsert Candidate
            try:
                existing_candidate = await self._candidate_repo.get_by_email(email)
                if existing_candidate is None:
                    candidate = await self._candidate_repo.create_candidate(
                        full_name=name,
                        email=email,
                        created_by=recruiter_id,
                    )
                else:
                    candidate = existing_candidate
                    if name and candidate.full_name != name:
                        candidate.full_name = name
                        await self._candidate_repo.update_candidate(candidate)

                # Link to assessment (skip if already linked)
                existing_ca = await self._ca_repo.get_by_candidate_and_assessment(
                    candidate.id, matched_assessment.id
                )
                if existing_ca is not None:
                    row_results.append(
                        CSVRowResult(
                            row=row_idx,
                            email=email,
                            status="failed",
                            reason="Candidate is already registered for this assessment.",
                        )
                    )
                    failed_rows += 1
                    continue

                ca_record = await self._ca_repo.create(
                    candidate_id=candidate.id,
                    assessment_id=matched_assessment.id,
                    resume_file_path=resume_placeholder,
                )

                if dominant_assessment_id is None:
                    dominant_assessment_id = matched_assessment.id

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

            except Exception as exc:
                logger.exception(
                    "Failed to process CSV row %d for email %s", row_idx, email
                )
                row_results.append(
                    CSVRowResult(
                        row=row_idx,
                        email=email,
                        status="failed",
                        reason=f"Internal error: {exc}",
                    )
                )
                failed_rows += 1

        #  Create the CSV upload log
        # Use dominant assessment id or fall back to the first available assessment
        log_assessment_id = dominant_assessment_id or (
            all_assessments[0].id if all_assessments else None
        )

        upload_log = None
        if log_assessment_id is not None:
            overall_status = (
                "COMPLETED"
                if failed_rows == 0
                else (
                    "COMPLETED_WITH_ERRORS"
                    if successful_rows > 0
                    else "COMPLETED_WITH_ERRORS"
                )
            )
            upload_log = await self._upload_log_repo.create(
                recruiter_id=recruiter_id,
                assessment_id=log_assessment_id,
                total_rows=total_rows,
                successful_rows=successful_rows,
                failed_rows=failed_rows,
                row_results=[r.model_dump() for r in row_results],
                overall_status=overall_status,
            )

        # Queue post-commit work so workers only see durable candidate rows.
        for (
            ca_record,
            assessment,
            candidate_name,
            recipient_email,
        ) in processed_ca_records:
            invitation_link = (
                f"{settings.FRONTEND_URL}/interview?token={ca_record.invitation_token}"
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
            upload_id=upload_log.id if upload_log else uuid.uuid4(),
            total_rows=total_rows,
            successful_rows=successful_rows,
            failed_rows=failed_rows,
            row_results=row_results,
            overall_status=upload_log.overall_status
            if upload_log
            else "COMPLETED_WITH_ERRORS",
        )

    async def create_single_candidate(
        self,
        recruiter_id: uuid.UUID,
        name: str,
        email: str,
        role: str,
        resume_file_bytes: bytes,
        resume_filename: str,
    ) -> CandidateAssessment:
        """Create a single candidate and dispatch processing and email."""
        import os

        # Match assessment
        all_assessments = await self._assessment_repo.get_all_by_recruiter(recruiter_id)
        role_assessment_map = {a.role_name.strip().lower(): a for a in all_assessments}
        matched_assessment = role_assessment_map.get(role.strip().lower())

        if matched_assessment is None:
            raise BadRequestException(f"No assessment found for role '{role}'.")

        existing_candidate = await self._candidate_repo.get_by_email(email)
        if existing_candidate is None:
            candidate = await self._candidate_repo.create_candidate(
                full_name=name,
                email=email,
                created_by=recruiter_id,
            )
        else:
            candidate = existing_candidate
            if name and candidate.full_name != name:
                candidate.full_name = name
                await self._candidate_repo.update_candidate(candidate)

        existing_ca = await self._ca_repo.get_by_candidate_and_assessment(
            candidate.id, matched_assessment.id
        )
        if existing_ca is not None:
            raise BadRequestException(
                "Candidate is already registered for this assessment."
            )

        ca_record = await self._ca_repo.create(
            candidate_id=candidate.id,
            assessment_id=matched_assessment.id,
            resume_file_path=resume_filename,
        )

        # Save resume locally
        os.makedirs("temp_resumes", exist_ok=True)
        temp_file_path = f"temp_resumes/{ca_record.id}.pdf"
        with open(temp_file_path, "wb") as f:
            f.write(resume_file_bytes)

        invitation_link = (
            f"{settings.FRONTEND_URL}/interview?token={ca_record.invitation_token}"
        )

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
                    temp_file_path=temp_file_path,
                )
            )

        self._ca_repo.register_after_commit_callback(_trigger_single_resume)

        return ca_record

    async def get_all_candidates_for_recruiter(
        self, recruiter_id: uuid.UUID
    ) -> list[CandidateAssessment]:
        """Return all candidate-assessments for all assessments owned by the recruiter."""
        return await self._ca_repo.get_all_by_recruiter(recruiter_id)

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
            raise NotFoundException("Candidate registration not found.")

        if ca.assessment.recruiter_id != recruiter_id:
            raise ForbiddenException(
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
        """Validate recruiter ownership and delete the candidate assessment from database."""
        ca = await self._ca_repo.get_by_id(ca_id)
        if ca is None:
            raise NotFoundException("Candidate registration not found.")

        if ca.assessment.recruiter_id != recruiter_id:
            raise ForbiddenException(
                "You do not have permission to delete this candidate."
            )

        await self._ca_repo.delete(ca)

    async def process_candidate_resume_in_background(
        self, ca_record_id, resume_url=None, temp_file_path=None
    ):
        from src.data.repositories.candidate_assessment_repository import (
            CandidateAssessmentRepository,
        )

        try:
            if resume_url:
                os.makedirs("temp_resumes", exist_ok=True)
                temp_file_path = f"temp_resumes/{ca_record_id}.pdf"
                await download_resume(resume_url, temp_file_path)

            if not temp_file_path:
                logger.warning(
                    "No resume_url or temp_file_path provided for ca_record_id %s",
                    ca_record_id,
                )
                return

            resume_parsed = await parse_resume_from_file(temp_file_path)

            await (
                CandidateAssessmentRepository.save_parsed_resume_success_in_background(
                    ca_record_id, resume_parsed
                )
            )

        except Exception as exc:
            logger.exception("Failed to parse resume for ca_record %s", ca_record_id)
            try:
                await CandidateAssessmentRepository.save_parsed_resume_failed_in_background(
                    ca_record_id, str(exc)
                )
            except Exception:
                pass
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

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
            await NotificationLogRepository.log_decision_sent_in_background(
                ca_record_id,
                recipient_email,
                notification_type,
            )
        except Exception as exc:
            logger.exception(
                "Failed to dispatch hiring decision email for candidate %s",
                ca_record_id,
            )
            try:
                await NotificationLogRepository.log_decision_failed_in_background(
                    ca_record_id,
                    recipient_email,
                    notification_type,
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
