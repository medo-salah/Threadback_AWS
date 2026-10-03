"""
Unit tests for deterministic VerificationService (M10).

Validates:
  - Rule A (No Evidence -> verified = False)
  - Rule B (Unresolved Blocker -> verified = False)
  - Rule C (Open Mandatory Commitment -> verified = False)
  - Rule D (Sufficient Evidence & No Blockers -> verified = True)
  - Rule E (Contradictory Evidence -> verified = False)
  - Non-mutation invariant (verification never changes thread status)
  - Non-existent thread handling (ThreadNotFoundError)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    EvidenceType,
    Priority,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Evidence,
    IntentThread,
)
from app.services.thread_service import ThreadNotFoundError, ThreadService
from app.services.verification_service import VerificationService

_NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def thread_service() -> ThreadService:
    """ThreadService populated with fresh in-memory demo data."""
    return ThreadService(threads=get_demo_threads())


@pytest.fixture
def verification_service(thread_service: ThreadService) -> VerificationService:
    return VerificationService(thread_service=thread_service)


def test_verification_rule_b_unresolved_blocker(
    verification_service: VerificationService,
) -> None:
    """Rule B: University Application with active recommendation letter blocker fails verification."""
    result = verification_service.verify_thread(
        "thread-university-application", reference_time=_NOW
    )

    assert result.verified is False
    assert result.confidence == 0.61
    assert "recommendation letter" in result.reason.lower()
    assert "dep-uni-rec-letter" in [b.lower() for b in result.missing_evidence] or any(
        "recommendation letter" in m.lower() for m in result.missing_evidence
    )


def test_verification_rule_a_no_evidence(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> None:
    """Rule A: Thread with zero evidence items cannot be verified."""
    thread = IntentThread(
        id="thread-no-evidence",
        title="Zero Evidence Thread",
        description="Empty evidence intent",
        status=ThreadStatus.ACTIVE,
        priority=Priority.LOW,
        created_at=_NOW,
        updated_at=_NOW,
        last_activity_at=_NOW,
        confidence=0.50,
        commitments=[],
        evidence=[],
        dependencies=[],
    )
    thread_service.update_thread(thread)

    result = verification_service.verify_thread(
        "thread-no-evidence", reference_time=_NOW
    )
    assert result.verified is False
    assert "insufficient evidence" in result.reason.lower()


def test_verification_rule_c_open_commitment(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> None:
    """Rule C: Thread with open commitment and no fulfilling evidence fails verification."""
    thread = IntentThread(
        id="thread-open-com",
        title="Open Commitment Thread",
        description="Thread with unfulfilled commitment",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        created_at=_NOW,
        updated_at=_NOW,
        last_activity_at=_NOW,
        confidence=0.80,
        commitments=[
            Commitment(
                id="com-mandatory",
                description="Submit quarterly financial audit",
                status=CommitmentStatus.OPEN,
            )
        ],
        evidence=[
            Evidence(
                id="evi-general",
                type=EvidenceType.NOTE,
                description="Draft planning notes",
                source="Notes app",
                created_at=_NOW,
                confidence=0.70,
            )
        ],
        dependencies=[],
    )
    thread_service.update_thread(thread)

    result = verification_service.verify_thread("thread-open-com", reference_time=_NOW)
    assert result.verified is False
    assert "commitment" in result.reason.lower()


def test_verification_rule_e_contradictory_evidence(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> None:
    """Rule E: Evidence showing rejection, failure, or dispute fails verification."""
    thread = IntentThread(
        id="thread-rejected-application",
        title="Grant Application",
        description="Application for research grant",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        created_at=_NOW,
        updated_at=_NOW,
        last_activity_at=_NOW,
        confidence=0.90,
        commitments=[
            Commitment(
                id="com-grant-submit",
                description="Submit proposal",
                status=CommitmentStatus.COMPLETED,
            )
        ],
        evidence=[
            Evidence(
                id="evi-grant-reject",
                type=EvidenceType.MESSAGE,
                description="Formal notification: Research grant application rejected by committee",
                source="Grant Portal Email",
                created_at=_NOW,
                confidence=0.99,
            )
        ],
        dependencies=[],
    )
    thread_service.update_thread(thread)

    result = verification_service.verify_thread(
        "thread-rejected-application", reference_time=_NOW
    )
    assert result.verified is False
    assert "contradictory" in result.reason.lower()
    assert "rejected" in result.reason.lower()


def test_verification_rule_d_success_with_completion_evidence(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> None:
    """Rule D: When blocker is resolved by received evidence, verification passes."""
    # Add external evidence resolving recommendation letter blocker
    resolution_evidence = Evidence(
        id="evi-uni-3",
        type=EvidenceType.DOCUMENT,
        description="Recommendation letter received from Ahmed; application submission completed",
        source="Admissions Office Portal",
        created_at=_NOW,
        confidence=0.98,
    )
    thread_service.add_evidence("thread-university-application", resolution_evidence)

    result = verification_service.verify_thread(
        "thread-university-application", reference_time=_NOW
    )
    assert result.verified is True
    assert result.confidence == 0.94
    assert "required completion evidence is present" in result.reason.lower()
    assert "evi-uni-3" in result.matched_evidence
    assert result.missing_evidence == []


def test_verification_does_not_mutate_thread_status(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> None:
    """Verification is non-mutating: calling verify_thread never changes thread status."""
    uni_before = thread_service.get_thread("thread-university-application")
    assert uni_before.status == ThreadStatus.BLOCKED

    # Run verification (which fails due to blocker)
    res_fail = verification_service.verify_thread("thread-university-application")
    assert res_fail.verified is False

    uni_after_fail = thread_service.get_thread("thread-university-application")
    assert uni_after_fail.status == ThreadStatus.BLOCKED

    # Add resolution evidence
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-res",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed",
            source="Portal",
            created_at=_NOW,
            confidence=0.95,
        ),
    )

    # Run verification (which passes)
    res_pass = verification_service.verify_thread("thread-university-application")
    assert res_pass.verified is True

    # Crucial invariant: thread status must STILL be BLOCKED, not COMPLETED!
    uni_after_pass = thread_service.get_thread("thread-university-application")
    assert uni_after_pass.status == ThreadStatus.BLOCKED


def test_verification_unknown_thread_raises_error(
    verification_service: VerificationService,
) -> None:
    """Verifying a non-existent thread raises ThreadNotFoundError."""
    with pytest.raises(ThreadNotFoundError):
        verification_service.verify_thread("thread-ghost-nonexistent")
