"""
Domain tests for Threadback M3.

Verifies:
  - IntentThread validation and domain structure
  - Status enums and values
  - Evidence and IntentThread confidence validation [0.0, 1.0]
  - Demo dataset completeness (all 4 required scenarios)
  - Stable, deterministic IDs and attributes
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    Priority,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Event,
    Evidence,
    IntentThread,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Enum verification
# ---------------------------------------------------------------------------


def test_thread_status_enum_values() -> None:
    """Status enum must contain the approved Threadback statuses including M13 DEFERRED."""
    expected = {
        "DISCOVERED",
        "ACTIVE",
        "BLOCKED",
        "WAITING",
        "DEFERRED",
        "COMPLETED",
        "ABANDONED",
    }
    actual = {s.value for s in ThreadStatus}
    assert actual == expected


def test_supporting_enums() -> None:
    """Verify CommitmentStatus, EvidenceType, DependencyStatus, Priority enums."""
    assert {s.value for s in CommitmentStatus} == {"OPEN", "COMPLETED", "CANCELLED"}
    assert {s.value for s in EvidenceType} == {
        "CONVERSATION",
        "DOCUMENT",
        "CALENDAR",
        "NOTE",
        "MESSAGE",
        "USER_ACTION",
    }
    assert {s.value for s in DependencyStatus} == {"OPEN", "RESOLVED", "UNKNOWN"}
    assert {s.value for s in Priority} == {"HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# Domain Model Validation
# ---------------------------------------------------------------------------


def test_intent_thread_valid_construction() -> None:
    """IntentThread constructs and validates with all required fields."""
    now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    thread = IntentThread(
        id="thread-test-1",
        title="Test Intent",
        description="Testing domain model validation",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        created_at=now,
        updated_at=now,
        last_activity_at=now,
        confidence=0.85,
        commitments=[
            Commitment(
                id="com-1",
                description="A test commitment",
                status=CommitmentStatus.OPEN,
                due_at=now,
            )
        ],
        evidence=[
            Evidence(
                id="evi-1",
                type=EvidenceType.NOTE,
                description="A note evidence",
                source="Notes app",
                created_at=now,
                confidence=0.90,
            )
        ],
        dependencies=[
            Dependency(
                id="dep-1",
                description="A blocking dependency",
                type="SYSTEM",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        events=[
            Event(
                id="evt-1",
                type="CREATED",
                description="Thread created",
                timestamp=now,
            )
        ],
    )
    assert thread.id == "thread-test-1"
    assert thread.status == ThreadStatus.ACTIVE
    assert len(thread.commitments) == 1
    assert len(thread.evidence) == 1
    assert len(thread.dependencies) == 1
    assert len(thread.events) == 1
    assert len(thread.active_blockers) == 1
    assert thread.open_commitments_count == 1


def test_evidence_confidence_validation() -> None:
    """Evidence confidence must be between 0.0 and 1.0."""
    now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

    # Valid boundary values
    e0 = Evidence(
        id="e0",
        type=EvidenceType.NOTE,
        description="min",
        source="test",
        created_at=now,
        confidence=0.0,
    )
    assert e0.confidence == 0.0

    e1 = Evidence(
        id="e1",
        type=EvidenceType.NOTE,
        description="max",
        source="test",
        created_at=now,
        confidence=1.0,
    )
    assert e1.confidence == 1.0

    # Invalid: < 0.0
    with pytest.raises(ValidationError):
        Evidence(
            id="e_neg",
            type=EvidenceType.NOTE,
            description="neg",
            source="test",
            created_at=now,
            confidence=-0.1,
        )

    # Invalid: > 1.0
    with pytest.raises(ValidationError):
        Evidence(
            id="e_high",
            type=EvidenceType.NOTE,
            description="high",
            source="test",
            created_at=now,
            confidence=1.05,
        )


def test_intent_thread_confidence_validation() -> None:
    """IntentThread confidence must be between 0.0 and 1.0."""
    now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    base_kwargs = {
        "id": "thread-val",
        "title": "Val",
        "description": "Val",
        "status": ThreadStatus.ACTIVE,
        "priority": Priority.MEDIUM,
        "created_at": now,
        "updated_at": now,
        "last_activity_at": now,
    }

    with pytest.raises(ValidationError):
        IntentThread(**base_kwargs, confidence=-0.5)

    with pytest.raises(ValidationError):
        IntentThread(**base_kwargs, confidence=1.5)


def test_dependency_active_blocker_logic() -> None:
    """Dependency is an active blocker ONLY when blocking=True AND status=OPEN."""
    d_open_blocking = Dependency(
        id="d1",
        description="blocking and open",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    assert d_open_blocking.is_active_blocker is True

    d_resolved_blocking = Dependency(
        id="d2",
        description="blocking but resolved",
        status=DependencyStatus.RESOLVED,
        blocking=True,
    )
    assert d_resolved_blocking.is_active_blocker is False

    d_open_nonblocking = Dependency(
        id="d3",
        description="open but non-blocking",
        status=DependencyStatus.OPEN,
        blocking=False,
    )
    assert d_open_nonblocking.is_active_blocker is False


# ---------------------------------------------------------------------------
# Demo Dataset Tests
# ---------------------------------------------------------------------------


def test_demo_dataset_contains_four_required_scenarios() -> None:
    """The demo dataset must contain all four required scenarios from M0/M3."""
    threads = get_demo_threads()
    thread_map = {t.id: t for t in threads}

    required_ids = {
        "thread-university-application",
        "thread-client-report",
        "thread-dentist-appointment",
        "thread-aws-hackathon",
    }
    assert required_ids.issubset(set(thread_map.keys())), (
        f"Missing required threads: {required_ids - set(thread_map.keys())}"
    )


def test_scenario_university_application() -> None:
    """
    Scenario: University Application.
    status: BLOCKED, priority: HIGH, blocker: recommendation letter from Ahmed, due Oct 12.
    """
    thread = next(
        t for t in get_demo_threads() if t.id == "thread-university-application"
    )
    assert thread.status == ThreadStatus.BLOCKED
    assert thread.priority == Priority.HIGH
    assert 0.90 <= thread.confidence <= 1.0  # Strong confidence band

    # Blocker check
    assert len(thread.active_blockers) == 1
    blocker = thread.active_blockers[0]
    assert blocker.blocking is True
    assert blocker.status == DependencyStatus.OPEN
    assert (
        "Ahmed" in blocker.description
        or "recommendation" in blocker.description.lower()
    )

    # Due date check
    due_dates = [c.due_at for c in thread.commitments if c.due_at is not None]
    assert any(d.month == 10 and d.day == 12 for d in due_dates)


def test_scenario_client_report() -> None:
    """
    Scenario: Client Report.
    status: WAITING, priority: MEDIUM, blocker/dependency: client response.
    """
    thread = next(t for t in get_demo_threads() if t.id == "thread-client-report")
    assert thread.status == ThreadStatus.WAITING
    assert thread.priority == Priority.MEDIUM
    assert 0.75 <= thread.confidence <= 0.89  # Good confidence band

    # Blocker/dependency check
    assert len(thread.active_blockers) == 1
    blocker = thread.active_blockers[0]
    assert blocker.blocking is True
    assert blocker.status == DependencyStatus.OPEN
    assert "client" in blocker.description.lower()


def test_scenario_dentist_appointment() -> None:
    """
    Scenario: Dentist Appointment.
    status: ACTIVE, priority: MEDIUM.
    """
    thread = next(t for t in get_demo_threads() if t.id == "thread-dentist-appointment")
    assert thread.status == ThreadStatus.ACTIVE
    assert thread.priority == Priority.MEDIUM
    assert 0.75 <= thread.confidence <= 0.89  # Good confidence band
    assert len(thread.active_blockers) == 0


def test_scenario_aws_hackathon() -> None:
    """
    Scenario: AWS Hackathon.
    status: ACTIVE, priority: HIGH.
    """
    thread = next(t for t in get_demo_threads() if t.id == "thread-aws-hackathon")
    assert thread.status == ThreadStatus.ACTIVE
    assert thread.priority == Priority.HIGH
    assert 0.90 <= thread.confidence <= 1.0  # Strong confidence band
    assert len(thread.active_blockers) == 0


def test_demo_dataset_ids_are_stable_and_deterministic() -> None:
    """Calling get_demo_threads repeatedly must return identical IDs and data."""
    run1 = get_demo_threads()
    run2 = get_demo_threads()

    assert len(run1) == len(run2)
    for t1, t2 in zip(run1, run2, strict=True):
        assert t1.id == t2.id
        assert t1.title == t2.title
        assert t1.status == t2.status
        assert t1.priority == t2.priority
        assert t1.confidence == t2.confidence
        assert t1.created_at == t2.created_at
        assert len(t1.commitments) == len(t2.commitments)
        assert len(t1.dependencies) == len(t2.dependencies)
