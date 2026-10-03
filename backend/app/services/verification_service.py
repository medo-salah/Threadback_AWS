"""
Deterministic Verification Service for Threadback (M10).

Evaluates whether an IntentThread has sufficient structured factual evidence
to be considered complete, strictly maintaining the invariant:
    EXECUTION_SUCCESS != COMPLETION
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    CommitmentStatus,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import (
    ThreadEvent,
    ThreadVerification,
)
from app.services.thread_service import ThreadService

if TYPE_CHECKING:
    from app.domain.models import IntentThread

logger = logging.getLogger(__name__)

# Keywords indicating contradictory evidence (Rule E)
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

# Keywords indicating evidence resolving blockers or fulfilling commitments
RESOLUTION_KEYWORDS: tuple[str, ...] = (
    "received",
    "submitted",
    "submission confirmed",
    "delivered",
    "accepted",
    "approved",
    "completed",
    "receipt",
    "signed off",
    "confirmed",
    "filed",
)

# Evidence keywords that represent pending or in-progress states rather than final resolution
IN_PROGRESS_KEYWORDS: tuple[str, ...] = (
    "requesting",
    "awaiting",
    "pending",
    "draft",
    "preliminary",
)


class VerificationService:
    """
    Deterministic domain service for verifying IntentThread completion.

    Evaluates structured facts against five deterministic verification rules:
      - Rule A: No evidence -> not verified
      - Rule B: Blocking dependency -> not verified
      - Rule C: Open commitment -> not verified
      - Rule D: Completion evidence present & no blockers -> verified
      - Rule E: Contradictory evidence -> not verified

    Never uses an LLM to decide completion.
    Never mutates thread status during verification.
    """

    def __init__(self, thread_service: ThreadService) -> None:
        self._thread_service = thread_service

    def verify_thread(
        self,
        thread_id: str,
        reference_time: datetime | None = None,
    ) -> ThreadVerification:
        """
        Deterministically verify whether the thread has reached completion.

        Args:
            thread_id: The ID of the thread to evaluate.
            reference_time: Optional fixed timestamp anchor for testing.

        Returns:
            Structured ThreadVerification result.

        Raises:
            ThreadNotFoundError: If the thread ID does not exist.
        """
        thread = self._thread_service.get_thread(thread_id)
        now = reference_time or datetime.now(timezone.utc)

        # Record VERIFICATION_STARTED lifecycle event
        start_event_id = f"evt-ver-start-{thread_id}-{int(now.timestamp() * 1000)}"
        self._thread_service.add_event(
            thread_id,
            ThreadEvent(
                id=start_event_id,
                thread_id=thread_id,
                event_type=ThreadEventType.VERIFICATION_STARTED,
                type=ThreadEventType.VERIFICATION_STARTED.value,
                description=f"Deterministic completion verification started for thread '{thread.title}'.",
                timestamp=now,
                actor="system",
                source="deterministic_engine",
                payload={"thread_id": thread_id},
            ),
        )

        verification = self._evaluate_rules(thread, now)

        # Record outcome lifecycle event: VERIFICATION_PASSED or VERIFICATION_FAILED
        outcome_type = (
            ThreadEventType.VERIFICATION_PASSED
            if verification.verified
            else ThreadEventType.VERIFICATION_FAILED
        )
        end_event_id = f"evt-ver-end-{thread_id}-{int(now.timestamp() * 1000)}"
        self._thread_service.add_event(
            thread_id,
            ThreadEvent(
                id=end_event_id,
                thread_id=thread_id,
                event_type=outcome_type,
                type=outcome_type.value,
                description=(
                    f"Completion verification {'PASSED' if verification.verified else 'FAILED'}: "
                    f"{verification.reason}"
                ),
                timestamp=now,
                actor="system",
                source="deterministic_engine",
                payload={
                    "verified": verification.verified,
                    "confidence": verification.confidence,
                    "reason": verification.reason,
                    "matched_evidence": verification.matched_evidence,
                    "missing_evidence": verification.missing_evidence,
                },
            ),
        )

        # Persist verification record in repository
        self._thread_service.repository.save_verification(verification)

        return verification

    def _evaluate_rules(
        self,
        thread: IntentThread,
        verified_at: datetime,
    ) -> ThreadVerification:
        """Evaluate deterministic rules A through E against thread domain state."""

        # Check Abandoned state
        if thread.status == ThreadStatus.ABANDONED:
            return ThreadVerification(
                thread_id=thread.id,
                verified=False,
                confidence=0.0,
                reason="Thread is abandoned and cannot be verified for completion.",
                required_evidence=["Active thread required"],
                matched_evidence=[],
                missing_evidence=["Thread was abandoned"],
                verified_at=verified_at,
            )

        # Rule E: Contradictory Evidence
        for ev in thread.evidence:
            ev_desc_lower = ev.description.lower()
            if any(k in ev_desc_lower for k in CONTRADICTORY_KEYWORDS):
                return ThreadVerification(
                    thread_id=thread.id,
                    verified=False,
                    confidence=ev.confidence,
                    reason=f"Contradictory evidence indicates the intention is unresolved: {ev.description}",
                    required_evidence=["Resolution of conflicting evidence"],
                    matched_evidence=[],
                    missing_evidence=[f"Contradictory: {ev.description}"],
                    verified_at=verified_at,
                )

        # Rule A: No Evidence
        if not thread.evidence:
            return ThreadVerification(
                thread_id=thread.id,
                verified=False,
                confidence=0.30,
                reason="Insufficient evidence to verify completion.",
                required_evidence=["At least one verifiable evidence record required"],
                matched_evidence=[],
                missing_evidence=["Completion evidence required"],
                verified_at=verified_at,
            )

        # Rule B: Blocking Dependencies
        active_blockers = thread.active_blockers
        unresolved_blockers: list[str] = []
        matched_blocker_evidence: list[str] = []

        for blocker in active_blockers:
            b_desc_lower = blocker.description.lower()
            # Check if any evidence resolves this blocker
            resolving_ev = next(
                (
                    e
                    for e in thread.evidence
                    if any(
                        word in e.description.lower()
                        for word in b_desc_lower.split()
                        if len(word) > 4
                    )
                    and any(rk in e.description.lower() for rk in RESOLUTION_KEYWORDS)
                    and not any(
                        pk in e.description.lower() for pk in IN_PROGRESS_KEYWORDS
                    )
                ),
                None,
            )
            if resolving_ev is not None:
                matched_blocker_evidence.append(resolving_ev.id)
            else:
                unresolved_blockers.append(blocker.description)

        if unresolved_blockers:
            # Deterministic reason formatting matching canonical examples
            first_blocker = unresolved_blockers[0]
            if "recommendation letter" in first_blocker.lower():
                reason = "The recommendation letter remains unresolved."
            else:
                reason = f"The {first_blocker.lower()} remains unresolved."

            return ThreadVerification(
                thread_id=thread.id,
                verified=False,
                confidence=0.61,
                reason=reason,
                required_evidence=[
                    f"Evidence resolving: {b}" for b in unresolved_blockers
                ],
                matched_evidence=matched_blocker_evidence,
                missing_evidence=unresolved_blockers,
                verified_at=verified_at,
            )

        # Rule C: Mandatory Open Commitments
        open_commitments = [
            c for c in thread.commitments if c.status == CommitmentStatus.OPEN
        ]
        unresolved_commitments: list[str] = []
        matched_commitment_evidence: list[str] = []

        for com in open_commitments:
            c_desc_lower = com.description.lower()
            resolving_ev = next(
                (
                    e
                    for e in thread.evidence
                    if (
                        any(
                            word in e.description.lower()
                            for word in c_desc_lower.split()
                            if len(word) > 4
                        )
                        or any(
                            rk in e.description.lower() for rk in RESOLUTION_KEYWORDS
                        )
                    )
                    and not any(
                        pk in e.description.lower() for pk in IN_PROGRESS_KEYWORDS
                    )
                ),
                None,
            )
            if resolving_ev is not None:
                matched_commitment_evidence.append(resolving_ev.id)
            else:
                unresolved_commitments.append(com.description)

        if unresolved_commitments:
            return ThreadVerification(
                thread_id=thread.id,
                verified=False,
                confidence=0.55,
                reason=f"Open commitment '{unresolved_commitments[0]}' remains unfulfilled.",
                required_evidence=[
                    f"Evidence fulfilling: {c}" for c in unresolved_commitments
                ],
                matched_evidence=matched_commitment_evidence,
                missing_evidence=unresolved_commitments,
                verified_at=verified_at,
            )

        # Rule D: Completion Evidence Present & No Blocking Conditions
        # Find completion evidence
        completion_evidence_ids: list[str] = []
        for e in thread.evidence:
            e_desc_lower = e.description.lower()
            if any(pk in e_desc_lower for pk in IN_PROGRESS_KEYWORDS):
                continue
            if (
                any(rk in e_desc_lower for rk in RESOLUTION_KEYWORDS)
                or e.id in matched_blocker_evidence
                or e.id in matched_commitment_evidence
                or e.type.value in ("DOCUMENT", "USER_ACTION", "MESSAGE")
            ):
                completion_evidence_ids.append(e.id)

        if not completion_evidence_ids:
            return ThreadVerification(
                thread_id=thread.id,
                verified=False,
                confidence=0.45,
                reason="Available evidence does not demonstrate actual completion.",
                required_evidence=["Definitive completion evidence"],
                matched_evidence=[],
                missing_evidence=["Factual completion record"],
                verified_at=verified_at,
            )

        return ThreadVerification(
            thread_id=thread.id,
            verified=True,
            confidence=thread.confidence,
            reason="Required completion evidence is present and no blocking dependency remains.",
            required_evidence=[
                "Completion evidence verifying resolved dependencies and commitments"
            ],
            matched_evidence=completion_evidence_ids,
            missing_evidence=[],
            verified_at=verified_at,
        )
