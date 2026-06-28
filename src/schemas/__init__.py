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
    TokenPayload,
    TokenResponse,
)
from src.schemas.candidate import (
    BulkUploadResponse,
    CandidateAssessmentListItem,
    CandidateAssessmentResponse,
    CandidateResponse,
    CandidateTokenValidationResponse,
    CSVRowResult,
    RecruiterDecisionRequest,
    RecruiterDecisionResponse,
    TokenValidationResponse,
)
from src.schemas.common import (
    APIResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
)
from src.schemas.event_log import (
    EventLogCreate,
    EventLogResponse,
    EventName,
    EventSource,
)
from src.schemas.notification import (
    NotificationLogResponse,
    RecruiterDashboardNotification,
    SendInvitationPayload,
    SendOutcomePayload,
    SendReminderPayload,
)

__all__ = [
    # auth
    "RecruiterRegisterRequest",
    "LoginRequest",
    "RecruiterResponse",
    "TokenResponse",
    "TokenPayload",
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
    "CandidateResponse",
    "BulkUploadResponse",
    "CSVRowResult",
    "CandidateAssessmentListItem",
    "CandidateAssessmentResponse",
    "RecruiterDecisionRequest",
    "RecruiterDecisionResponse",
    "TokenValidationResponse",
    "CandidateTokenValidationResponse",
    # notification
    "NotificationLogResponse",
    "RecruiterDashboardNotification",
    "SendInvitationPayload",
    "SendReminderPayload",
    "SendOutcomePayload",
    # event logs
    "EventLogCreate",
    "EventLogResponse",
    "EventName",
    "EventSource",
    # common
    "APIResponse",
    "PaginatedResponse",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
]
