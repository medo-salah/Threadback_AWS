"""
Action execution abstraction and simulated executor for Threadback (M7).

Provides the ActionExecutor base class and SimulatedActionExecutor implementation.
M7 operates exclusively in SIMULATED mode.
No external network requests, emails, calls, messages, or real-world side effects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.enums import ExecutionMode, ExecutionStatus, NextActionType
from app.domain.models import Event, ExecutionResult
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.domain.models import ActionProposal, IntentThread

# Human-readable simulation success messages by action category
SIMULATION_MESSAGES: dict[NextActionType, str] = {
    NextActionType.DIRECT_NEXT_ACTION: "The direct next action was simulated successfully.",
    NextActionType.UNBLOCKER_ACTION: "The unblocker action was simulated successfully.",
    NextActionType.FOLLOW_UP_ACTION: "The follow-up action was simulated successfully.",
    NextActionType.GATHER_EVIDENCE_ACTION: "The evidence-gathering action was simulated successfully.",
}


class ActionExecutor(ABC):
    """Abstract base class for action executors."""

    @abstractmethod
    def execute(
        self,
        proposal: ActionProposal,
        thread: IntentThread,
        execution_mode: ExecutionMode = ExecutionMode.SIMULATED,
        reference_time: datetime | None = None,
    ) -> tuple[ExecutionResult, Event]:
        """Execute a validated action proposal against a thread.

        Returns a tuple of (ExecutionResult, Event) to record on the thread.
        """
        ...


class SimulatedActionExecutor(ActionExecutor):
    """Controlled simulated action executor (M7).

    Simulates execution of action proposals entirely in-memory without
    invoking external APIs, sending messages, mutating real-world systems,
    or claiming real-world delivery.
    """

    def execute(
        self,
        proposal: ActionProposal,
        thread: IntentThread,
        execution_mode: ExecutionMode = ExecutionMode.SIMULATED,
        reference_time: datetime | None = None,
    ) -> tuple[ExecutionResult, Event]:
        """Simulate execution of an ActionProposal and produce an audit Event.

        Args:
            proposal: The validated ActionProposal to simulate.
            thread: The IntentThread associated with the proposal.
            execution_mode: Must be ExecutionMode.SIMULATED in M7.
            reference_time: Deterministic timestamp anchor.

        Returns:
            Tuple of (ExecutionResult, Event).
        """
        ref_time = (
            reference_time or proposal.created_at or DEFAULT_ANALYSIS_REFERENCE_TIME
        )

        # Derive deterministic event ID
        event_suffix = proposal.id.replace("proposal-", "")
        event_id = f"evt-exec-{event_suffix}"

        # Standard simulation message
        message = SIMULATION_MESSAGES.get(
            proposal.action_type,
            f"The {proposal.action_type.value.lower()} action was simulated successfully.",
        )

        # Audit event recording proposal -> execution -> thread
        event = Event(
            id=event_id,
            type="SIMULATED_EXECUTION",
            description=(
                f"Action executed in simulated mode. "
                f"proposal_id: {proposal.id}, "
                f"action_type: {proposal.action_type.value}, "
                f"execution_mode: {execution_mode.value}"
            ),
            timestamp=ref_time,
        )

        result = ExecutionResult(
            proposal_id=proposal.id,
            thread_id=thread.id,
            action_type=proposal.action_type,
            execution_status=ExecutionStatus.EXECUTED,
            execution_mode=ExecutionMode.SIMULATED,
            message=message,
            event_id=event.id,
        )

        return result, event
