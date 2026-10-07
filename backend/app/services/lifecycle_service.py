"""
Lifecycle Closure Service for Threadback (M10).

Manages state transitions and safe lifecycle completion for IntentThreads,
enforcing the fundamental invariant:
    close_thread(thread_id) CANNOT bypass verify_thread_completion(thread_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    ClosureStatus,
    CommitmentStatus,
    DependencyStatus,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import CloseThreadResponse, ThreadEvent
from app.services.thread_service import ThreadService
from app.services.verification_service import VerificationService

if TYPE_CHECKING:
    from app.domain.models import IntentThread, ThreadVerification

logger = logging.getLogger(__name__)

CONTRADICTORY_KEYWORDS: tuple[str, ...] = (
    "rejected",
    "rejection",
    "failed",
    "failure",
    "cancelled",
    "canceled",
    "cancellation",
    "denied",
    "dispute",
    "error",
    "incomplete",
)


class LifecycleService:
    """
    Deterministic domain service for managing IntentThread lifecycle closure.

    Ensures threads are only transitioned to COMPLETED when backed by verified evidence.
    """

    def __init__(
        self,
        thread_service: ThreadService,
        verification_service: VerificationService,
    ) -> None:
        self._thread_service = thread_service
        self._verification_service = verification_service

    def close_thread(
        self,
        thread_id: str,
        reference_time: datetime | None = None,
    ) -> CloseThreadResponse:
        """
        Safely transition an IntentThread into COMPLETED status after verification.

        Validates all 7 closure safety rules:
          1. Thread exists.
          2. Thread is not ABANDONED.
          3. Thread is not already COMPLETED (idempotent result, no duplicate events).
          4. A valid prior verification record exists.
          5. Verification succeeded (verified == True).
          6. Required completion evidence remains present.
          7. No blocking condition has appeared after verification.

        Args:
            thread_id: Unique identifier of the thread to close.
            reference_time: Optional fixed timestamp anchor for testing.

        Returns:
            CloseThreadResponse containing status and closure outcome.

        Raises:
            ThreadNotFoundError: If thread_id does not exist.
        """
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        now = reference_time or datetime.now(timezone.utc)

        # Rule 2: Abandoned thread protection
        if thread.status == ThreadStatus.ABANDONED:
            return CloseThreadResponse(
                thread_id=thread_id,
                status=thread.status,
                closure_status=ClosureStatus.REJECTED,
                message="Cannot close thread: thread is ABANDONED.",
            )

        # Rule 3: Idempotency check for already completed thread
        if thread.status == ThreadStatus.COMPLETED:
            return CloseThreadResponse(
                thread_id=thread_id,
                status=ThreadStatus.COMPLETED,
                closure_status=ClosureStatus.ALREADY_COMPLETED,
                message="Thread is already completed. No state change required.",
            )

        # Rule 4: Verification existence check
        latest_verification: ThreadVerification | None = (
            self._thread_service.repository.get_latest_verification(thread_id)
        )
        if latest_verification is None:
            return CloseThreadResponse(
                thread_id=thread_id,
                status=thread.status,
                closure_status=ClosureStatus.REJECTED,
                message=(
                    "Thread cannot be closed without prior successful verification. "
                    "Run verify_thread_completion first."
                ),
            )

        # Rule 5: Verification outcome check
        if not latest_verification.verified:
            return CloseThreadResponse(
                thread_id=thread_id,
                status=thread.status,
                closure_status=ClosureStatus.REJECTED,
                message=(
                    f"Thread closure rejected: verification did not pass. "
                    f"Reason: {latest_verification.reason}"
                ),
            )

        # Rule 6 & 7: Check that completion evidence remains valid and no new blocker appeared
        # 1. Did contradictory evidence appear after verification?
        for ev in thread.evidence:
            if ev.created_at > latest_verification.verified_at:
                ev_desc_lower = ev.description.lower()
                if any(k in ev_desc_lower for k in CONTRADICTORY_KEYWORDS):
                    return CloseThreadResponse(
                        thread_id=thread_id,
                        status=thread.status,
                        closure_status=ClosureStatus.REJECTED,
                        message=(
                            f"Thread closure rejected: contradictory evidence appeared after verification: {ev.description}"
                        ),
                    )

        # 2. Check if a new blocking condition appeared after verification
        events_after = [
            e
            for e in thread.events
            if e.timestamp > latest_verification.verified_at
            and (
                e.type == "BLOCKER_IDENTIFIED"
                or getattr(e, "event_type", "") == ThreadEventType.BLOCKER_IDENTIFIED
            )
        ]
        if events_after:
            return CloseThreadResponse(
                thread_id=thread_id,
                status=thread.status,
                closure_status=ClosureStatus.REJECTED,
                message=(
                    f"Thread closure rejected: new blocking condition appeared after verification: {events_after[0].description}"
                ),
            )

        # All checks passed: safely execute closure
        thread.status = ThreadStatus.COMPLETED
        thread.updated_at = now
        thread.last_activity_at = now

        # Update dependencies and commitments to resolved/completed
        for d in thread.dependencies:
            d.status = DependencyStatus.RESOLVED
            d.blocking = False
        for c in thread.commitments:
            if c.status == CommitmentStatus.OPEN:
                c.status = CommitmentStatus.COMPLETED

        # Record THREAD_COMPLETED lifecycle event
        close_event_id = f"evt-close-{thread_id}-{int(now.timestamp() * 1000)}"
        close_event = ThreadEvent(
            id=close_event_id,
            thread_id=thread_id,
            event_type=ThreadEventType.THREAD_COMPLETED,
            type=ThreadEventType.THREAD_COMPLETED.value,
            description=f"Thread '{thread.title}' successfully verified and completed.",
            timestamp=now,
            actor="system",
            source="deterministic_engine",
            payload={
                "previous_status": thread.status.value,
                "verified_at": latest_verification.verified_at.isoformat(),
                "confidence": latest_verification.confidence,
            },
        )

        # Persist updated thread aggregate and record completion event
        self._thread_service.update_thread(thread)
        self._thread_service.add_event(thread_id, close_event)

        return CloseThreadResponse(
            thread_id=thread_id,
            status=ThreadStatus.COMPLETED,
            closure_status=ClosureStatus.COMPLETED,
            message="Thread successfully verified and closed.",
            verification_id=f"ver-{thread_id}",
            event_id=close_event.id,
        )

    def defer_thread(
        self,
        thread_id: str,
        deferred_until: datetime | None = None,
        reason: str = "Postponed by user",
        reference_time: datetime | None = None,
    ) -> ThreadEvent:
        """
        Transition an open IntentThread into DEFERRED status.

        Preserves all evidence, commitments, and historical events.
        """
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        if thread.status in (ThreadStatus.COMPLETED, ThreadStatus.ABANDONED):
            raise ValueError(
                f"Cannot defer thread '{thread_id}' with terminal status '{thread.status.value}'."
            )

        now = reference_time or datetime.now(timezone.utc)
        clean_reason = reason.strip() or "Postponed by user"

        thread.status = ThreadStatus.DEFERRED
        thread.deferred_until = deferred_until
        thread.updated_at = now
        thread.last_interaction_at = now

        defer_event_id = f"evt-defer-{thread_id}-{int(now.timestamp() * 1000)}"
        defer_event = ThreadEvent(
            id=defer_event_id,
            thread_id=thread_id,
            event_type=ThreadEventType.THREAD_DEFERRED,
            type=ThreadEventType.THREAD_DEFERRED.value,
            description=f"Thread '{thread.title}' deferred: {clean_reason}",
            timestamp=now,
            actor="user",
            source="conversational_agent",
            payload={
                "reason": clean_reason,
                "deferred_until": deferred_until.isoformat()
                if deferred_until
                else None,
            },
        )

        self._thread_service.update_thread(thread)
        self._thread_service.add_event(thread_id, defer_event)
        logger.info(
            "Thread '%s' deferred until %s (reason: %s)",
            thread_id,
            deferred_until,
            clean_reason,
        )
        return defer_event

    def resume_thread(
        self,
        thread_id: str,
        reason: str = "Resumed by user",
        reference_time: datetime | None = None,
    ) -> ThreadEvent:
        """
        Resume a DEFERRED (or inactive) IntentThread back into active lifecycle.

        Recomputes status based on open blockers and dependencies.
        """
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        if thread.status == ThreadStatus.COMPLETED:
            raise ValueError(f"Cannot resume completed thread '{thread_id}'.")

        now = reference_time or datetime.now(timezone.utc)
        clean_reason = reason.strip() or "Resumed by user"

        # Deterministically determine new status based on dependencies
        if len(thread.active_blockers) > 0:
            new_status = ThreadStatus.BLOCKED
        elif any(d.status == DependencyStatus.OPEN for d in thread.dependencies):
            new_status = ThreadStatus.WAITING
        else:
            new_status = ThreadStatus.ACTIVE

        thread.status = new_status
        thread.deferred_until = None
        thread.updated_at = now
        thread.last_interaction_at = now

        resume_event_id = f"evt-resume-{thread_id}-{int(now.timestamp() * 1000)}"
        resume_event = ThreadEvent(
            id=resume_event_id,
            thread_id=thread_id,
            event_type=ThreadEventType.THREAD_RESUMED,
            type=ThreadEventType.THREAD_RESUMED.value,
            description=f"Thread '{thread.title}' resumed as {new_status.value}: {clean_reason}",
            timestamp=now,
            actor="user",
            source="conversational_agent",
            payload={
                "reason": clean_reason,
                "resumed_status": new_status.value,
            },
        )

        self._thread_service.update_thread(thread)
        self._thread_service.add_event(thread_id, resume_event)
        logger.info(
            "Thread '%s' resumed as %s (reason: %s)",
            thread_id,
            new_status.value,
            clean_reason,
        )
        return resume_event

    def abandon_thread(
        self,
        thread_id: str,
        reason: str = "Abandoned by user",
        reference_time: datetime | None = None,
    ) -> ThreadEvent:
        """
        Explicitly abandon an IntentThread.

        Crucial invariant: Abandonment never deletes historical evidence, commitments,
        or previous lifecycle events.
        """
        thread: IntentThread = self._thread_service.get_thread(thread_id)
        if thread.status == ThreadStatus.COMPLETED:
            raise ValueError(f"Cannot abandon completed thread '{thread_id}'.")

        now = reference_time or datetime.now(timezone.utc)
        clean_reason = reason.strip() or "Abandoned by user"

        thread.status = ThreadStatus.ABANDONED
        thread.abandoned_reason = clean_reason
        thread.updated_at = now
        thread.last_interaction_at = now

        abandon_event_id = f"evt-abandon-{thread_id}-{int(now.timestamp() * 1000)}"
        abandon_event = ThreadEvent(
            id=abandon_event_id,
            thread_id=thread_id,
            event_type=ThreadEventType.THREAD_ABANDONED,
            type=ThreadEventType.THREAD_ABANDONED.value,
            description=f"Thread '{thread.title}' marked ABANDONED: {clean_reason}",
            timestamp=now,
            actor="user",
            source="conversational_agent",
            payload={"reason": clean_reason},
        )

        self._thread_service.update_thread(thread)
        self._thread_service.add_event(thread_id, abandon_event)
        logger.info("Thread '%s' abandoned (reason: %s)", thread_id, clean_reason)
        return abandon_event
