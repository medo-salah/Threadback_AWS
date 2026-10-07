"""
REST API Router for Threadback Intent Copilot (M15).

Provides deterministic decision endpoints for:
  - Ranked prioritization (Urgency vs Attention)
  - Read-only what-if simulations (counterfactual consequences)
  - Time-budget task planning (e.g. 15m, 30m, 60m, 120m)
  - Safe closure assistance (verification criteria audit)
  - Structured Intent Decision Cards for dashboard display
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.domain.models import (
    IntentCopilotOverview,
    IntentDecisionCard,
    PrioritizedThreadSummary,
    SafeClosureCandidate,
    TimeBudgetRecommendation,
    WhatIfSimulationResult,
)
from app.mcp.server import (
    intent_copilot_service,
    safe_closure_assistant,
    thread_service,
    time_budget_service,
    what_if_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class WhatIfRequest(BaseModel):
    """Payload for read-only counterfactual what-if simulation."""

    thread_id: str = Field(..., description="Target thread ID to simulate")
    scenario: str = Field(
        ...,
        description="Scenario: IGNORE_TEMPORARILY, POSTPONE, RESOLVE_BLOCKER, CHANGE_GOAL",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Scenario parameters (e.g. {'days': 7})"
    )


@router.get("/overview", response_model=IntentCopilotOverview)
async def get_copilot_overview(
    conversation_id: str | None = Query(
        None, description="Optional conversation session ID for checkpoint anchor"
    ),
) -> IntentCopilotOverview:
    """
    Retrieve comprehensive Intent Copilot synthesis across all user intentions.
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return intent_copilot_service.generate_overview(
        threads=threads,
        conversation_id=conversation_id,
    )


@router.get("/priorities", response_model=list[PrioritizedThreadSummary])
async def get_ranked_priorities() -> list[PrioritizedThreadSummary]:
    """
    Retrieve ranked shortlist answering 'What should I do first?'
    clearly distinguishing Urgency (execution pressure) from Attention (cognitive salience).
    """
    threads = thread_service.list_threads(unfinished_only=True)
    return intent_copilot_service.prioritize_threads(threads)


@router.post("/what-if", response_model=WhatIfSimulationResult)
async def simulate_what_if(req: WhatIfRequest) -> WhatIfSimulationResult:
    """
    Execute a read-only deterministic scenario simulation on a thread clone.
    Strictly preserves: SIMULATION — NO STATE CHANGED.
    """
    thread = thread_service.get_thread(req.thread_id)
    if thread is None:
        raise HTTPException(
            status_code=404, detail=f"Thread '{req.thread_id}' not found"
        )

    all_threads = thread_service.list_threads(unfinished_only=False)
    return what_if_service.simulate(
        thread=thread,
        scenario=req.scenario,
        parameters=req.parameters,
        all_threads=all_threads,
    )


@router.get("/time-budget", response_model=TimeBudgetRecommendation)
async def get_time_budget_plan(
    available_minutes: int = Query(
        30, ge=5, le=480, description="Available minutes for work session"
    ),
) -> TimeBudgetRecommendation:
    """
    Recommend the best actionable task fitting the requested time budget conservatively.
    """
    threads = thread_service.list_threads(unfinished_only=True)
    return time_budget_service.recommend(
        threads=threads,
        available_minutes=available_minutes,
    )


@router.get("/safe-closure", response_model=list[SafeClosureCandidate])
async def get_safe_closure_candidates() -> list[SafeClosureCandidate]:
    """
    Evaluate threads for safe closure readiness based on verification criteria and active blockers.
    Does not close threads automatically.
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return safe_closure_assistant.evaluate_threads(threads)


@router.get("/decision-cards", response_model=list[IntentDecisionCard])
async def get_decision_cards(
    conversation_id: str | None = Query(
        None, description="Optional conversation session ID"
    ),
) -> list[IntentDecisionCard]:
    """
    Retrieve structured conversational decision cards (TOP_PRIORITY, WHY_NOW, WHAT_CHANGED, RESUME, etc.).
    """
    threads = thread_service.list_threads(unfinished_only=False)
    return intent_copilot_service.generate_decision_cards(
        threads=threads,
        conversation_id=conversation_id,
    )
