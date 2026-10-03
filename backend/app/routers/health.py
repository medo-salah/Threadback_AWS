"""
Health check router.

Exposes GET /health — a lightweight liveness probe with no external dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response schema for GET /health."""

    status: str
    app: str
    version: str
    environment: str
    timestamp: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Returns the application health status. "
        "This endpoint has no external dependencies and always returns HTTP 200 "
        "when the backend process is running."
    ),
)
def health_check() -> HealthResponse:
    """
    Liveness probe.

    - No database dependency
    - No LLM dependency
    - No external API dependency
    - Deterministic response (timestamp varies, all other fields are constant)
    """
    return HealthResponse(
        status="healthy",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
