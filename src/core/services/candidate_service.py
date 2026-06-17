"""Business logic for bulk candidate upload, role matching, and invitation dispatch."""

import asyncio
import csv
import io
import logging
import uuid

from src.config.settings import settings
from src.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.repositories.assessment_repository import AssessmentRepository
from src.data.repositories.candidate_assessment_full_repository import (
    CandidateAssessmentFullRepository,
)
from src.data.repositories.candidate_repository import CandidateRepository
from src.data.repositories.csv_upload_log_repository import CSVUploadLogRepository
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.schemas.candidate import BulkUploadResponse, CSVRowResult
from src.utils.candidates import _send_invitation_email

logger = logging.getLogger(__name__)

# Required CSV column headers (case-insensitive)
REQUIRED_COLUMNS = {"name", "email", "resume", "role"}


class CandidateService:
    """Service layer managing bulk CSV upload, role matching, and invitation dispatch."""

    def __init__(
        self,
        candidate_repo: CandidateRepository,
        ca_repo: CandidateAssessmentFullRepository,
        assessment_repo: AssessmentRepository,
        upload_log_repo: CSVUploadLogRepository,
        notification_log_repo: NotificationLogRepository,
    ) -> None:
        self._candidate_repo = candidate_repo
        self._ca_repo = ca_repo
        self._assessment_repo = assessment_repo
        self._upload_log_repo = upload_log_repo
        self._notification_log_repo = notification_log_repo

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
        # ── Parse CSV ────────────────────────────────────────────────────────
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

        # ── Load all active assessments owned by this recruiter ───────────────
        all_assessments = await self._assessment_repo.get_all_by_recruiter(recruiter_id)
        # Build a role_name -> assessment lookup (case-insensitive)
        role_assessment_map: dict[str, object] = {
            a.role_name.strip().lower(): a for a in all_assessments
        }

        # ── Create the upload log record immediately ──────────────────────────
        total_rows = len(rows)
        # Use the first matching assessment for the log (or a placeholder UUID)
        # We defer associating to assessment_id until we know the overall dominant one.
        # For simplicity, use a sentinel and update per-row.
        # We'll use recruiter's first assessment for the log, or handle per-row.
        # Since CSV can have multiple roles, we'll use None and handle below.
        # Actually: create one log per CSV upload — use assessment_id from first successful row.

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

            # ── Role matching ─────────────────────────────────────────────────
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

            # ── Upsert Candidate ──────────────────────────────────────────────
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

                # ── Link to assessment (skip if already linked) ───────────────
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

        # ── Create the CSV upload log ─────────────────────────────────────────
        # Use dominant assessment id or fall back to the first available assessment
        log_assessment_id = dominant_assessment_id or (
            all_assessments[0].id if all_assessments else None
        )

        upload_log = None
        if log_assessment_id is not None:
            upload_log = await self._upload_log_repo.create(
                recruiter_id=recruiter_id,
                assessment_id=log_assessment_id,
                total_rows=total_rows,
            )
            upload_log.successful_rows = successful_rows
            upload_log.failed_rows = failed_rows
            upload_log.row_results = [r.model_dump() for r in row_results]
            upload_log.overall_status = (
                "COMPLETED"
                if failed_rows == 0
                else (
                    "COMPLETED_WITH_ERRORS"
                    if successful_rows > 0
                    else "COMPLETED_WITH_ERRORS"
                )
            )

        # ── Dispatch invitation emails as background tasks ────────────────────
        for (
            ca_record,
            assessment,
            candidate_name,
            recipient_email,
        ) in processed_ca_records:
            invitation_link = (
                f"{settings.FRONTEND_URL}/interview?token={ca_record.invitation_token}"
            )
            # Fire-and-forget email: log but don't fail the upload on email error
            asyncio.create_task(
                _dispatch_invitation_with_logging(
                    ca_record_id=ca_record.id,
                    candidate_name=candidate_name,
                    recipient_email=recipient_email,
                    assessment_title=assessment.title,
                    role_name=assessment.role_name,
                    invitation_link=invitation_link,
                    interview_duration_mins=assessment.interview_duration_mins,
                )
            )
            # Fire-and-forget resume download and parsing
            if ca_record.resume_file_path:
                asyncio.create_task(
                    process_candidate_resume_in_background(
                        ca_record_id=ca_record.id,
                        resume_url=ca_record.resume_file_path,
                    )
                )

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

        # Dispatch email
        invitation_link = (
            f"{settings.FRONTEND_URL}/interview?token={ca_record.invitation_token}"
        )
        asyncio.create_task(
            _dispatch_invitation_with_logging(
                ca_record_id=ca_record.id,
                candidate_name=name,
                recipient_email=email,
                assessment_title=matched_assessment.title,
                role_name=matched_assessment.role_name,
                invitation_link=invitation_link,
                interview_duration_mins=matched_assessment.interview_duration_mins,
            )
        )

        # Dispatch background parsing
        asyncio.create_task(
            process_local_candidate_resume_in_background(
                ca_record_id=ca_record.id,
                temp_file_path=temp_file_path,
            )
        )

        return ca_record


def get_direct_download_url(url: str) -> str:
    """If the URL is a Google Drive share link, return a direct download URL."""
    import re

    gd_match = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url)
    if gd_match:
        file_id = gd_match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    gd_match_query = re.search(r"drive\.google\.com/.*id=([a-zA-Z0-9_-]+)", url)
    if gd_match_query:
        file_id = gd_match_query.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url


async def run_resume_analysis(resume_text: str, groq_client: object) -> dict:
    """Call Groq to extract structured fields from resume markdown text."""
    import json

    system_prompt = (
        "You are an expert resume parser and technical recruiter. "
        "Analyze the provided resume markdown text and extract structured candidate data.\n\n"
        "You MUST respond with a JSON object that strictly adheres to the following schema:\n"
        "{\n"
        '  "summary": "string (a concise 2-3 sentence technical summary of the candidate\'s background and strengths)",\n'
        '  "skills": ["string (key technical skills/tools/languages the candidate has experience with)"],\n'
        '  "experience_years": float (estimated total years of professional/technical work experience based on the resume timeline. Be realistic. If it is not clear, provide a best estimate)\n'
        "}\n"
        "Only return raw JSON. Do not include markdown code block formatting (such as ```json) or explanation."
    )

    completion = await groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Analyze this Candidate Resume:\n{resume_text}",
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw_content = completion.choices[0].message.content or ""
    return json.loads(raw_content)


async def process_candidate_resume_in_background(
    ca_record_id: uuid.UUID,
    resume_url: str,
) -> None:
    """Download candidate resume, parse using LlamaParse, extract structured data via Groq, and update CandidateAssessment."""
    import os

    import httpx
    from fastapi.concurrency import run_in_threadpool
    from groq import AsyncGroq
    from llama_parse import LlamaParse
    from sqlalchemy import select

    from src.data.clients.postgres_client import get_session_factory

    logger.info(
        "Starting background resume parsing for ca_record=%s from url=%s",
        ca_record_id,
        resume_url,
    )

    # 1. Setup local temporary storage path
    os.makedirs("temp_resumes", exist_ok=True)
    temp_file_path = f"temp_resumes/{ca_record_id}.pdf"

    SessionLocal = await get_session_factory()

    try:
        # Check if the URL is a dummy placeholder or invalid
        if not resume_url.startswith("http"):
            raise ValueError(f"Invalid resume URL (not HTTP/HTTPS): {resume_url}")

        # 2. Download the file
        download_url = get_direct_download_url(resume_url)
        logger.info(
            "Downloading resume from %s to local file %s", download_url, temp_file_path
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(download_url, timeout=30.0)
            response.raise_for_status()
            with open(temp_file_path, "wb") as f:
                f.write(response.content)

        # 3. Parse with LlamaParse
        api_key = settings.LLAMA_CLOUD_API_KEY
        if not api_key:
            raise ValueError("LLAMA_CLOUD_API_KEY is not configured in settings")

        parser = LlamaParse(api_key=api_key, result_type="markdown")
        extra_info = {"file_name": f"{ca_record_id}.pdf"}

        logger.info("Parsing resume using LlamaParse for ca_record=%s", ca_record_id)
        documents = await asyncio.wait_for(
            run_in_threadpool(parser.load_data, temp_file_path, extra_info=extra_info),
            timeout=60,
        )
        resume_text = "\n".join(doc.text for doc in documents)

        if not resume_text.strip():
            raise ValueError("Parsed resume text is empty")

        # 4. Analyze via Groq
        logger.info(
            "Analyzing parsed resume text via Groq for ca_record=%s", ca_record_id
        )
        groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        resume_parsed = await run_resume_analysis(resume_text, groq_client)

        # 5. Save to database
        async with SessionLocal() as db_session:
            # Retry fetching up to 5 times to wait for the CSV upload transaction to commit
            ca_record = None
            for _attempt in range(5):
                statement = select(CandidateAssessment).where(
                    CandidateAssessment.id == ca_record_id
                )
                result = await db_session.execute(statement)
                ca_record = result.scalar_one_or_none()
                if ca_record:
                    break
                await asyncio.sleep(0.5)

            if ca_record:
                ca_record.resume_parsed = resume_parsed
                ca_record.resume_parse_status = "COMPLETED"
                await db_session.commit()
                logger.info(
                    "Resume parsed and saved successfully in DB for ca_record=%s",
                    ca_record_id,
                )
            else:
                logger.error(
                    "CandidateAssessment %s not found in database to update parsing results",
                    ca_record_id,
                )

    except Exception as exc:
        logger.exception(
            "Failed to parse and save resume for ca_record %s", ca_record_id
        )

        # Mark as FAILED in database
        try:
            async with SessionLocal() as db_session:
                ca_record = None
                for _attempt in range(5):
                    statement = select(CandidateAssessment).where(
                        CandidateAssessment.id == ca_record_id
                    )
                    result = await db_session.execute(statement)
                    ca_record = result.scalar_one_or_none()
                    if ca_record:
                        break
                    await asyncio.sleep(0.5)

                if ca_record:
                    ca_record.resume_parse_status = "FAILED"
                    ca_record.resume_parsed = {
                        "error": str(exc),
                        "summary": "Failed to parse resume.",
                        "skills": [],
                        "experience_years": 0,
                    }
                    await db_session.commit()
                    logger.info(
                        "Marked resume parse as FAILED in DB for ca_record=%s",
                        ca_record_id,
                    )
        except Exception:
            logger.exception(
                "Failed to update resume_parse_status to FAILED for ca_record %s",
                ca_record_id,
            )

    finally:
        # 6. Delete local copy of the downloaded resume
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info("Deleted local resume file: %s", temp_file_path)
            except Exception:
                logger.exception(
                    "Failed to delete local resume file: %s", temp_file_path
                )


async def process_local_candidate_resume_in_background(
    ca_record_id: uuid.UUID,
    temp_file_path: str,
) -> None:
    """Parse local candidate resume using LlamaParse, extract structured data via Groq, and update CandidateAssessment."""
    import asyncio
    import os

    from fastapi.concurrency import run_in_threadpool
    from groq import AsyncGroq
    from llama_parse import LlamaParse
    from sqlalchemy import select

    from src.data.clients.postgres_client import get_session_factory

    logger.info(
        "Starting background resume parsing for ca_record=%s from local file=%s",
        ca_record_id,
        temp_file_path,
    )

    SessionLocal = await get_session_factory()

    try:
        # 1. Parse with LlamaParse
        api_key = settings.LLAMA_CLOUD_API_KEY
        if not api_key:
            raise ValueError("LLAMA_CLOUD_API_KEY is not configured in settings")

        parser = LlamaParse(api_key=api_key, result_type="markdown")
        extra_info = {"file_name": f"{ca_record_id}.pdf"}

        logger.info("Parsing resume using LlamaParse for ca_record=%s", ca_record_id)
        documents = await asyncio.wait_for(
            run_in_threadpool(parser.load_data, temp_file_path, extra_info=extra_info),
            timeout=60,
        )
        resume_text = "\n".join(doc.text for doc in documents)

        if not resume_text.strip():
            raise ValueError("Parsed resume text is empty")

        # 2. Analyze via Groq
        logger.info(
            "Analyzing parsed resume text via Groq for ca_record=%s", ca_record_id
        )
        groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        resume_parsed = await run_resume_analysis(resume_text, groq_client)

        # 3. Save to database
        async with SessionLocal() as db_session:
            ca_record = None
            for _attempt in range(5):
                statement = select(CandidateAssessment).where(
                    CandidateAssessment.id == ca_record_id
                )
                result = await db_session.execute(statement)
                ca_record = result.scalar_one_or_none()
                if ca_record:
                    break
                await asyncio.sleep(0.5)

            if ca_record:
                ca_record.resume_parsed = resume_parsed
                ca_record.resume_parse_status = "COMPLETED"
                await db_session.commit()
                logger.info(
                    "Resume parsed and saved successfully in DB for ca_record=%s",
                    ca_record_id,
                )
            else:
                logger.error(
                    "CandidateAssessment %s not found in database to update parsing results",
                    ca_record_id,
                )

    except Exception as exc:
        logger.exception(
            "Failed to parse and save resume for ca_record %s", ca_record_id
        )

        try:
            async with SessionLocal() as db_session:
                ca_record = None
                for _attempt in range(5):
                    statement = select(CandidateAssessment).where(
                        CandidateAssessment.id == ca_record_id
                    )
                    result = await db_session.execute(statement)
                    ca_record = result.scalar_one_or_none()
                    if ca_record:
                        break
                    await asyncio.sleep(0.5)

                if ca_record:
                    ca_record.resume_parse_status = "FAILED"
                    ca_record.resume_parsed = {
                        "error": str(exc),
                        "summary": "Failed to parse resume.",
                        "skills": [],
                        "experience_years": 0,
                    }
                    await db_session.commit()
                    logger.info(
                        "Marked resume parse as FAILED in DB for ca_record=%s",
                        ca_record_id,
                    )
        except Exception:
            logger.exception(
                "Failed to update resume_parse_status to FAILED for ca_record %s",
                ca_record_id,
            )

    finally:
        # 4. Delete local copy of the downloaded resume
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info("Deleted local resume file: %s", temp_file_path)
            except Exception:
                logger.exception(
                    "Failed to delete local resume file: %s", temp_file_path
                )


async def _dispatch_invitation_with_logging(
    ca_record_id: uuid.UUID,
    candidate_name: str,
    recipient_email: str,
    assessment_title: str,
    role_name: str,
    invitation_link: str,
    interview_duration_mins: int,
) -> None:
    """Send invitation email and create a notification log entry (best-effort)."""
    from src.data.clients.postgres_client import get_session_factory

    SessionLocal = await get_session_factory()
    async with SessionLocal() as session:
        notif_repo = NotificationLogRepository(session)
        try:
            await _send_invitation_email(
                candidate_name=candidate_name,
                recipient_email=recipient_email,
                assessment_title=assessment_title,
                role_name=role_name,
                invitation_link=invitation_link,
                interview_duration_mins=interview_duration_mins,
            )
            await notif_repo.create(
                candidate_assessment_id=ca_record_id,
                notification_type="INVITATION",
                recipient_email=recipient_email,
                delivery_status="SENT",
            )
            await session.commit()
            logger.info(
                "Invitation email sent and logged",
                extra={"candidate_assessment_id": str(ca_record_id)},
            )
        except Exception as exc:
            logger.exception(
                "Failed to send invitation email for candidate_assessment %s — %s: %s",
                ca_record_id,
                type(exc).__name__,
                exc,
            )
            try:
                await notif_repo.create(
                    candidate_assessment_id=ca_record_id,
                    notification_type="INVITATION",
                    recipient_email=recipient_email,
                    delivery_status="FAILED",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                await session.commit()
            except Exception as log_exc:
                logger.exception(
                    "Failed to log failed notification for candidate_assessment %s — %s",
                    ca_record_id,
                    log_exc,
                )
