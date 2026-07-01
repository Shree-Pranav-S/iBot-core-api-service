"""Unit tests for candidate enrollment and manual creation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import BadRequestException, ForbiddenException
from src.core.services.candidate_service import (
    CandidateService,
    _find_reusable_resume_enrollment,
)


def _assessment(
    *,
    assessment_id: uuid.UUID | None = None,
    recruiter_id: uuid.UUID | None = None,
    title: str = "Backend Developer",
    role_name: str = "Backend Engineer",
) -> Any:
    return SimpleNamespace(
        id=assessment_id or uuid.uuid4(),
        recruiter_id=recruiter_id or uuid.uuid4(),
        title=title,
        role_name=role_name,
        interview_duration_mins=45,
        window_start=datetime(2026, 7, 1, tzinfo=UTC),
        window_end=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _candidate(
    *,
    candidate_id: uuid.UUID | None = None,
    recruiter_id: uuid.UUID | None = None,
) -> Any:
    return SimpleNamespace(
        id=candidate_id or uuid.uuid4(),
        full_name="Jane Doe",
        email="jane@example.com",
        created_by=recruiter_id or uuid.uuid4(),
    )


def _enrollment(
    *,
    assessment: SimpleNamespace,
    resume_file_path: str = "resume.pdf",
    resume_parse_status: str = "PENDING",
    resume_parsed: dict | None = None,
    status: str = "COMPLETED",
) -> Any:
    return SimpleNamespace(
        assessment=assessment,
        resume_file_path=resume_file_path,
        resume_parse_status=resume_parse_status,
        resume_parsed=resume_parsed,
        status=status,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def _build_service() -> tuple[CandidateService, AsyncMock, AsyncMock, AsyncMock]:
    candidate_repo = AsyncMock()
    ca_repo = AsyncMock()
    assessment_repo = AsyncMock()
    event_logs_repo = AsyncMock()
    service = CandidateService(
        candidate_repo=candidate_repo,
        ca_repo=ca_repo,
        assessment_repo=assessment_repo,
        event_logs_repo=event_logs_repo,
    )
    ca_repo.register_after_commit_callback = MagicMock()
    return service, candidate_repo, ca_repo, assessment_repo


class TestFindReusableResumeEnrollment:
    def test_returns_most_recent_completed_parse(self) -> None:
        assessment = _assessment()
        older = _enrollment(
            assessment=assessment,
            resume_parse_status="COMPLETED",
            resume_parsed={"skills": ["Python"]},
        )
        newer = _enrollment(
            assessment=assessment,
            resume_parse_status="COMPLETED",
            resume_parsed={"skills": ["Go"]},
        )
        assert _find_reusable_resume_enrollment([newer, older]) is newer

    def test_skips_pending_enrollments(self) -> None:
        assessment = _assessment()
        pending = _enrollment(assessment=assessment, resume_parse_status="PENDING")
        completed = _enrollment(
            assessment=assessment,
            resume_parse_status="COMPLETED",
            resume_parsed={"skills": ["Rust"]},
        )
        assert _find_reusable_resume_enrollment([pending, completed]) is completed

    def test_returns_none_when_no_completed_parse(self) -> None:
        assessment = _assessment()
        pending = _enrollment(assessment=assessment, resume_parse_status="PENDING")
        assert _find_reusable_resume_enrollment([pending]) is None


@pytest.mark.asyncio
class TestEnrollExistingCandidate:
    async def test_reuses_completed_resume_when_no_upload(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment_a = _assessment(recruiter_id=recruiter_id, title="Role A")
        assessment_b = _assessment(
            recruiter_id=recruiter_id,
            title="Role A",
            role_name="Backend Engineer",
        )
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)
        parsed = {"skills": ["Python"], "summary": "Backend dev", "experience_years": 3}
        prior = _enrollment(
            assessment=assessment_a,
            resume_parse_status="COMPLETED",
            resume_parsed=parsed,
            resume_file_path="jane_resume.pdf",
        )
        created_ca = SimpleNamespace(id=uuid.uuid4(), invitation_token=uuid.uuid4())

        assessment_repo.get_by_id.return_value = assessment_b
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = None
        ca_repo.get_all_by_candidate_id.return_value = [prior]

        async def create_side_effect(**kwargs: object) -> SimpleNamespace:
            created_ca.resume_parse_status = kwargs["resume_parse_status"]
            created_ca.resume_parsed = kwargs["resume_parsed"]
            created_ca.resume_file_path = kwargs["resume_file_path"]
            created_ca.assessment_id = kwargs["assessment_id"]
            return created_ca

        ca_repo.create.side_effect = create_side_effect

        ca_record, returned_candidate = await service.enroll_existing_candidate(
            recruiter_id=recruiter_id,
            candidate_id=candidate_id,
            assessment_id=assessment_b.id,
            resume_file_bytes=None,
            resume_filename=None,
        )

        assert returned_candidate is candidate
        assert ca_record.assessment_id == assessment_b.id
        assert ca_record.resume_parse_status == "COMPLETED"
        assert ca_record.resume_parsed == parsed
        assert ca_record.resume_file_path == "jane_resume.pdf"
        ca_repo.create.assert_awaited_once()
        create_kwargs = ca_repo.create.await_args.kwargs
        assert create_kwargs["assessment_id"] == assessment_b.id
        assert create_kwargs["resume_parse_status"] == "COMPLETED"
        assert create_kwargs["resume_parsed"] == parsed

    async def test_new_resume_upload_stays_pending_and_triggers_parse(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)
        prior = _enrollment(
            assessment=assessment,
            resume_parse_status="COMPLETED",
            resume_parsed={"skills": ["Python"]},
        )
        created_ca = SimpleNamespace(id=uuid.uuid4(), invitation_token=uuid.uuid4())

        assessment_repo.get_by_id.return_value = assessment
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = None
        ca_repo.get_all_by_candidate_id.return_value = [prior]
        ca_repo.create.return_value = created_ca

        with (
            patch(
                "src.core.services.candidate_service.write_temporary_resume",
                new_callable=AsyncMock,
            ) as write_resume,
            patch(
                "src.core.services.candidate_service.enqueue_invitation_email",
            ),
        ):
            write_resume.return_value = "/tmp/resume.pdf"
            await service.enroll_existing_candidate(
                recruiter_id=recruiter_id,
                candidate_id=candidate_id,
                assessment_id=assessment.id,
                resume_file_bytes=b"%PDF-1.4",
                resume_filename="new_resume.pdf",
            )

        create_kwargs = ca_repo.create.await_args.kwargs
        assert create_kwargs["resume_parse_status"] == "PENDING"
        assert create_kwargs["resume_parsed"] is None
        assert create_kwargs["resume_file_path"] == "new_resume.pdf"
        write_resume.assert_awaited_once()
        assert ca_repo.register_after_commit_callback.call_count == 2

    async def test_no_prior_parse_stays_pending(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)
        created_ca = SimpleNamespace(id=uuid.uuid4(), invitation_token=uuid.uuid4())

        assessment_repo.get_by_id.return_value = assessment
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = None
        ca_repo.get_all_by_candidate_id.return_value = []
        ca_repo.create.return_value = created_ca

        with patch("src.core.services.candidate_service.enqueue_invitation_email"):
            await service.enroll_existing_candidate(
                recruiter_id=recruiter_id,
                candidate_id=candidate_id,
                assessment_id=assessment.id,
                resume_file_bytes=None,
                resume_filename=None,
            )

        create_kwargs = ca_repo.create.await_args.kwargs
        assert create_kwargs["resume_parse_status"] == "PENDING"
        assert create_kwargs["resume_parsed"] is None
        assert create_kwargs["resume_file_path"] == "placeholder_resume.pdf"

    async def test_duplicate_enrollment_raises(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)

        assessment_repo.get_by_id.return_value = assessment
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = SimpleNamespace()

        with pytest.raises(BadRequestException, match="already registered"):
            await service.enroll_existing_candidate(
                recruiter_id=recruiter_id,
                candidate_id=candidate_id,
                assessment_id=assessment.id,
                resume_file_bytes=None,
                resume_filename=None,
            )

    async def test_forbidden_when_candidate_not_known_to_recruiter(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        other_recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        candidate = _candidate(
            candidate_id=candidate_id, recruiter_id=other_recruiter_id
        )

        assessment_repo.get_by_id.return_value = assessment
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = None
        ca_repo.get_all_by_candidate_id.return_value = []

        with pytest.raises(ForbiddenException, match="permission"):
            await service.enroll_existing_candidate(
                recruiter_id=recruiter_id,
                candidate_id=candidate_id,
                assessment_id=assessment.id,
                resume_file_bytes=None,
                resume_filename=None,
            )

    async def test_enrolls_to_correct_assessment_when_titles_match(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        assessment_a = _assessment(
            recruiter_id=recruiter_id,
            title="Backend Developer",
            role_name="Backend Engineer",
        )
        assessment_b = _assessment(
            recruiter_id=recruiter_id,
            title="Backend Developer",
            role_name="Backend Engineer",
        )
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)
        prior = _enrollment(
            assessment=assessment_a,
            resume_parse_status="COMPLETED",
            resume_parsed={"skills": ["Java"]},
        )
        created_ca = SimpleNamespace(id=uuid.uuid4(), invitation_token=uuid.uuid4())

        assessment_repo.get_by_id.return_value = assessment_b
        candidate_repo.get_by_id.return_value = candidate
        ca_repo.get_by_candidate_and_assessment.return_value = None
        ca_repo.get_all_by_candidate_id.return_value = [prior]
        ca_repo.create.return_value = created_ca

        with patch("src.core.services.candidate_service.enqueue_invitation_email"):
            await service.enroll_existing_candidate(
                recruiter_id=recruiter_id,
                candidate_id=candidate_id,
                assessment_id=assessment_b.id,
                resume_file_bytes=None,
                resume_filename=None,
            )

        assert ca_repo.create.await_args.kwargs["assessment_id"] == assessment_b.id
        assert assessment_repo.get_by_id.await_args.args[0] == assessment_b.id


@pytest.mark.asyncio
class TestCreateSingleCandidate:
    async def test_duplicate_email_raises(self) -> None:
        service, candidate_repo, ca_repo, assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)

        assessment_repo.get_by_id.return_value = assessment
        candidate_repo.get_by_email.return_value = _candidate(recruiter_id=recruiter_id)

        with pytest.raises(BadRequestException, match="already exists"):
            await service.create_single_candidate(
                recruiter_id=recruiter_id,
                name="Jane Doe",
                email="jane@example.com",
                assessment_id=assessment.id,
                resume_file_bytes=b"%PDF",
                resume_filename="resume.pdf",
            )

        ca_repo.create.assert_not_awaited()


@pytest.mark.asyncio
class TestDeleteCandidateFromAssessment:
    async def test_deletes_orphan_candidate_when_last_enrollment_removed(self) -> None:
        service, candidate_repo, ca_repo, _assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        ca_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        candidate = _candidate(candidate_id=candidate_id, recruiter_id=recruiter_id)
        ca_record = SimpleNamespace(
            id=ca_id,
            candidate_id=candidate_id,
            assessment=assessment,
        )

        ca_repo.get_by_id.return_value = ca_record
        ca_repo.get_all_by_candidate_id.return_value = []
        candidate_repo.get_by_id.return_value = candidate

        await service.delete_candidate_from_assessment(ca_id, recruiter_id)

        ca_repo.delete.assert_awaited_once_with(ca_record)
        candidate_repo.delete_candidate.assert_awaited_once_with(candidate)

    async def test_keeps_candidate_when_other_enrollments_remain(self) -> None:
        service, candidate_repo, ca_repo, _assessment_repo = _build_service()
        recruiter_id = uuid.uuid4()
        candidate_id = uuid.uuid4()
        ca_id = uuid.uuid4()
        assessment = _assessment(recruiter_id=recruiter_id)
        other_assessment = _assessment(recruiter_id=recruiter_id)
        ca_record = SimpleNamespace(
            id=ca_id,
            candidate_id=candidate_id,
            assessment=assessment,
        )
        remaining = _enrollment(assessment=other_assessment)

        ca_repo.get_by_id.return_value = ca_record
        ca_repo.get_all_by_candidate_id.return_value = [remaining]

        await service.delete_candidate_from_assessment(ca_id, recruiter_id)

        ca_repo.delete.assert_awaited_once_with(ca_record)
        candidate_repo.delete_candidate.assert_not_awaited()
