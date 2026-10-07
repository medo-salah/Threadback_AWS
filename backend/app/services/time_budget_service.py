"""
Time-Budget Planning Service for Threadback (M15).

Deterministic recommendation engine for questions like:
  "I have 30 minutes. What can I realistically finish?"
  "I have two hours."

Matches actionable intent next actions to available time windows conservatively.
Never fabricates duration knowledge when unknown; provides explicit bounds and estimates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.domain.enums import NextActionType, Priority, ThreadStatus
from app.domain.models import IntentThread, TimeBudgetRecommendation
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME
from app.services.attention_engine import AttentionEngine
from app.services.next_action_service import NextActionService

logger = logging.getLogger(__name__)

# Heuristic conservative duration bands (minutes) for structured action types
# when explicit duration metadata is not present on the commitment.
ESTIMATED_DURATION_MINUTES: dict[NextActionType, int] = {
    NextActionType.FOLLOW_UP_ACTION: 15,  # Send check-in email / message
    NextActionType.DIRECT_NEXT_ACTION: 30,  # Complete single open task step
    NextActionType.UNBLOCKER_ACTION: 45,  # Contact blocker party or review unblocking document
    NextActionType.GATHER_EVIDENCE_ACTION: 30,  # Collect missing documentation
    NextActionType.EVOLVE_INTENTION: 20,  # Goal alignment discussion / update
    NextActionType.DEFER_INTENTION: 10,  # Set deferral parameters
    NextActionType.RESUME_INTENTION: 15,  # Review history and un-defer
    NextActionType.ABANDON_INTENTION: 10,  # Record rationale and cancel commitments
    NextActionType.NO_ACTION: 5,
}


class TimeBudgetService:
    """
    Deterministic planning service matching tasks to user time availability.
    """

    def __init__(
        self,
        next_action_service: NextActionService | None = None,
        attention_engine: AttentionEngine | None = None,
    ) -> None:
        self._next_action_service = next_action_service or NextActionService()
        self._attention_engine = attention_engine or AttentionEngine()

    def recommend(
        self,
        threads: list[IntentThread],
        available_minutes: int,
        reference_time: datetime | None = None,
    ) -> TimeBudgetRecommendation:
        """
        Evaluate threads and recommend the best task fitting the time budget.

        Prioritizes:
          1. Actionable threads (not blocked, not deferred)
          2. High AttentionScore
          3. Tasks that realistically fit the requested available minutes
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Exclude completed/abandoned threads
        active_threads = [
            t
            for t in threads
            if t.status
            in (
                ThreadStatus.ACTIVE,
                ThreadStatus.WAITING,
                ThreadStatus.BLOCKED,
                ThreadStatus.DISCOVERED,
            )
        ]

        if not active_threads:
            return TimeBudgetRecommendation(
                available_minutes=available_minutes,
                selected_thread_id="none",
                selected_thread_title="No Active Intentions",
                reason="You have no active unfinished intentions requiring work.",
                expected_next_action="Review long-term goals or discover new commitments.",
                fits_budget=True,
                is_blocked=False,
                estimated_duration_minutes=0,
                confidence=1.0,
            )

        # Score attention across active threads
        candidates = self._attention_engine.evaluate_threads(
            active_threads, reference_time=ref_time
        )
        candidate_map = {c.thread_id: c for c in candidates}

        # Build evaluated task proposals
        scored_tasks: list[dict] = []

        for thread in active_threads:
            cand = candidate_map.get(thread.id)
            att_score = cand.attention_score if cand else 0.0

            action_sug = self._next_action_service.suggest_action(thread)
            act_type = action_sug.action_type
            est_minutes = ESTIMATED_DURATION_MINUTES.get(act_type, 30)

            is_blocked = bool(thread.active_blockers)
            fits_budget = est_minutes <= available_minutes

            # Scoring weight:
            # - Heavily reward unblocked tasks (+0.50)
            # - Reward fitting the budget (+0.40)
            # - Incorporate attention score (+0.30)
            # - High priority (+0.20)
            suitability_score = 0.0
            if not is_blocked:
                suitability_score += 0.50
            if fits_budget:
                suitability_score += 0.40
            suitability_score += 0.30 * att_score
            if thread.priority == Priority.HIGH:
                suitability_score += 0.20

            scored_tasks.append(
                {
                    "thread": thread,
                    "action": action_sug,
                    "est_minutes": est_minutes,
                    "fits_budget": fits_budget,
                    "is_blocked": is_blocked,
                    "suitability_score": suitability_score,
                    "att_score": att_score,
                }
            )

        # Sort by suitability descending
        scored_tasks.sort(key=lambda x: x["suitability_score"], reverse=True)
        top = scored_tasks[0]
        top_thread: IntentThread = top["thread"]
        top_action = top["action"]
        top_est = top["est_minutes"]
        top_fits = top["fits_budget"]
        top_blocked = top["is_blocked"]

        # Formulate grounded rationale
        if top_fits and not top_blocked:
            reason = (
                f"Selected '{top_thread.title}' because it has high attention ({top['att_score'] * 100:.0f}%), "
                f"is completely unblocked, and its next step estimated at ~{top_est}m comfortably fits your {available_minutes}m budget."
            )
        elif top_fits and top_blocked:
            reason = (
                f"Selected '{top_thread.title}' because addressing its active blocker ({top_action.action}) "
                f"estimated at ~{top_est}m is the most impactful step fitting your {available_minutes}m budget."
            )
        else:
            reason = (
                f"Selected '{top_thread.title}' as your top priority. Note that its estimated duration (~{top_est}m) "
                f"may exceed your {available_minutes}m budget; consider making partial progress on: {top_action.action}."
            )

        return TimeBudgetRecommendation(
            available_minutes=available_minutes,
            selected_thread_id=top_thread.id,
            selected_thread_title=top_thread.title,
            reason=reason,
            expected_next_action=top_action.action,
            fits_budget=top_fits,
            is_blocked=top_blocked,
            estimated_duration_minutes=top_est,
            confidence=0.85,
        )
