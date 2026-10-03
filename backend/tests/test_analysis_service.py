"""
Analysis service tests for Threadback M4.

Verifies:
  - Basic analysis for all thread states (active, blocked, waiting, completed, abandoned)
  - Evidence aggregation (no evidence, single, multiple, mixed types, strong, weak, stale)
  - Confidence bands (STRONG, GOOD, UNCERTAIN, WEAK) and exact boundaries
  - Commitment analysis (none, one open, multiple open, completed excluded)
  - Blocker analysis (none, one, multiple, resolved excluded)
  - Priority / attention signal determinism
  - Determinism guarantee (identical input -> identical output)
  - Unknown thread error propagation
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    AttentionLevel,
    CommitmentStatus,
    ConfidenceBand,
    DependencyStatus,
    EvidenceType,
    Priority,
    ThreadStatus,
    UnfinishedReason,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Event,
    Evidence,
    IntentThread,
)
from app.services.analysis_service import (
    AnalysisService,
    aggregate_evidence,
    classify_confidence,
    classify_unfinished_reasons,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
_RECENT = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
_OLD = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)  # ~89 days ago


@pytest.fixture
def service() -> AnalysisService:
    return AnalysisService()


def _make_thread(
    *,
    thread_id: str = "thread-test",
    title: str = "Test Thread",
    description: str = "A test thread",
    status: ThreadStatus = ThreadStatus.ACTIVE,
    priority: Priority = Priority.MEDIUM,
    confidence: float = 0.80,
    commitments: list[Commitment] | None = None,
    evidence: list[Evidence] | None = None,
    dependencies: list[Dependency] | None = None,
    events: list[Event] | None = None,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
    last_activity_at: datetime = _NOW,
) -> IntentThread:
    return IntentThread(
        id=thread_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        created_at=created_at,
        updated_at=updated_at,
        last_activity_at=last_activity_at,
        confidence=confidence,
        commitments=commitments or [],
        evidence=evidence or [],
        dependencies=dependencies or [],
        events=events or [],
    )


def _make_evidence(
    eid: str = "evi-1",
    confidence: float = 0.90,
    created_at: datetime = _RECENT,
    etype: EvidenceType = EvidenceType.CONVERSATION,
) -> Evidence:
    return Evidence(
        id=eid,
        type=etype,
        description=f"Evidence {eid}",
        source=f"source-{eid}",
        created_at=created_at,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# A. Basic Analysis Tests
# ---------------------------------------------------------------------------


def test_analyze_active_thread(service: AnalysisService) -> None:
    """Active thread analysis produces correct status and non-empty explanation."""
    thread = _make_thread(status=ThreadStatus.ACTIVE, priority=Priority.HIGH)
    analysis = service.analyze(thread)

    assert analysis.thread_id == "thread-test"
    assert analysis.current_status == ThreadStatus.ACTIVE
    assert len(analysis.explanation) > 0
    assert (
        "actively" in analysis.explanation.lower()
        or "active" in analysis.explanation.lower()
    )
    assert 0.0 <= analysis.confidence <= 1.0


def test_analyze_blocked_thread(service: AnalysisService) -> None:
    """Blocked thread analysis identifies blocking state and blocker details."""
    thread = _make_thread(
        status=ThreadStatus.BLOCKED,
        dependencies=[
            Dependency(
                id="dep-1",
                description="Blocking dependency",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[_make_evidence()],
    )
    analysis = service.analyze(thread)

    assert analysis.current_status == ThreadStatus.BLOCKED
    assert "blocked" in analysis.explanation.lower()
    assert len(analysis.active_blockers) == 1
    assert analysis.active_blockers[0].dependency_id == "dep-1"
    assert UnfinishedReason.ACTIVE_BLOCKER in analysis.unfinished_reasons


def test_analyze_waiting_thread(service: AnalysisService) -> None:
    """Waiting thread analysis identifies waiting state."""
    thread = _make_thread(
        status=ThreadStatus.WAITING,
        dependencies=[
            Dependency(
                id="dep-wait",
                description="Waiting on external input",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[_make_evidence()],
    )
    analysis = service.analyze(thread)

    assert analysis.current_status == ThreadStatus.WAITING
    assert "waiting" in analysis.explanation.lower()
    assert UnfinishedReason.WAITING_ON_DEPENDENCY in analysis.unfinished_reasons


def test_analyze_completed_thread(service: AnalysisService) -> None:
    """Completed thread analysis returns COMPLETED with no unfinished reasons."""
    thread = _make_thread(
        status=ThreadStatus.COMPLETED,
        confidence=0.99,
        commitments=[
            Commitment(
                id="com-done",
                description="Done task",
                status=CommitmentStatus.COMPLETED,
            )
        ],
        evidence=[_make_evidence(confidence=1.0)],
    )
    analysis = service.analyze(thread)

    assert analysis.current_status == ThreadStatus.COMPLETED
    assert "completed" in analysis.explanation.lower()
    assert UnfinishedReason.OPEN_COMMITMENT not in analysis.unfinished_reasons
    assert len(analysis.open_commitments) == 0


def test_analyze_abandoned_thread(service: AnalysisService) -> None:
    """Abandoned thread analysis returns ABANDONED."""
    thread = _make_thread(
        status=ThreadStatus.ABANDONED,
        confidence=0.60,
    )
    analysis = service.analyze(thread)

    assert analysis.current_status == ThreadStatus.ABANDONED
    assert "abandoned" in analysis.explanation.lower()


# ---------------------------------------------------------------------------
# B. Evidence Tests
# ---------------------------------------------------------------------------


def test_evidence_none(service: AnalysisService) -> None:
    """Thread with no evidence has weak confidence and is marked as stale."""
    thread = _make_thread(evidence=[])
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.total == 0
    assert analysis.evidence_summary.confidence == 0.0
    assert analysis.evidence_summary.confidence_band == ConfidenceBand.WEAK
    assert analysis.evidence_summary.is_weak is True
    assert analysis.evidence_summary.is_stale is True
    assert analysis.evidence_summary.is_sufficient is False
    assert analysis.evidence_summary.most_recent_evidence_id is None


def test_evidence_single(service: AnalysisService) -> None:
    """Single evidence item is aggregated correctly."""
    thread = _make_thread(evidence=[_make_evidence(confidence=0.90)])
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.total == 1
    assert analysis.evidence_summary.average_confidence == 0.90
    # Single evidence is not sufficient (min = 2)
    assert analysis.evidence_summary.is_sufficient is False


def test_evidence_multiple(service: AnalysisService) -> None:
    """Multiple evidence items are aggregated correctly."""
    thread = _make_thread(
        evidence=[
            _make_evidence("e1", confidence=0.95, created_at=_RECENT),
            _make_evidence(
                "e2", confidence=0.85, created_at=_RECENT, etype=EvidenceType.DOCUMENT
            ),
        ]
    )
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.total == 2
    assert analysis.evidence_summary.average_confidence == 0.90
    assert analysis.evidence_summary.is_sufficient is True
    assert len(analysis.evidence_summary.by_type) == 2
    assert "CONVERSATION" in analysis.evidence_summary.by_type
    assert "DOCUMENT" in analysis.evidence_summary.by_type


def test_evidence_mixed_types(service: AnalysisService) -> None:
    """Evidence of different types is counted correctly by type."""
    thread = _make_thread(
        evidence=[
            _make_evidence("e1", etype=EvidenceType.CONVERSATION),
            _make_evidence("e2", etype=EvidenceType.DOCUMENT),
            _make_evidence("e3", etype=EvidenceType.NOTE),
            _make_evidence("e4", etype=EvidenceType.CONVERSATION),
        ]
    )
    analysis = service.analyze(thread)

    by_type = analysis.evidence_summary.by_type
    assert by_type["CONVERSATION"] == 2
    assert by_type["DOCUMENT"] == 1
    assert by_type["NOTE"] == 1


def test_evidence_strong(service: AnalysisService) -> None:
    """Strong evidence (all >= 0.90) results in STRONG confidence band."""
    thread = _make_thread(
        evidence=[
            _make_evidence("e1", confidence=0.95, created_at=_RECENT),
            _make_evidence("e2", confidence=0.98, created_at=_RECENT),
        ]
    )
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.confidence_band == ConfidenceBand.STRONG
    assert analysis.evidence_summary.is_weak is False


def test_evidence_weak(service: AnalysisService) -> None:
    """Weak evidence (all < 0.50) results in WEAK confidence band."""
    thread = _make_thread(
        evidence=[
            _make_evidence("e1", confidence=0.30, created_at=_RECENT),
            _make_evidence("e2", confidence=0.20, created_at=_RECENT),
        ]
    )
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.confidence_band == ConfidenceBand.WEAK
    assert analysis.evidence_summary.is_weak is True


def test_evidence_stale(service: AnalysisService) -> None:
    """Evidence older than 30 days from reference is flagged as stale."""
    old_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    thread = _make_thread(
        last_activity_at=_NOW,
        evidence=[_make_evidence("e1", confidence=0.90, created_at=old_time)],
    )
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.is_stale is True


def test_evidence_not_stale(service: AnalysisService) -> None:
    """Recent evidence is not flagged as stale."""
    thread = _make_thread(
        last_activity_at=_NOW,
        evidence=[_make_evidence("e1", confidence=0.90, created_at=_RECENT)],
    )
    analysis = service.analyze(thread)

    assert analysis.evidence_summary.is_stale is False


# ---------------------------------------------------------------------------
# C. Confidence Band Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "expected_band"),
    [
        (1.00, ConfidenceBand.STRONG),
        (0.95, ConfidenceBand.STRONG),
        (0.90, ConfidenceBand.STRONG),
        (0.89, ConfidenceBand.GOOD),
        (0.80, ConfidenceBand.GOOD),
        (0.75, ConfidenceBand.GOOD),
        (0.74, ConfidenceBand.UNCERTAIN),
        (0.60, ConfidenceBand.UNCERTAIN),
        (0.50, ConfidenceBand.UNCERTAIN),
        (0.49, ConfidenceBand.WEAK),
        (0.25, ConfidenceBand.WEAK),
        (0.00, ConfidenceBand.WEAK),
    ],
)
def test_confidence_band_classification(
    confidence: float, expected_band: ConfidenceBand
) -> None:
    """Confidence bands match M0 specification at exact boundaries."""
    assert classify_confidence(confidence) == expected_band


# ---------------------------------------------------------------------------
# D. Commitment Tests
# ---------------------------------------------------------------------------


def test_no_commitments(service: AnalysisService) -> None:
    """Thread with no commitments has empty open_commitments."""
    thread = _make_thread(commitments=[])
    analysis = service.analyze(thread)

    assert len(analysis.open_commitments) == 0
    assert UnfinishedReason.OPEN_COMMITMENT not in analysis.unfinished_reasons


def test_one_open_commitment(service: AnalysisService) -> None:
    """Thread with one open commitment includes it in open_commitments."""
    thread = _make_thread(
        commitments=[
            Commitment(
                id="com-1",
                description="Submit application",
                status=CommitmentStatus.OPEN,
            )
        ]
    )
    analysis = service.analyze(thread)

    assert len(analysis.open_commitments) == 1
    assert "Submit application" in analysis.open_commitments
    assert UnfinishedReason.OPEN_COMMITMENT in analysis.unfinished_reasons


def test_multiple_open_commitments(service: AnalysisService) -> None:
    """Thread with multiple open commitments lists all."""
    thread = _make_thread(
        commitments=[
            Commitment(id="com-1", description="Task A", status=CommitmentStatus.OPEN),
            Commitment(id="com-2", description="Task B", status=CommitmentStatus.OPEN),
            Commitment(
                id="com-3", description="Task C", status=CommitmentStatus.COMPLETED
            ),
        ]
    )
    analysis = service.analyze(thread)

    assert len(analysis.open_commitments) == 2
    assert "Task A" in analysis.open_commitments
    assert "Task B" in analysis.open_commitments
    assert "Task C" not in analysis.open_commitments


def test_completed_commitments_excluded(service: AnalysisService) -> None:
    """Only OPEN commitments appear; COMPLETED and CANCELLED are excluded."""
    thread = _make_thread(
        commitments=[
            Commitment(
                id="com-1", description="Done", status=CommitmentStatus.COMPLETED
            ),
            Commitment(
                id="com-2", description="Cancelled", status=CommitmentStatus.CANCELLED
            ),
        ]
    )
    analysis = service.analyze(thread)

    assert len(analysis.open_commitments) == 0
    assert UnfinishedReason.OPEN_COMMITMENT not in analysis.unfinished_reasons


# ---------------------------------------------------------------------------
# E. Blocker Tests
# ---------------------------------------------------------------------------


def test_no_blockers(service: AnalysisService) -> None:
    """Thread with no blockers has empty active_blockers list."""
    thread = _make_thread(dependencies=[])
    analysis = service.analyze(thread)

    assert len(analysis.active_blockers) == 0
    assert UnfinishedReason.ACTIVE_BLOCKER not in analysis.unfinished_reasons


def test_one_blocker(service: AnalysisService) -> None:
    """Thread with one active blocker identifies it."""
    thread = _make_thread(
        dependencies=[
            Dependency(
                id="dep-1",
                description="Recommendation letter",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[
            _make_evidence("e1", confidence=0.90),
        ],
    )
    analysis = service.analyze(thread)

    assert len(analysis.active_blockers) == 1
    assert analysis.active_blockers[0].dependency_id == "dep-1"
    assert analysis.active_blockers[0].description == "Recommendation letter"
    assert UnfinishedReason.ACTIVE_BLOCKER in analysis.unfinished_reasons


def test_multiple_blockers(service: AnalysisService) -> None:
    """Thread with multiple active blockers identifies all."""
    thread = _make_thread(
        dependencies=[
            Dependency(
                id="dep-1",
                description="Blocker A",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="dep-2",
                description="Blocker B",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
        ]
    )
    analysis = service.analyze(thread)

    assert len(analysis.active_blockers) == 2
    dep_ids = {b.dependency_id for b in analysis.active_blockers}
    assert dep_ids == {"dep-1", "dep-2"}


def test_resolved_dependency_not_active_blocker(service: AnalysisService) -> None:
    """Resolved dependency does not appear as active blocker."""
    thread = _make_thread(
        dependencies=[
            Dependency(
                id="dep-1",
                description="Resolved dep",
                status=DependencyStatus.RESOLVED,
                blocking=True,
            ),
            Dependency(
                id="dep-2",
                description="Non-blocking",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ]
    )
    analysis = service.analyze(thread)

    assert len(analysis.active_blockers) == 0
    assert UnfinishedReason.ACTIVE_BLOCKER not in analysis.unfinished_reasons


# ---------------------------------------------------------------------------
# F. Priority / Attention Signal Tests
# ---------------------------------------------------------------------------


def test_attention_high_priority_with_blocker(service: AnalysisService) -> None:
    """HIGH priority thread with active blocker gets HIGH attention."""
    thread = _make_thread(
        priority=Priority.HIGH,
        commitments=[
            Commitment(id="com-1", description="Task", status=CommitmentStatus.OPEN),
        ],
        dependencies=[
            Dependency(
                id="dep-1",
                description="Blocker",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
        ],
        evidence=[
            _make_evidence("e1", confidence=0.95, created_at=_RECENT),
            _make_evidence("e2", confidence=0.90, created_at=_RECENT),
        ],
        events=[
            Event(
                id="evt-1", type="RECENT", description="Recent event", timestamp=_RECENT
            ),
        ],
    )
    analysis = service.analyze(thread)

    assert analysis.attention.level == AttentionLevel.HIGH
    assert analysis.attention.score >= 0.65
    assert "HIGH priority" in analysis.attention.factors
    assert "ACTIVE blocker" in analysis.attention.factors


def test_attention_low_priority_no_blockers(service: AnalysisService) -> None:
    """LOW priority thread without blockers gets lower attention."""
    thread = _make_thread(
        priority=Priority.LOW,
        evidence=[_make_evidence("e1", confidence=0.50, created_at=_OLD)],
    )
    analysis = service.analyze(thread)

    assert analysis.attention.level in (AttentionLevel.LOW, AttentionLevel.MEDIUM)
    assert analysis.attention.score < 0.65


def test_attention_demo_dataset_university(service: AnalysisService) -> None:
    """University application thread (BLOCKED, HIGH) gets HIGH attention."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")
    analysis = service.analyze(uni)

    assert analysis.attention.level == AttentionLevel.HIGH
    assert "HIGH priority" in analysis.attention.factors
    assert "ACTIVE blocker" in analysis.attention.factors
    assert "OPEN commitment" in analysis.attention.factors


def test_attention_demo_dataset_dentist(service: AnalysisService) -> None:
    """Dentist appointment (ACTIVE, MEDIUM, no blockers) gets MEDIUM attention."""
    threads = get_demo_threads()
    dentist = next(t for t in threads if t.id == "thread-dentist-appointment")
    analysis = service.analyze(dentist)

    assert analysis.attention.level == AttentionLevel.MEDIUM
    assert "MEDIUM priority" in analysis.attention.factors


# ---------------------------------------------------------------------------
# G. Determinism Tests
# ---------------------------------------------------------------------------


def test_analysis_determinism(service: AnalysisService) -> None:
    """Same input produces identical output across multiple runs."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")

    analysis1 = service.analyze(uni)
    analysis2 = service.analyze(uni)

    assert analysis1.model_dump() == analysis2.model_dump()


def test_analysis_determinism_all_demo_threads(service: AnalysisService) -> None:
    """Every demo thread produces identical analysis across runs."""
    threads = get_demo_threads()
    for thread in threads:
        a1 = service.analyze(thread)
        a2 = service.analyze(thread)
        assert a1.model_dump() == a2.model_dump(), f"Non-deterministic for {thread.id}"


# ---------------------------------------------------------------------------
# H. Evidence Aggregation Unit Tests
# ---------------------------------------------------------------------------


def test_aggregate_evidence_empty() -> None:
    """Empty evidence list produces zero-confidence summary."""
    summary = aggregate_evidence([], _NOW)

    assert summary.total == 0
    assert summary.confidence == 0.0
    assert summary.confidence_band == ConfidenceBand.WEAK
    assert summary.is_sufficient is False
    assert summary.is_weak is True


def test_aggregate_evidence_recency_weighting() -> None:
    """Recent evidence receives higher weight than old evidence."""
    recent = _make_evidence("e-recent", confidence=0.80, created_at=_RECENT)
    old = _make_evidence("e-old", confidence=0.80, created_at=_OLD)

    summary_recent = aggregate_evidence([recent], _NOW)
    summary_old = aggregate_evidence([old], _NOW)

    # Same raw confidence, but recent evidence should get higher aggregate
    assert summary_recent.confidence >= summary_old.confidence


def test_aggregate_evidence_strongest_ids() -> None:
    """Strongest evidence IDs are sorted by confidence descending."""
    evs = [
        _make_evidence("e1", confidence=0.70),
        _make_evidence("e2", confidence=0.95),
        _make_evidence("e3", confidence=0.85),
    ]
    summary = aggregate_evidence(evs, _NOW)

    assert summary.strongest_evidence_ids[0] == "e2"
    assert summary.strongest_evidence_ids[1] == "e3"


def test_evidence_staleness_fresh_set() -> None:
    """All evidence items <= 30 days old: neither contains stale nor is entire set stale."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    evs = [
        _make_evidence(
            "e1",
            created_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),  # 3 days old
        _make_evidence(
            "e2",
            created_at=datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        ),  # 18 days old
    ]
    summary = aggregate_evidence(evs, reference_time=ref_time)

    assert summary.is_stale is False  # Entire set is NOT stale
    assert summary.has_stale_evidence is False  # Does not contain stale evidence
    assert summary.stale_evidence_ids == []


def test_evidence_staleness_mixed_set() -> None:
    """Mixed set: contains stale evidence, but entire set is NOT stale."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    ev_fresh = _make_evidence(
        "e-fresh",
        created_at=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )  # 8 days old
    ev_stale = _make_evidence(
        "e-stale",
        created_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )  # 49 days old (> 30 days)

    summary = aggregate_evidence([ev_fresh, ev_stale], reference_time=ref_time)

    assert summary.has_stale_evidence is True  # Contains at least one stale item
    assert (
        summary.is_stale is False
    )  # Entire set is NOT stale because e-fresh is recent
    assert summary.stale_evidence_ids == ["e-stale"]


def test_evidence_staleness_entirely_stale_set() -> None:
    """All evidence items > 30 days old: contains stale AND entire set is stale."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    ev1 = _make_evidence(
        "e-old1",
        created_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
    )  # 44 days old
    ev2 = _make_evidence(
        "e-old2",
        created_at=datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc),
    )  # 70 days old

    summary = aggregate_evidence([ev1, ev2], reference_time=ref_time)

    assert summary.has_stale_evidence is True  # Contains stale items
    assert summary.is_stale is True  # Entire set IS stale
    assert set(summary.stale_evidence_ids) == {"e-old1", "e-old2"}


# ---------------------------------------------------------------------------
# I. Unfinished Reason Classification
# ---------------------------------------------------------------------------


def test_unfinished_reasons_open_commitment() -> None:
    """OPEN_COMMITMENT when at least one commitment is open."""
    thread = _make_thread(
        commitments=[
            Commitment(id="c1", description="Task", status=CommitmentStatus.OPEN),
        ]
    )
    reasons = classify_unfinished_reasons(thread)
    assert UnfinishedReason.OPEN_COMMITMENT in reasons


def test_unfinished_reasons_missing_evidence() -> None:
    """MISSING_REQUIRED_EVIDENCE when fewer than 2 evidence items."""
    thread = _make_thread(evidence=[])
    reasons = classify_unfinished_reasons(thread)
    assert UnfinishedReason.MISSING_REQUIRED_EVIDENCE in reasons

    thread_one = _make_thread(evidence=[_make_evidence()])
    reasons_one = classify_unfinished_reasons(thread_one)
    assert UnfinishedReason.MISSING_REQUIRED_EVIDENCE in reasons_one


def test_unfinished_reasons_sufficient_evidence() -> None:
    """No MISSING_REQUIRED_EVIDENCE when >= 2 evidence items."""
    thread = _make_thread(
        evidence=[
            _make_evidence("e1"),
            _make_evidence("e2"),
        ]
    )
    reasons = classify_unfinished_reasons(thread)
    assert UnfinishedReason.MISSING_REQUIRED_EVIDENCE not in reasons


def test_unfinished_reasons_recent_activity() -> None:
    """RECENT_ACTIVITY when most recent event is within 7 days of reference_time."""
    thread = _make_thread(
        events=[
            Event(id="evt-1", type="TEST", description="Recent", timestamp=_RECENT),
        ],
    )
    reasons = classify_unfinished_reasons(thread, reference_time=_NOW)
    assert UnfinishedReason.RECENT_ACTIVITY in reasons


def test_unfinished_reasons_recent_activity_event_3_days_old() -> None:
    """Event 3 days old relative to reference_time triggers RECENT_ACTIVITY."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    event_time = datetime(
        2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc
    )  # Exactly 3.0 days old
    thread = _make_thread(
        events=[
            Event(
                id="evt-3d",
                type="NOTE",
                description="3 days old",
                timestamp=event_time,
            ),
        ],
    )
    reasons = classify_unfinished_reasons(thread, reference_time=ref_time)
    assert UnfinishedReason.RECENT_ACTIVITY in reasons


def test_unfinished_reasons_no_recent_activity_event_60_days_old() -> None:
    """Event 60 days old relative to reference_time does NOT trigger RECENT_ACTIVITY."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    event_time = datetime(
        2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc
    )  # Exactly 60.0 days old
    thread = _make_thread(
        events=[
            Event(
                id="evt-60d",
                type="NOTE",
                description="60 days old",
                timestamp=event_time,
            ),
        ],
    )
    reasons = classify_unfinished_reasons(thread, reference_time=ref_time)
    assert UnfinishedReason.RECENT_ACTIVITY not in reasons


# ---------------------------------------------------------------------------
# J. Overall Confidence Calculation
# ---------------------------------------------------------------------------


def test_overall_confidence_with_evidence(service: AnalysisService) -> None:
    """Overall confidence blends thread confidence and evidence confidence."""
    thread = _make_thread(
        confidence=0.90,
        evidence=[
            _make_evidence("e1", confidence=0.95, created_at=_RECENT),
            _make_evidence("e2", confidence=0.85, created_at=_RECENT),
        ],
    )
    analysis = service.analyze(thread)

    # overall = 0.6 * 0.90 + 0.4 * evidence_confidence
    # evidence_confidence is weighted average ~ 0.90
    assert 0.85 <= analysis.confidence <= 0.95
    assert 0.0 <= analysis.confidence <= 1.0


def test_overall_confidence_no_evidence(service: AnalysisService) -> None:
    """No evidence degrades confidence by 50%."""
    thread = _make_thread(confidence=0.80, evidence=[])
    analysis = service.analyze(thread)

    # overall = 0.80 * 0.5 = 0.40
    assert analysis.confidence == pytest.approx(0.40, abs=0.01)
    assert analysis.confidence_band == ConfidenceBand.WEAK


def test_overall_confidence_bounded(service: AnalysisService) -> None:
    """Overall confidence is always bounded between 0.0 and 1.0."""
    # High confidence
    thread_high = _make_thread(
        confidence=1.0,
        evidence=[_make_evidence("e1", confidence=1.0)],
    )
    analysis_high = service.analyze(thread_high)
    assert 0.0 <= analysis_high.confidence <= 1.0

    # Low confidence
    thread_low = _make_thread(
        confidence=0.0,
        evidence=[_make_evidence("e1", confidence=0.0)],
    )
    analysis_low = service.analyze(thread_low)
    assert 0.0 <= analysis_low.confidence <= 1.0


# ---------------------------------------------------------------------------
# K. Demo Dataset Analysis Tests
# ---------------------------------------------------------------------------


def test_analyze_university_application(service: AnalysisService) -> None:
    """University application analysis matches expected state."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")
    analysis = service.analyze(uni)

    assert analysis.thread_id == "thread-university-application"
    assert analysis.current_status == ThreadStatus.BLOCKED
    assert UnfinishedReason.OPEN_COMMITMENT in analysis.unfinished_reasons
    assert UnfinishedReason.ACTIVE_BLOCKER in analysis.unfinished_reasons
    assert len(analysis.open_commitments) == 1
    assert len(analysis.active_blockers) == 1
    assert analysis.active_blockers[0].dependency_id == "dep-uni-rec-letter"
    assert analysis.evidence_summary.total == 2
    assert analysis.confidence_band in (ConfidenceBand.STRONG, ConfidenceBand.GOOD)


def test_analyze_aws_hackathon(service: AnalysisService) -> None:
    """AWS hackathon analysis matches expected state."""
    threads = get_demo_threads()
    aws = next(t for t in threads if t.id == "thread-aws-hackathon")
    analysis = service.analyze(aws)

    assert analysis.thread_id == "thread-aws-hackathon"
    assert analysis.current_status == ThreadStatus.ACTIVE
    assert len(analysis.active_blockers) == 0
    assert analysis.evidence_summary.total == 2
    assert analysis.confidence_band in (ConfidenceBand.STRONG, ConfidenceBand.GOOD)
