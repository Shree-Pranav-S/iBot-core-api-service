import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.future import select

from src.data.clients.postgres_client import get_session_factory
from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.candidate import Candidate
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.recruiter import Recruiter


async def seed():
    session_factory = await get_session_factory()

    async with session_factory() as session:
        # 1. Create or get test recruiter
        recruiter_email = "test_recruiter@example.com"
        stmt = select(Recruiter).where(Recruiter.email == recruiter_email)
        result = await session.execute(stmt)
        recruiter = result.scalar_one_or_none()

        if not recruiter:
            print("Creating test recruiter...")
            recruiter = Recruiter(
                id=uuid.uuid4(),
                full_name="Test Recruiter",
                email=recruiter_email,
                hashed_password="not_needed_for_internal_testing",
                company_name="Test Company",
                is_active=True,
            )
            session.add(recruiter)
            await session.flush()
        else:
            print(f"Found existing test recruiter: {recruiter.id}")

        # 2. Create test assessment
        print("Creating test assessment...")
        assessment = Assessment(
            id=uuid.uuid4(),
            recruiter_id=recruiter.id,
            title="Software Engineer Assessment",
            role_name="Software Engineer",
            jd_text="Looking for a Python Backend developer with FastAPI experience.",
            jd_file_path=None,
            jd_analysis={"skills": ["Python", "FastAPI"]},
            focus_areas={"coding": 5},
            interview_plan={"steps": ["introduction", "coding"]},
            interview_duration_mins=30,
            window_start=datetime.now(UTC),
            window_end=datetime.now(UTC) + timedelta(days=7),
            status="ACTIVE",
        )
        session.add(assessment)
        await session.flush()

        # 3. Create test candidate
        candidate_email = f"candidate_{uuid.uuid4().hex[:6]}@example.com"
        print(f"Creating test candidate ({candidate_email})...")
        candidate = Candidate(
            id=uuid.uuid4(),
            full_name="John Doe",
            email=candidate_email,
            created_by=recruiter.id,
        )
        session.add(candidate)
        await session.flush()

        # 4. Link candidate and assessment via CandidateAssessment
        token_uuid = uuid.uuid4()
        print(f"Creating candidate assessment invitation link with token: {token_uuid}")
        candidate_assessment = CandidateAssessment(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            assessment_id=assessment.id,
            resume_file_path="resumes/test_john_doe.pdf",
            resume_parse_status="COMPLETED",
            invitation_token=token_uuid,
            status="INVITED",
        )
        session.add(candidate_assessment)
        await session.commit()

        print("\n" + "=" * 50)
        print("SEEDING COMPLETE!")
        print("=" * 50)
        print(f"Candidate ID:  {candidate.id}")
        print(f"Assessment ID: {assessment.id}")
        print(f"Invitation Token (UUID): {token_uuid}")
        print("\nTest WebSocket connection URL via API Gateway:")
        print(f"ws://localhost:8002/ws/interview?token={token_uuid}")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
