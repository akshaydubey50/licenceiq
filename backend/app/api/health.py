"""Public liveness endpoint for local development and deployment checks."""

from fastapi import APIRouter

from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report API liveness without requiring storage or an external AI service."""
    return HealthResponse()
