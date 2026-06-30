"""Internal service authentication for microservice-to-microservice calls."""

from fastapi import Header, HTTPException, status

INTERVIEW_ENGINE_SERVICE = "interview-engine"


async def require_interview_engine_service(
    x_internal_service: str = Header(..., alias="X-Internal-Service"),
) -> None:
    """Allow only interview-engine-service to call interview persistence APIs."""
    if x_internal_service != INTERVIEW_ENGINE_SERVICE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden internal service caller.",
        )
