"""
Safe Closure Assistant Service for Threadback (M15).

Deterministic assistant identifying threads eligible for safe closure.
Examines completion evidence, open blockers, open commitments, and verification status.

Mandatory Invariants:
  - Never automatically close threads.
  - Closure remains strictly confirmation-gated: verify_thread_completion -> close_thread.
"""

from __future__ import annotations

import logging

from app.domain.enums import CommitmentStatus, ThreadStatus
from app.domain.models import IntentThread, SafeClosureCandidate
from app.services.verification_service import VerificationService

logger = logging.getLogger(__name__)


class SafeClosureAssistant:
    """
    Deterministic domain assistant evaluating closure readiness.
    """

    def __init__(self, verification_service: VerificationService | None = None) -> None:
        self._verification_service = verification_service or VerificationService()

    def evaluate_thread(self, thread: IntentThread) -> SafeClosureCandidate:
        """
        Evaluate a single thread's safety for closure.
        """
        # Blockers
        active_blockers = thread.active_blockers
        active_blockers_count = len(active_blockers)

        # Open commitments
        open_commitments = [
            c for c in thread.commitments if c.status == CommitmentStatus.OPEN
        ]
        open_commitments_count = len(open_commitments)

        # Evidence
        evidence_count = len(thread.evidence)

        # Verification
        verification = self._verification_service.verify_completion(thread)
        verification_status = "VERIFIED" if verification.verified else "UNVERIFIED"

        # Safe to close requires:
        # 1. Thread is not already closed/abandoned
        # 2. No active blockers
        # 3. Verified completion via VerificationService
        # 4. No conflicting open commitments
        is_already_terminal = thread.status in (
            ThreadStatus.COMPLETED,
            ThreadStatus.ABANDONED,
        )
        is_safe = (
            not is_already_terminal
            and active_blockers_count == 0
            and verification.verified
            and open_commitments_count == 0
        )

        # Build explainable readiness reason
        if is_already_terminal:
            reason = f"Thread is already in terminal state ({thread.status.value})."
            next_step = "No closure action needed."
        elif is_safe:
            reason = (
                f"Verified complete with {evidence_count} evidence item(s), "
                "0 active blockers, and all commitments fulfilled."
            )
            next_step = f"Thread is safe to close. Proceed to verify and close '{thread.title}'."
        elif active_blockers_count > 0:
            b_desc = active_blockers[0].description
            reason = (
                f"Cannot safely close: blocked by unresolved dependency '{b_desc}'."
            )
            next_step = f"Resolve active blocker '{b_desc}' before requesting closure."
        elif not verification.verified:
            reason = f"Cannot safely close: verification criteria not satisfied ({verification.reason})."
            next_step = (
                "Fulfill remaining goal requirements and gather completion evidence."
            )
        elif open_commitments_count > 0:
            c_desc = open_commitments[0].description
            reason = f"Cannot safely close: has {open_commitments_count} open commitment(s) ('{c_desc}')."
            next_step = f"Complete commitment '{c_desc}' before closing."
        else:
            reason = "Closure conditions have not been verified."
            next_step = "Review thread context and verification status."

        return SafeClosureCandidate(
            thread_id=thread.id,
            thread_title=thread.title,
            is_safe_to_close=is_safe,
            completion_evidence_count=evidence_count,
            active_blockers_count=active_blockers_count,
            open_commitments_count=open_commitments_count,
            verification_status=verification_status,
            closure_readiness_reason=reason,
            next_step=next_step,
        )

    def evaluate_threads(
        self, threads: list[IntentThread]
    ) -> list[SafeClosureCandidate]:
        """
        Evaluate all active or waiting threads for closure readiness.
        """
        # Focus on non-terminal threads
        evaluable = [
            t
            for t in threads
            if t.status
            in (
                ThreadStatus.ACTIVE,
                ThreadStatus.WAITING,
                ThreadStatus.BLOCKED,
                ThreadStatus.DISCOVERED,
                ThreadStatus.DEFERRED,
            )
        ]
        results = [self.evaluate_thread(t) for t in evaluable]
        # Sort so safe-to-close appear first
        results.sort(key=lambda c: (not c.is_safe_to_close, c.thread_title))
        return results
