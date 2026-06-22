"""
Models package.

Import all models here so that:
  1. Alembic's env.py only needs to import this one module to discover
     every table in Base.metadata.
  2. Application code can do:
       from src.data.models.postgres import Recruiter, Assessment, ...
"""

from src.data.models.postgres.assessment import Assessment
from src.data.models.postgres.audit_log import AuditLog
from src.data.models.postgres.base import Base
from src.data.models.postgres.candidate import Candidate
from src.data.models.postgres.candidate_assessment import CandidateAssessment
from src.data.models.postgres.csv_upload_log import CSVUploadLog
from src.data.models.postgres.interview_evaluation import InterviewEvaluation
from src.data.models.postgres.interview_session import InterviewSession
from src.data.models.postgres.mixins import TimestampMixin
from src.data.models.postgres.notification_log import NotificationLog
from src.data.models.postgres.recruiter import Recruiter
from src.data.models.postgres.recruiter_token import RecruiterToken

__all__ = [
    "Base",
    "TimestampMixin",
    "Recruiter",
    "RecruiterToken",
    "Candidate",
    "Assessment",
    "CandidateAssessment",
    "CSVUploadLog",
    "NotificationLog",
    "AuditLog",
    "InterviewSession",
    "InterviewEvaluation",
]
