"""
Unit tests for Lifecycle Closure Service (M10).

Validates:
  - Close safety invariant: close_thread cannot bypass verify_thread_completion
  - Unverified threads rejected
  - Blocked threads rejected
  - Abandoned threads rejected
  - Nonexistent threads raise ThreadNotFoundError
  - Successfully verified threads transition to COMPLETED
  - Auditable THREAD_COMPLETED event is created and persisted
  - Idempotency: closing an already-completed thread returns ALREADY_COMPLETED without duplicate events
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    ClosureStatus,
    EvidenceType,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import Evidence
from app.services.lifecycle_service import LifecycleService
from app.services.thread_service import ThreadNotFoundError, ThreadService
from app.services.verification_service import VerificationService

_NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def thread_service() -> ThreadService:
    return ThreadService(threads=get_demo_threads())


@pytest.fixture
def verification_service(thread_service: ThreadService) -> VerificationService:
    return VerificationService(thread_service=thread_service)


@pytest.fixture
def lifecycle_service(
    thread_service: ThreadService,
    verification_service: VerificationService,
) -> LifecycleService:
    return LifecycleService(
        thread_service=thread_service,
        verification_service=verification_service,
    )


def test_close_thread_without_prior_verification_is_rejected(
    lifecycle_service: LifecycleService,
) -> None:
    """Close safety invariant: close_thread cannot be called without prior verification."""
    res = lifecycle_service.close_thread(
        "thread-university-application", reference_time=_NOW
    )
    assert res.closure_status == ClosureStatus.REJECTED
    assert "cannot be closed without prior successful verification" in res.message


def test_close_thread_with_failed_verification_is_rejected(
    verification_service: VerificationService,
    lifecycle_service: LifecycleService,
) -> None:
    """A thread with failed verification cannot be closed."""
    # 1. Run verification (which fails due to blocker)
    ver = verification_service.verify_thread("thread-university-application")
    assert ver.verified is False

    # 2. Attempt closure
    res = lifecycle_service.close_thread(
        "thread-university-application", reference_time=_NOW
    )
    assert res.closure_status == ClosureStatus.REJECTED
    assert "verification did not pass" in res.message


def test_close_thread_successful_flow(
    thread_service: ThreadService,
    verification_service: VerificationService,
    lifecycle_service: LifecycleService,
) -> None:
    """Verified thread is safely closed, status updated to COMPLETED, and event logged."""
    thread_id = "thread-university-application"

    # Step 1: Add new evidence resolving recommendation letter blocker
    thread_service.add_evidence(
        thread_id,
        Evidence(
            id="evi-uni-3",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed",
            source="Portal",
            created_at=_NOW,
            confidence=0.95,
        ),
    )

    # Step 2: Verify completion
    ver = verification_service.verify_thread(thread_id, reference_time=_NOW)
    assert ver.verified is True

    # Step 3: Close thread
    close_res = lifecycle_service.close_thread(thread_id, reference_time=_NOW)
    assert close_res.closure_status == ClosureStatus.COMPLETED
    assert close_res.status == ThreadStatus.COMPLETED

    # Step 4: Verify thread state in repository
    updated_thread = thread_service.get_thread(thread_id)
    assert updated_thread.status == ThreadStatus.COMPLETED

    # Step 5: Verify auditable THREAD_COMPLETED event
    events = thread_service.get_events(thread_id)
    completed_events = [
        e for e in events if e.event_type == ThreadEventType.THREAD_COMPLETED
    ]
    assert len(completed_events) == 1
    assert completed_events[0].id == close_res.event_id


def test_close_thread_idempotency(
    thread_service: ThreadService,
    verification_service: VerificationService,
    lifecycle_service: LifecycleService,
) -> None:
    """Calling close_thread on already completed thread is idempotent and does not create duplicate events."""
    thread_id = "thread-university-application"
    thread_service.add_evidence(
        thread_id,
        Evidence(
            id="evi-uni-3",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed",
            source="Portal",
            created_at=_NOW,
            confidence=0.95,
        ),
    )
    verification_service.verify_thread(thread_id, reference_time=_NOW)

    # First closure
    first_res = lifecycle_service.close_thread(thread_id, reference_time=_NOW)
    assert first_res.closure_status == ClosureStatus.COMPLETED
    events_count_1 = len(thread_service.get_events(thread_id))

    # Second closure
    second_res = lifecycle_service.close_thread(thread_id, reference_time=_NOW)
    assert second_res.closure_status == ClosureStatus.ALREADY_COMPLETED
    assert second_res.status == ThreadStatus.COMPLETED
    events_count_2 = len(thread_service.get_events(thread_id))

    # Ensure no duplicate completion event was recorded
    assert events_count_1 == events_count_2


def test_close_thread_abandoned_thread_rejected(
    lifecycle_service: LifecycleService,
) -> None:
    """Abandoned thread cannot be closed."""
    res = lifecycle_service.close_thread("thread-old-gym-membership")
    assert res.closure_status == ClosureStatus.REJECTED
    assert "ABANDONED" in res.message


def test_close_thread_unknown_raises_not_found(
    lifecycle_service: LifecycleService,
) -> None:
    """Nonexistent thread raises ThreadNotFoundError."""
    with pytest.raises(ThreadNotFoundError):
        lifecycle_service.close_thread("thread-unknown-999")
