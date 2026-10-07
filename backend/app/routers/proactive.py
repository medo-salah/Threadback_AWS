"""
FastAPI router for Threadback Proactive Intent Intelligence (M14).

Exposes deterministic read-only endpoints:
  - GET /api/proactive/briefing
  - GET /api/proactive/attention
  - GET /api/proactive/conflicts
  - GET /api/proactive/resumable
  - GET /api/proactive/health

All routes delegate purely to domain services — zero business logic duplication.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.domain.enums import ThreadStatus
from app.domain.models import (
    AttentionCandidate,
    AttentionDelta,
    IntentConflict,
    IntentHealthSummary,
    ProactiveBriefing,
    ResumableCandidate,
)
from app.mcp.server import attention_engine, thread_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


@router.get("/briefing", response_model=ProactiveBriefing)
async def get_proactive_briefing(
    conversation_id: str | None = Query(
        None, description="Optional conversation session ID for checkpoint anchor"
    ),
) -> ProactiveBriefing:
    """
    Retrieve deterministic executive proactive briefing prioritizing attention,
    significant changes, blockers, resumables, and conflicts.
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return attention_engine.generate_briefing(
        threads=threads,
        conversation_id=conversation_id,
    )


@router.get("/attention", response_model=list[AttentionCandidate])
async def get_attention_candidates() -> list[AttentionCandidate]:
    """
    Retrieve all active intent threads evaluated and ranked by deterministic AttentionScore.
    """
    threads = thread_service.list_threads(unfinished_only=True)
    return attention_engine.evaluate_threads(threads)


@router.get("/conflicts", response_model=list[IntentConflict])
async def get_cross_thread_conflicts() -> list[IntentConflict]:
    """
    Retrieve conservative, structured cross-thread conflicts.
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return attention_engine.detect_cross_thread_conflicts(threads)


@router.get("/resumable", response_model=list[ResumableCandidate])
async def get_resumable_intentions() -> list[ResumableCandidate]:
    """
    Retrieve resume eligibility evaluations for all deferred intent threads.
    """
    threads = thread_service.list_threads(
        status=ThreadStatus.DEFERRED, unfinished_only=False
    )
    return [attention_engine.evaluate_thread_resume(t) for t in threads]


@router.get("/health", response_model=IntentHealthSummary)
async def get_intent_health_summary() -> IntentHealthSummary:
    """
    Retrieve aggregate deterministic health metrics across user intentions.
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return attention_engine.generate_health_summary(threads)


@router.get("/changes/{thread_id}", response_model=AttentionDelta)
async def get_thread_changes(
    thread_id: str,
    conversation_id: str | None = Query(
        None, description="Optional conversation session ID"
    ),
) -> AttentionDelta:
    """
    Retrieve factual differential state changes for a specific thread since the 4-tier anchor.
    """
    thread = thread_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")
    return attention_engine.analyze_thread_changes(
        thread=thread,
        conversation_id=conversation_id,
    )
