"""
Controlled Action Execution Service for Threadback (M7).

Coordinates the M7 validation pipeline, executes validated action proposals
via SimulatedActionExecutor, records audit events on the affected thread,
and maintains an in-memory idempotency ledger.

Strict non-execution boundary: operates in SIMULATED mode only.
No external network requests, emails, calls, messages, or mutations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    ProposalStatus,
    ThreadStatus,
)
from app.domain.models import Event, ExecutionResult
from app.services.action_executor import ActionExecutor, SimulatedActionExecutor
from app.services.thread_service import ThreadNotFoundError

if TYPE_CHECKING:
    from app.domain.models import ActionProposal, IntentThread
    from app.repositories.base import BaseThreadRepository
    from app.services.proposal_registry import ProposalRegistry
    from app.services.thread_service import ThreadService


def validate_preconditions(
    proposal: ActionProposal,
    thread: IntentThread,
) -> tuple[bool, str | None]:
    """Validate proposal preconditions against current thread state.

    Returns:
        (True, None) if all preconditions pass.
        (False, failed_reason) if any precondition is unsatisfied.
    """
    for prec in proposal.preconditions:
        # Check explicit test-failure or unsatisfied markers
        if (
            prec.startswith("FAILED:")
            or "[UNSATISFIED]" in prec
            or prec.startswith("UNSATISFIED:")
        ):
            return False, prec

        # Missing recipient precondition
        if "Recipient identity must be established" in prec:
            recipient = proposal.inputs.get("recipient")
            if not recipient:
                return False, prec

        # Commitment preconditions (e.g. "Commitment '...' is open and actionable")
        if "open and actionable" in prec or "Commitment '" in prec:
            for cid in proposal.supporting_commitment_ids:
                comm = next((c for c in thread.commitments if c.id == cid), None)
                if comm is None or comm.status != CommitmentStatus.OPEN:
                    return (
                        False,
                        f"Supporting commitment '{cid}' is not open and actionable.",
                    )

        # Dependency preconditions (e.g. "Dependency '...' must be resolved", "Awaiting external response for '...'")
        if (
            "must be resolved" in prec
            or "Awaiting external response" in prec
            or "Dependency '" in prec
        ):
            for did in proposal.supporting_dependency_ids:
                dep = next((d for d in thread.dependencies if d.id == did), None)
                if dep is None or dep.status != DependencyStatus.OPEN:
                    return (
                        False,
                        f"Supporting dependency '{did}' is not open and pending.",
                    )

    return True, None


class ExecutionService:
    """Controlled Action Execution Service (M7).

    Enforces the strict 7-step validation pipeline:
      Step 1 — Proposal existence
      Step 2 — Proposal status
      Step 3 — Explicit confirmation
      Step 4 — Preconditions
      Step 5 — Source thread existence
      Step 6 — Terminal thread protection
      Step 7 — Idempotency ledger

    Executes validated proposals using an ActionExecutor (SimulatedActionExecutor).
    """

    def __init__(
        self,
        proposal_registry: ProposalRegistry | None = None,
        thread_service: ThreadService | None = None,
        executor: ActionExecutor | None = None,
        repository: BaseThreadRepository | None = None,
        intent_memory_service: Any = None,
        lifecycle_service: Any = None,
    ) -> None:
        self._registry = proposal_registry
        self._thread_service = thread_service
        self._executor = executor or SimulatedActionExecutor()
        self._repository = repository or (
            getattr(thread_service, "repository", None) if thread_service else None
        )
        self._intent_memory_service = intent_memory_service
        self._lifecycle_service = lifecycle_service
        self._ledger: dict[str, ExecutionResult] = {}

    @property
    def intent_memory_service(self) -> Any:
        if self._intent_memory_service is None and self._thread_service is not None:
            from app.services.intent_memory_service import IntentMemoryService

            self._intent_memory_service = IntentMemoryService(
                thread_service=self._thread_service
            )
        return self._intent_memory_service

    @property
    def lifecycle_service(self) -> Any:
        if self._lifecycle_service is None and self._thread_service is not None:
            from app.services.lifecycle_service import LifecycleService

            self._lifecycle_service = LifecycleService(
                thread_service=self._thread_service
            )
        return self._lifecycle_service

    def execute_action(
        self,
        proposal_id: str,
        confirmed: bool = False,
        execution_mode: ExecutionMode | str = ExecutionMode.SIMULATED,
        reference_time: datetime | None = None,
    ) -> ExecutionResult:
        """Validate and execute a prepared ActionProposal (M7 / M13).

        External-world operational actions (send email, submit application, etc.)
        execute strictly in SIMULATED mode. No real-world side effects.

        Threadback internal state mutations (EVOLVE_INTENTION, DEFER_INTENTION,
        RESUME_INTENTION, ABANDON_INTENTION) execute as PERSISTENT_MUTATION,
        duly updating internal SQLite state and appending lifecycle events after
        satisfying the confirmation and precondition safety pipeline.

        Args:
            proposal_id: Unique deterministic ID of the prepared proposal.
            confirmed: Explicit confirmation from caller. Required if proposal.requires_confirmation is True.
            execution_mode: Execution mode (SIMULATED or PERSISTENT_MUTATION).
            reference_time: Optional deterministic reference timestamp for events.

        Returns:
            Structured ExecutionResult distinguishing EXECUTED, REJECTED, BLOCKED,
            or ALREADY_EXECUTED with accurate execution_mode.
        """
        # Validate execution mode
        mode_str = (
            execution_mode.value
            if isinstance(execution_mode, ExecutionMode)
            else str(execution_mode)
        )
        valid_modes = {
            ExecutionMode.SIMULATED.value,
            ExecutionMode.PERSISTENT_MUTATION.value,
        }
        if mode_str not in valid_modes:
            return ExecutionResult(
                proposal_id=proposal_id,
                thread_id="",
                action_type=NextActionType.NO_ACTION,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=ExecutionMode.SIMULATED,
                message=(
                    f"Unsupported execution mode '{mode_str}'. "
                    "Only 'SIMULATED' (for external operational actions) and 'PERSISTENT_MUTATION' "
                    "(for internal Threadback state mutations) are supported."
                ),
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 1: Proposal existence (persistent repository is authoritative)
        # -------------------------------------------------------------------
        proposal: ActionProposal | None = None
        if self._repository is not None:
            proposal = self._repository.get_proposal(proposal_id)
        elif (
            self._thread_service is not None
            and hasattr(self._thread_service, "repository")
            and self._thread_service.repository is not None
        ):
            proposal = self._thread_service.repository.get_proposal(proposal_id)

        if proposal is None and self._registry is not None:
            proposal = self._registry.get(proposal_id)

        if proposal is None:
            return ExecutionResult(
                proposal_id=proposal_id,
                thread_id="",
                action_type=NextActionType.NO_ACTION,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=ExecutionMode.SIMULATED,
                message=(
                    f"Proposal '{proposal_id}' was not found in the proposal registry "
                    "or is no longer available."
                ),
                event_id=None,
            )

        # Determine expected execution taxonomy for this proposal
        mutation_types = {
            NextActionType.EVOLVE_INTENTION,
            NextActionType.DEFER_INTENTION,
            NextActionType.RESUME_INTENTION,
            NextActionType.ABANDON_INTENTION,
        }
        is_internal_mutation = proposal.action_type in mutation_types
        target_mode = (
            ExecutionMode.PERSISTENT_MUTATION
            if is_internal_mutation
            else ExecutionMode.SIMULATED
        )

        # External operational actions cannot be executed in PERSISTENT_MUTATION mode
        if (
            not is_internal_mutation
            and mode_str == ExecutionMode.PERSISTENT_MUTATION.value
        ):
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=ExecutionMode.SIMULATED,
                message=(
                    f"Operational action '{proposal.action_type.value}' cannot be executed in "
                    "PERSISTENT_MUTATION mode. External operational actions remain SIMULATED ONLY."
                ),
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 2: Proposal status
        # -------------------------------------------------------------------
        if proposal.status == ProposalStatus.BLOCKED:
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.BLOCKED,
                execution_mode=target_mode,
                message=(
                    f"Proposal '{proposal.id}' is BLOCKED and cannot be executed. "
                    f"Reason: {proposal.confirmation_reason or 'unresolved precondition or missing required information'}."
                ),
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 3: Explicit confirmation
        # -------------------------------------------------------------------
        if proposal.requires_confirmation and not confirmed:
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=target_mode,
                message=(
                    f"Action requires explicit user confirmation before execution (confirmed=true). "
                    f"Reason: {proposal.confirmation_reason or 'Action modifies state or creates simulated side effects'}."
                ),
                event_id=None,
            )

        # Retrieve source thread for Steps 4, 5, 6
        try:
            thread = self._thread_service.get_thread(proposal.thread_id)
        except ThreadNotFoundError:
            # Step 5 failure: unknown thread
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=target_mode,
                message=f"Source thread '{proposal.thread_id}' was not found.",
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 4: Preconditions
        # -------------------------------------------------------------------
        preconditions_ok, failed_reason = validate_preconditions(proposal, thread)
        if not preconditions_ok:
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.BLOCKED,
                execution_mode=target_mode,
                message=f"Execution blocked: Precondition failed - {failed_reason}",
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 5: Source thread (already verified thread exists)
        # -------------------------------------------------------------------

        # -------------------------------------------------------------------
        # Step 6: Terminal thread protection
        # -------------------------------------------------------------------
        if proposal.action_type == NextActionType.RESUME_INTENTION:
            if thread.status == ThreadStatus.COMPLETED:
                return ExecutionResult(
                    proposal_id=proposal.id,
                    thread_id=thread.id,
                    action_type=proposal.action_type,
                    execution_status=ExecutionStatus.REJECTED,
                    execution_mode=target_mode,
                    message=f"Cannot resume thread '{thread.id}' because thread is in terminal status '{thread.status.value}'.",
                    event_id=None,
                )
        elif proposal.action_type == NextActionType.ABANDON_INTENTION:
            if thread.status == ThreadStatus.COMPLETED:
                return ExecutionResult(
                    proposal_id=proposal.id,
                    thread_id=thread.id,
                    action_type=proposal.action_type,
                    execution_status=ExecutionStatus.REJECTED,
                    execution_mode=target_mode,
                    message=f"Cannot abandon thread '{thread.id}' because thread is already COMPLETED.",
                    event_id=None,
                )
        elif thread.status in (ThreadStatus.COMPLETED, ThreadStatus.ABANDONED):
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=thread.id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=target_mode,
                message=(
                    f"Cannot execute action on thread '{thread.id}' because thread is in "
                    f"terminal status '{thread.status.value}'."
                ),
                event_id=None,
            )

        # -------------------------------------------------------------------
        # Step 7: Idempotency (in-memory ledger or persistent event history)
        # -------------------------------------------------------------------
        event_suffix = proposal.id.replace("proposal-", "")
        expected_event_id = f"evt-exec-{event_suffix}"
        matching_event = next(
            (
                ev
                for ev in thread.events
                if ev.id == expected_event_id
                or f"proposal_id: {proposal.id}" in getattr(ev, "description", "")
            ),
            None,
        )

        if proposal.id in self._ledger:
            prev = self._ledger[proposal.id]
            return ExecutionResult(
                proposal_id=prev.proposal_id,
                thread_id=prev.thread_id,
                action_type=prev.action_type,
                execution_status=ExecutionStatus.ALREADY_EXECUTED,
                execution_mode=prev.execution_mode,
                message=(
                    f"Proposal '{proposal.id}' was already executed. "
                    "Returning previous execution information."
                ),
                event_id=prev.event_id,
            )
        elif matching_event is not None:
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.ALREADY_EXECUTED,
                execution_mode=target_mode,
                message=(
                    f"Proposal '{proposal.id}' was already executed. "
                    "Returning previous execution information."
                ),
                event_id=matching_event.id,
            )

        # -------------------------------------------------------------------
        # Non-executable action type check
        # -------------------------------------------------------------------
        if proposal.action_type == NextActionType.NO_ACTION:
            return ExecutionResult(
                proposal_id=proposal.id,
                thread_id=proposal.thread_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.REJECTED,
                execution_mode=ExecutionMode.SIMULATED,
                message="NO_ACTION proposal cannot be executed because no action is required.",
                event_id=None,
            )

        # -------------------------------------------------------------------
        # M13 Deterministic Domain Mutations (Persistent Threadback State Mutations)
        # -------------------------------------------------------------------
        if proposal.action_type == NextActionType.EVOLVE_INTENTION:
            new_goal = (proposal.inputs.get("new_goal") or proposal.title).strip()
            reason = (
                proposal.inputs.get("reason")
                or "Goal evolved via approved action proposal"
            ).strip()
            evolution = self.intent_memory_service.evolve_goal(
                thread_id=thread.id,
                revised_goal=new_goal,
                reason=reason,
                reference_time=reference_time,
            )
            result = ExecutionResult(
                proposal_id=proposal.id,
                thread_id=thread.id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.EXECUTED,
                execution_mode=ExecutionMode.PERSISTENT_MUTATION,
                message=f"Intention evolved for '{thread.title}'. Current goal persistently updated to '{new_goal}'.",
                event_id=evolution.trigger_event_id,
            )
            # Record audit event on the thread for persistent restart idempotency
            audit_event = Event(
                id=expected_event_id,
                type="MUTATION_EXECUTION",
                description=(
                    f"Action executed in persistent mutation mode. "
                    f"proposal_id: {proposal.id}, "
                    f"action_type: {proposal.action_type.value}, "
                    f"execution_mode: {ExecutionMode.PERSISTENT_MUTATION.value}"
                ),
                timestamp=reference_time or datetime.now(timezone.utc),
            )
            self._thread_service.add_event(thread.id, audit_event)
            self._ledger[proposal.id] = result
            return result

        if proposal.action_type == NextActionType.DEFER_INTENTION:
            until_val = proposal.inputs.get("deferred_until")
            until_dt: datetime | None = None
            if isinstance(until_val, datetime):
                until_dt = until_val
            elif isinstance(until_val, str) and until_val:
                try:
                    until_dt = datetime.fromisoformat(until_val.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    now_ref = reference_time or datetime.now(timezone.utc)
                    until_dt = now_ref + timedelta(days=7)
            reason = (
                proposal.inputs.get("reason") or "Deferred via approved action proposal"
            ).strip()
            defer_event = self.lifecycle_service.defer_thread(
                thread_id=thread.id,
                deferred_until=until_dt,
                reason=reason,
                reference_time=reference_time,
            )
            result = ExecutionResult(
                proposal_id=proposal.id,
                thread_id=thread.id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.EXECUTED,
                execution_mode=ExecutionMode.PERSISTENT_MUTATION,
                message=f"Thread '{thread.title}' persistently deferred until {until_val or 'further notice'}.",
                event_id=defer_event.id,
            )
            audit_event = Event(
                id=expected_event_id,
                type="MUTATION_EXECUTION",
                description=(
                    f"Action executed in persistent mutation mode. "
                    f"proposal_id: {proposal.id}, "
                    f"action_type: {proposal.action_type.value}, "
                    f"execution_mode: {ExecutionMode.PERSISTENT_MUTATION.value}"
                ),
                timestamp=reference_time or datetime.now(timezone.utc),
            )
            self._thread_service.add_event(thread.id, audit_event)
            self._ledger[proposal.id] = result
            return result

        if proposal.action_type == NextActionType.RESUME_INTENTION:
            reason = (
                proposal.inputs.get("reason") or "Resumed via approved action proposal"
            ).strip()
            resume_event = self.lifecycle_service.resume_thread(
                thread_id=thread.id,
                reason=reason,
                reference_time=reference_time,
            )
            result = ExecutionResult(
                proposal_id=proposal.id,
                thread_id=thread.id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.EXECUTED,
                execution_mode=ExecutionMode.PERSISTENT_MUTATION,
                message=f"Thread '{thread.title}' persistently resumed back to active lifecycle.",
                event_id=resume_event.id,
            )
            audit_event = Event(
                id=expected_event_id,
                type="MUTATION_EXECUTION",
                description=(
                    f"Action executed in persistent mutation mode. "
                    f"proposal_id: {proposal.id}, "
                    f"action_type: {proposal.action_type.value}, "
                    f"execution_mode: {ExecutionMode.PERSISTENT_MUTATION.value}"
                ),
                timestamp=reference_time or datetime.now(timezone.utc),
            )
            self._thread_service.add_event(thread.id, audit_event)
            self._ledger[proposal.id] = result
            return result

        if proposal.action_type == NextActionType.ABANDON_INTENTION:
            reason = (
                proposal.inputs.get("reason")
                or "Abandoned via approved action proposal"
            ).strip()
            abandon_event = self.lifecycle_service.abandon_thread(
                thread_id=thread.id,
                reason=reason,
                reference_time=reference_time,
            )
            result = ExecutionResult(
                proposal_id=proposal.id,
                thread_id=thread.id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.EXECUTED,
                execution_mode=ExecutionMode.PERSISTENT_MUTATION,
                message=f"Thread '{thread.title}' persistently marked as ABANDONED. Reason: {reason}",
                event_id=abandon_event.id,
            )
            audit_event = Event(
                id=expected_event_id,
                type="MUTATION_EXECUTION",
                description=(
                    f"Action executed in persistent mutation mode. "
                    f"proposal_id: {proposal.id}, "
                    f"action_type: {proposal.action_type.value}, "
                    f"execution_mode: {ExecutionMode.PERSISTENT_MUTATION.value}"
                ),
                timestamp=reference_time or datetime.now(timezone.utc),
            )
            self._thread_service.add_event(thread.id, audit_event)
            self._ledger[proposal.id] = result
            return result

        # -------------------------------------------------------------------
        # Execution (Simulated)
        # -------------------------------------------------------------------
        result, event = self._executor.execute(
            proposal=proposal,
            thread=thread,
            execution_mode=ExecutionMode.SIMULATED,
            reference_time=reference_time,
        )

        # Record audit event on the thread
        self._thread_service.add_event(thread.id, event)

        # Record in idempotency ledger
        self._ledger[proposal.id] = result

        return result
