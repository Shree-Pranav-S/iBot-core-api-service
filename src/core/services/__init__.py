"""Service package exports.

Use lazy attribute loading to avoid import-time circular dependencies.
"""

from importlib import import_module
from typing import Any

__all__ = ["AuthService", "AssessmentService", "CandidateService", "EvaluationService"]

_SERVICE_MODULES: dict[str, str] = {
    "AuthService": "src.core.services.auth_service",
    "AssessmentService": "src.core.services.assessment_service",
    "CandidateService": "src.core.services.candidate_service",
    "EvaluationService": "src.core.services.evaluation_service",
}


def __getattr__(name: str) -> Any:
    """Load service classes on demand to prevent circular imports."""
    if name not in _SERVICE_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_SERVICE_MODULES[name])
    return getattr(module, name)
