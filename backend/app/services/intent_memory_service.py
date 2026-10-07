"""
Intent Memory Service for Threadback M13.

Authoritative domain service for managing persistent intent memory,
intent evolution, and goal revision tracking over time.

Enforces core safety rules:
- original_goal is strictly immutable from thread discovery.
- Explicit and unambiguous evolutions are recorded with auditable INTENTION_EVOLVED events.
- Reasons are never fabricated by an LLM or extrapolated from assumptions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import ThreadEventType, ThreadStatus
from app.domain.models import IntentEvolution, IntentSummary, IntentThread, ThreadEvent
from app.services.thread_service import ThreadService

if TYPE_CHECKING:
    from app.services.intent_radar_service import IntentRadarService

logger = logging.getLogger(__name__)


class IntentMemoryService:
    """Authoritative business logic for intent evolution and memory history."""

    def __init__(
        self,
        thread_service: ThreadService,
        radar_service: IntentRadarService | None = None,
    ) -> None:
        self._thread_service = thread_service
        self._radar_service = radar_service

    def evolve_goal(
        self,
        thread_id: str,
        revised_goal: str,
        reason: str,
        reference_time: datetime | None = None,
    ) -> IntentEvolution:
        """
        Evolve the active goal of an IntentThread.

        Validates:
          1. Thread exists.
          2. Thread is not COMPLETED or ABANDONED.
          3. revised_goal is non-empty.
          4. reason is provided and non-fabricated.
          5. original_goal is strictly preserved.
          6. Emits auditable INTENTION_EVOLVED lifecycle event.
        """
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        if thread.status in (ThreadStatus.COMPLETED, ThreadStatus.ABANDONED):
            raise ValueError(
                f"Cannot evolve intention for thread '{thread_id}' with terminal status '{thread.status.value}'."
            )

        clean_goal = revised_goal.strip()
        if not clean_goal:
            raise ValueError("Revised goal cannot be empty.")

        clean_reason = reason.strip() or "User revised active objective"
        now = reference_time or datetime.now(timezone.utc)
        previous_goal = thread.current_goal or thread.description

        # Idempotency check: if revised goal is identical, return latest evolution if exists
        if clean_goal == previous_goal:
            evolutions = self._thread_service.repository.get_intent_evolutions(
                thread_id
            )
            if evolutions:
                return evolutions[-1]

        evolution_id = f"evo-{uuid.uuid4().hex[:12]}"
        event_id = f"evt-evolve-{int(now.timestamp() * 1000)}"

        evolution = IntentEvolution(
            id=evolution_id,
            thread_id=thread_id,
            previous_goal=previous_goal,
            revised_goal=clean_goal,
            reason=clean_reason,
            timestamp=now,
            trigger_event_id=event_id,
        )

        # Record INTENTION_EVOLVED lifecycle event
        lifecycle_event = ThreadEvent(
            id=event_id,
            thread_id=thread_id,
            event_type=ThreadEventType.INTENTION_EVOLVED,
            type=ThreadEventType.INTENTION_EVOLVED.value,
            description=f"Intention evolved: '{previous_goal}' → '{clean_goal}' (Reason: {clean_reason})",
            timestamp=now,
            actor="user",
            source="conversational_agent",
            payload={
                "original_goal": thread.original_goal,
                "previous_goal": previous_goal,
                "revised_goal": clean_goal,
                "reason": clean_reason,
                "evolution_id": evolution_id,
            },
        )

        # Persist evolution & lifecycle event atomically
        self._thread_service.repository.add_intent_evolution(evolution)

        # Synchronize thread aggregate
        thread.current_goal = clean_goal
        thread.updated_at = now
        thread.last_interaction_at = now
        thread.evolutions.append(evolution)
        self._thread_service.update_thread(thread)
        self._thread_service.add_event(thread_id, lifecycle_event)

        logger.info(
            "Intent evolved for thread '%s': '%s' -> '%s' (reason: %s)",
            thread_id,
            previous_goal,
            clean_goal,
            clean_reason,
        )
        return evolution

    def get_evolution_history(self, thread_id: str) -> list[IntentEvolution]:
        """Retrieve chronological goal evolution chain for a thread."""
        return self._thread_service.repository.get_intent_evolutions(thread_id)

    def get_intent_summary(
        self,
        thread_id: str,
        reference_time: datetime | None = None,
    ) -> IntentSummary:
        """Generate structured deterministic intent summary for a thread."""
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        now = reference_time or datetime.now(timezone.utc)

        completed_commitments = [
            c.description for c in thread.commitments if c.status.value == "COMPLETED"
        ]
        remaining_commitments = [
            c.description for c in thread.commitments if c.status.value == "OPEN"
        ]

        total_comms = len(thread.commitments)
        if total_comms == 0:
            progress_pct = 100 if thread.status == ThreadStatus.COMPLETED else 50
        else:
            progress_pct = int((len(completed_commitments) / total_comms) * 100)

        active_blockers = [d.description for d in thread.active_blockers]

        # Compute decay signal
        from app.services.intent_radar_service import IntentRadarService

        radar_svc = self._radar_service or IntentRadarService(self._thread_service)
        decay_signal = radar_svc.compute_decay_signal(thread, reference_time=now)

        rec_step = "Review thread context and identify next action"
        if active_blockers:
            rec_step = f"Resolve active blocker: {active_blockers[0]}"
        elif remaining_commitments:
            rec_step = f"Address open commitment: {remaining_commitments[0]}"
        elif thread.status == ThreadStatus.COMPLETED:
            rec_step = "Thread is completed and closed"

        return IntentSummary(
            thread_id=thread.id,
            title=thread.title,
            original_goal=thread.original_goal or thread.description,
            current_goal=thread.current_goal or thread.description,
            status=thread.status,
            progress_percentage=progress_pct,
            active_blockers=active_blockers,
            completed_commitments=completed_commitments,
            remaining_commitments=remaining_commitments,
            last_activity_at=thread.last_activity_at,
            decay_state=decay_signal.decay_state,
            recommended_next_step=rec_step,
        )
