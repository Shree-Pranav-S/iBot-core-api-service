"""
Schemas package.

Single import surface for all Pydantic schemas used in core-api.
"""

from src.schemas.assessment import (
    AssessmentCreateRequest,
    AssessmentResponse,
    AssessmentSummaryResponse,
    AssessmentUpdateStatusRequest,
    FocusAreaOverride,
    InterviewPlan,
    InterviewSection,
    JDAnalysis,
    JDAnalysisAndInterviewPlan,
    SkillPriority,
)
from src.schemas.auth import (
    LoginRequest,
    RecruiterRegisterRequest,
    RecruiterResponse,
    TokenResponse,
)
from src.schemas.candidate import (
    AIRejectionFeedbackResponse,
    BulkUploadResponse,
    CandidateAssessmentListItem,
    CSVRowResult,
    EnrollCandidateResponse,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    SingleCandidateResponse,
    TokenValidationResponse,
)
from src.schemas.common import (
    APIResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
)
from src.schemas.event_log import (
    EventLogCreate,
    EventName,
    EventSource,
)
from src.schemas.notification import (
    RecruiterDashboardNotification,
)

__all__ = [
    # auth
    "RecruiterRegisterRequest",
    "LoginRequest",
    "RecruiterResponse",
    "TokenResponse",
    # assessment
    "AssessmentCreateRequest",
    "AssessmentUpdateStatusRequest",
    "AssessmentResponse",
    "AssessmentSummaryResponse",
    "SkillPriority",
    "JDAnalysis",
    "JDAnalysisAndInterviewPlan",
    "InterviewSection",
    "InterviewPlan",
    "FocusAreaOverride",
    # candidate
    "AIRejectionFeedbackResponse",
    "BulkUploadResponse",
    "CSVRowResult",
    "CandidateAssessmentListItem",
    "CSVRowResult",
    "EnrollCandidateResponse",
    "RecruiterDecisionRequest",
    "RecruiterDecisionResponse",
    "SingleCandidateResponse",
    "TokenValidationResponse",
    # notification
    "RecruiterDashboardNotification",
    # event logs
    "EventLogCreate",
    "EventName",
    "EventSource",
    # common
    "APIResponse",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
]
