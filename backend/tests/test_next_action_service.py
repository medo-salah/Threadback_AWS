"""
Unit tests for NextActionService (Threadback M5).

Tests cover:
  - DIRECT_NEXT_ACTION on actionable threads
  - UNBLOCKER_ACTION on blocked threads (University Application)
  - FOLLOW_UP_ACTION on waiting threads (Client Report)
  - GATHER_EVIDENCE_ACTION when evidence is insufficient
  - NO_ACTION on completed/abandoned threads (Tax Filing 2025)
  - Determinism across multiple executions
  - Deterministic tie-breaking for blockers and commitments
  - Supporting source IDs correspondence
  - Confidence bounding and validity
  - Confirmation requirement flags
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    NextActionType,
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
from app.services.analysis_service import AnalysisService
from app.services.next_action_service import NextActionService

# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
_RECENT = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def analysis_service() -> AnalysisService:
    return AnalysisService()


@pytest.fixture
def service(analysis_service: AnalysisService) -> NextActionService:
    return NextActionService(analysis_service)


def _make_evidence(
    eid: str = "evi-1",
    confidence: float = 0.90,
    created_at: datetime = _RECENT,
    etype: EvidenceType = EvidenceType.CONVERSATION,
    description: str = "Evidence description",
) -> Evidence:
    return Evidence(
        id=eid,
        type=etype,
        description=description,
        source="test",
        created_at=created_at,
        confidence=confidence,
    )


def _make_thread(
    *,
    thread_id: str = "thread-test",
    title: str = "Test Thread",
    description: str = "A test thread",
    status: ThreadStatus = ThreadStatus.ACTIVE,
    priority: Priority = Priority.MEDIUM,
    confidence: float = 0.85,
    commitments: list[Commitment] | None = None,
    evidence: list[Evidence] | None = None,
    dependencies: list[Dependency] | None = None,
    events: list[Event] | None = None,
) -> IntentThread:
    return IntentThread(
        id=thread_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        created_at=_NOW,
        updated_at=_NOW,
        last_activity_at=_NOW,
        confidence=confidence,
        commitments=commitments or [],
        evidence=evidence or [],
        dependencies=dependencies or [],
        events=events or [],
    )


# ---------------------------------------------------------------------------
# 1. Active Blocker → UNBLOCKER_ACTION
# ---------------------------------------------------------------------------


def test_suggest_action_university_application_unblocker(
    service: NextActionService,
) -> None:
    """University Application must recommend UNBLOCKER_ACTION for recommendation letter."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")

    suggestion = service.suggest_action(uni, reference_time=_NOW)

    assert suggestion.thread_id == "thread-university-application"
    assert suggestion.action_type == NextActionType.UNBLOCKER_ACTION
    assert "recommendation letter" in suggestion.action.lower()
    assert "dep-uni-rec-letter" in suggestion.supporting_dependency_ids
    assert len(suggestion.supporting_evidence_ids) > 0
    assert 0.0 <= suggestion.confidence <= 1.0
    assert (
        suggestion.requires_confirmation is True
    )  # Involves contacting Ahmed (PERSON)
    assert len(suggestion.preconditions) > 0


# ---------------------------------------------------------------------------
# 2. Waiting Dependency → FOLLOW_UP_ACTION
# ---------------------------------------------------------------------------


def test_suggest_action_client_report_follow_up(service: NextActionService) -> None:
    """Client Report in WAITING status must recommend FOLLOW_UP_ACTION."""
    threads = get_demo_threads()
    client_rep = next(t for t in threads if t.id == "thread-client-report")

    suggestion = service.suggest_action(client_rep, reference_time=_NOW)

    assert suggestion.thread_id == "thread-client-report"
    assert suggestion.action_type == NextActionType.FOLLOW_UP_ACTION
    assert "follow up" in suggestion.action.lower()
    assert "dep-client-response" in suggestion.supporting_dependency_ids
    assert 0.0 <= suggestion.confidence <= 1.0
    assert suggestion.requires_confirmation is True  # External client follow-up


# ---------------------------------------------------------------------------
# 3. Actionable Thread → DIRECT_NEXT_ACTION
# ---------------------------------------------------------------------------


def test_suggest_action_aws_hackathon_direct_action(
    service: NextActionService,
) -> None:
    """AWS Hackathon (ACTIVE, unblocked) must recommend DIRECT_NEXT_ACTION for commitment."""
    threads = get_demo_threads()
    aws = next(t for t in threads if t.id == "thread-aws-hackathon")

    suggestion = service.suggest_action(aws, reference_time=_NOW)

    assert suggestion.thread_id == "thread-aws-hackathon"
    assert suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert "m3" in suggestion.action.lower()
    assert "com-aws-m3" in suggestion.supporting_commitment_ids
    assert 0.0 <= suggestion.confidence <= 1.0


def test_suggest_action_dentist_appointment_insufficient_evidence(
    service: NextActionService,
) -> None:
    """Dentist appointment has only 1 evidence item (insufficient in M4), so recommends GATHER_EVIDENCE_ACTION."""
    threads = get_demo_threads()
    dentist = next(t for t in threads if t.id == "thread-dentist-appointment")

    suggestion = service.suggest_action(dentist, reference_time=_NOW)

    assert suggestion.thread_id == "thread-dentist-appointment"
    assert suggestion.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert "gather" in suggestion.action.lower()


def test_suggest_action_active_thread_with_sufficient_evidence_direct_action(
    service: NextActionService,
) -> None:
    """Active thread with >= 2 evidence items and open commitment recommends DIRECT_NEXT_ACTION."""
    thread = _make_thread(
        status=ThreadStatus.ACTIVE,
        confidence=0.90,
        evidence=[
            _make_evidence("e1", confidence=0.95),
            _make_evidence("e2", confidence=0.90),
        ],
        commitments=[
            Commitment(
                id="c-call",
                description="Call client to confirm schedule",
                status=CommitmentStatus.OPEN,
            )
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert suggestion.action == "Call client to confirm schedule"
    assert "c-call" in suggestion.supporting_commitment_ids
    assert suggestion.requires_confirmation is True


# ---------------------------------------------------------------------------
# 4. Insufficient Evidence → GATHER_EVIDENCE_ACTION
# ---------------------------------------------------------------------------


def test_suggest_action_insufficient_evidence(service: NextActionService) -> None:
    """Thread with insufficient evidence and no blocker must recommend GATHER_EVIDENCE_ACTION."""
    thread = _make_thread(
        title="Vague Thread",
        confidence=0.50,
        evidence=[],  # 0 evidence items
        commitments=[
            Commitment(
                id="c-vague",
                description="Think about doing something",
                status=CommitmentStatus.OPEN,
            )
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert "gather" in suggestion.action.lower()
    assert suggestion.requires_confirmation is False  # Internal gathering


def test_gather_evidence_action_confidence_formula(
    service: NextActionService,
) -> None:
    """
    Authorized formula: C_action = max(0.30, min(0.60, C_analysis)).

    Verifies:
      - values below 0.30 -> 0.30
      - values between 0.30 and 0.60 -> unchanged
      - values above 0.60 -> 0.60
    """
    # 1. Below 0.30 -> clamped to 0.30
    thread_low = _make_thread(
        confidence=0.15,
        evidence=[],  # 0 evidence items -> analysis.confidence is 0.075 (< 0.30)
    )
    sug_low = service.suggest_action(thread_low, reference_time=_NOW)
    assert sug_low.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert sug_low.confidence == 0.30

    # 2. Between 0.30 and 0.60 -> unchanged
    thread_mid = _make_thread(
        confidence=0.90,
        evidence=[],  # 0 evidence items -> analysis.confidence is 0.45 (in [0.30, 0.60])
    )
    sug_mid = service.suggest_action(thread_mid, reference_time=_NOW)
    assert sug_mid.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert sug_mid.confidence == 0.45

    # 3. Above 0.60 -> clamped to 0.60
    thread_high = _make_thread(
        confidence=0.95,
        evidence=[
            _make_evidence(
                "e1", confidence=0.95
            ),  # 1 evidence item -> insufficient (<2), analysis.confidence is 0.95 (> 0.60)
        ],
    )
    sug_high = service.suggest_action(thread_high, reference_time=_NOW)
    assert sug_high.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert sug_high.confidence == 0.60


# ---------------------------------------------------------------------------
# 5. Terminal Threads → NO_ACTION
# ---------------------------------------------------------------------------


def test_suggest_action_completed_thread_no_action(
    service: NextActionService,
) -> None:
    """Completed thread (Tax Filing 2025) must return NO_ACTION."""
    threads = get_demo_threads()
    tax = next(t for t in threads if t.id == "thread-tax-filing-2025")

    suggestion = service.suggest_action(tax, reference_time=_NOW)

    assert suggestion.thread_id == "thread-tax-filing-2025"
    assert suggestion.action_type == NextActionType.NO_ACTION
    assert "no action" in suggestion.action.lower()
    assert suggestion.confidence == 1.0
    assert suggestion.requires_confirmation is False


def test_suggest_action_abandoned_thread_no_action(
    service: NextActionService,
) -> None:
    """Abandoned thread must return NO_ACTION."""
    threads = get_demo_threads()
    gym = next(t for t in threads if t.id == "thread-old-gym-membership")

    suggestion = service.suggest_action(gym, reference_time=_NOW)

    assert suggestion.thread_id == "thread-old-gym-membership"
    assert suggestion.action_type == NextActionType.NO_ACTION
    assert "no action" in suggestion.action.lower()
    assert suggestion.confidence == 1.0


# ---------------------------------------------------------------------------
# 6. Unfinished Thread Without Explicit Commitments or Blockers
# ---------------------------------------------------------------------------


def test_suggest_action_thread_level_review(service: NextActionService) -> None:
    """Active thread with sufficient evidence but no commitments or blockers gets review action."""
    thread = _make_thread(
        status=ThreadStatus.ACTIVE,
        confidence=0.85,
        evidence=[
            _make_evidence("e1", confidence=0.90),
            _make_evidence("e2", confidence=0.85),
        ],
        commitments=[],
        dependencies=[],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert "review" in suggestion.action.lower()
    assert suggestion.requires_confirmation is False


# ---------------------------------------------------------------------------
# 7. Determinism Tests
# ---------------------------------------------------------------------------


def test_suggest_action_determinism(service: NextActionService) -> None:
    """Repeated calls with identical thread state produce identical suggestions."""
    threads = get_demo_threads()
    for thread in threads:
        s1 = service.suggest_action(thread, reference_time=_NOW)
        s2 = service.suggest_action(thread, reference_time=_NOW)
        assert s1.model_dump() == s2.model_dump(), f"Non-deterministic for {thread.id}"


# ---------------------------------------------------------------------------
# 8. Deterministic Tie-Breaking Tests
# ---------------------------------------------------------------------------


def test_tie_breaking_blockers_commitment_overlap(
    service: NextActionService,
) -> None:
    """Blocker related to an open commitment is prioritized over an unrelated blocker."""
    thread = _make_thread(
        status=ThreadStatus.BLOCKED,
        evidence=[
            _make_evidence("e1", description="General evidence 1"),
            _make_evidence("e2", description="General evidence 2"),
        ],
        commitments=[
            Commitment(
                id="c-submit",
                description="Submit thesis draft to committee",
                status=CommitmentStatus.OPEN,
            )
        ],
        dependencies=[
            Dependency(
                id="dep-z-unrelated",
                description="Order new stationery supplies",
                type="VENDOR",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="dep-a-related",
                description="Advisor sign-off on thesis draft",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.UNBLOCKER_ACTION
    # Must select dep-a-related because of 'thesis draft' overlap with commitment
    assert "dep-a-related" in suggestion.supporting_dependency_ids


def test_tie_breaking_blockers_evidence_count(service: NextActionService) -> None:
    """When blockers have no commitment overlap, blocker with more supporting evidence is selected."""
    thread = _make_thread(
        status=ThreadStatus.BLOCKED,
        evidence=[
            _make_evidence("e1", description="Evidence regarding server migration"),
            _make_evidence("e2", description="Additional notes on server migration"),
        ],
        commitments=[],
        dependencies=[
            Dependency(
                id="dep-server",
                description="Server migration access",
                type="SYSTEM",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="dep-hardware",
                description="Hardware procurement",
                type="VENDOR",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.UNBLOCKER_ACTION
    # dep-server matches 2 evidence items, dep-hardware matches 0
    assert "dep-server" in suggestion.supporting_dependency_ids


def test_tie_breaking_blockers_stable_id(service: NextActionService) -> None:
    """When blockers have equal overlap and equal evidence count, tie breaks on dependency_id ascending."""
    thread = _make_thread(
        status=ThreadStatus.BLOCKED,
        evidence=[
            _make_evidence("e1", description="General evidence 1"),
            _make_evidence("e2", description="General evidence 2"),
        ],
        commitments=[],
        dependencies=[
            Dependency(
                id="dep-zebra",
                description="Zebra requirement",
                type="SYSTEM",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="dep-alpha",
                description="Alpha requirement",
                type="SYSTEM",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.UNBLOCKER_ACTION
    assert "dep-alpha" in suggestion.supporting_dependency_ids


def test_tie_breaking_waiting_dependencies_evidence_match_count(
    service: NextActionService,
) -> None:
    """Waiting dependencies break ties using evidence match count descending."""
    thread = _make_thread(
        status=ThreadStatus.WAITING,
        evidence=[
            _make_evidence(
                "e1", description="Email sent to client about budget approval"
            ),
            _make_evidence(
                "e2", description="Follow-up note on client budget approval"
            ),
        ],
        commitments=[],
        dependencies=[
            Dependency(
                id="dep-client-budget",
                description="Client budget approval",
                type="CLIENT",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
            Dependency(
                id="dep-security-review",
                description="Security audit review",
                type="SYSTEM",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.FOLLOW_UP_ACTION
    # dep-client-budget matches 2 evidence items, dep-security-review matches 0
    assert "dep-client-budget" in suggestion.supporting_dependency_ids


def test_tie_breaking_waiting_dependencies_stable_id(
    service: NextActionService,
) -> None:
    """Waiting dependencies with equal evidence matches break ties using id ascending."""
    thread = _make_thread(
        status=ThreadStatus.WAITING,
        evidence=[
            _make_evidence("e1", description="Neutral evidence 1"),
            _make_evidence("e2", description="Neutral evidence 2"),
        ],
        commitments=[],
        dependencies=[
            Dependency(
                id="dep-zebra-response",
                description="Pending zebra response",
                type="CLIENT",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
            Dependency(
                id="dep-alpha-response",
                description="Pending alpha response",
                type="CLIENT",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.FOLLOW_UP_ACTION
    assert "dep-alpha-response" in suggestion.supporting_dependency_ids


def test_tie_breaking_commitments_earliest_due_date(
    service: NextActionService,
) -> None:
    """Commitment with earlier due_at is prioritized over later due_at."""
    due_early = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    due_late = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

    thread = _make_thread(
        status=ThreadStatus.ACTIVE,
        evidence=[
            _make_evidence("e1"),
            _make_evidence("e2"),
        ],
        commitments=[
            Commitment(
                id="c-late",
                description="Final project submission",
                status=CommitmentStatus.OPEN,
                due_at=due_late,
            ),
            Commitment(
                id="c-early",
                description="Draft initial outline",
                status=CommitmentStatus.OPEN,
                due_at=due_early,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert suggestion.action == "Draft initial outline"
    assert "c-early" in suggestion.supporting_commitment_ids


def test_tie_breaking_commitments_stable_id_when_no_due_date(
    service: NextActionService,
) -> None:
    """Commitments without due dates break ties using lexicographical ID."""
    thread = _make_thread(
        status=ThreadStatus.ACTIVE,
        evidence=[
            _make_evidence("e1"),
            _make_evidence("e2"),
        ],
        commitments=[
            Commitment(
                id="c-zebra",
                description="Task Zebra",
                status=CommitmentStatus.OPEN,
                due_at=None,
            ),
            Commitment(
                id="c-alpha",
                description="Task Alpha",
                status=CommitmentStatus.OPEN,
                due_at=None,
            ),
        ],
    )

    suggestion = service.suggest_action(thread, reference_time=_NOW)

    assert suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert suggestion.action == "Task Alpha"
    assert "c-alpha" in suggestion.supporting_commitment_ids


# ---------------------------------------------------------------------------
# 9. Source IDs Traceability Test
# ---------------------------------------------------------------------------


def test_supporting_source_ids_correspondence(service: NextActionService) -> None:
    """All returned supporting IDs must exist in the actual domain thread objects."""
    threads = get_demo_threads()
    for thread in threads:
        suggestion = service.suggest_action(thread, reference_time=_NOW)

        # Check evidence IDs
        actual_ev_ids = {e.id for e in thread.evidence}
        for eid in suggestion.supporting_evidence_ids:
            assert eid in actual_ev_ids

        # Check commitment IDs
        actual_comm_ids = {c.id for c in thread.commitments}
        for cid in suggestion.supporting_commitment_ids:
            assert cid in actual_comm_ids

        # Check dependency IDs
        actual_dep_ids = {d.id for d in thread.dependencies}
        for did in suggestion.supporting_dependency_ids:
            assert did in actual_dep_ids


# ---------------------------------------------------------------------------
# 10. Decision Precedence & Overlapping Conditions Test
# ---------------------------------------------------------------------------


def test_decision_precedence_overlapping_conditions(
    service: NextActionService,
) -> None:
    """
    Verifies the authorized M5 decision order when conditions overlap:
        1. Insufficient evidence
        2. Active blocking dependency
        3. Waiting dependency
        4. Open actionable commitment
        5. Thread-level action
        6. No action
    """
    due = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Insufficient evidence beats Active Blocker, Waiting, and Commitment
    t_overlap_1 = _make_thread(
        status=ThreadStatus.BLOCKED,
        evidence=[
            _make_evidence("e1")
        ],  # 1 evidence item -> is_sufficient == False (<2)
        commitments=[
            Commitment(
                id="c1", description="Do work", status=CommitmentStatus.OPEN, due_at=due
            )
        ],
        dependencies=[
            Dependency(
                id="d1",
                description="Blocker A",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="d2",
                description="Waiting B",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ],
    )
    s1 = service.suggest_action(t_overlap_1, reference_time=_NOW)
    assert s1.action_type == NextActionType.GATHER_EVIDENCE_ACTION

    # 2. Sufficient evidence: Active Blocker beats Waiting and Commitment
    t_overlap_2 = _make_thread(
        status=ThreadStatus.BLOCKED,
        evidence=[
            _make_evidence("e1"),
            _make_evidence("e2"),
        ],  # 2 items -> is_sufficient == True
        commitments=[
            Commitment(
                id="c1", description="Do work", status=CommitmentStatus.OPEN, due_at=due
            )
        ],
        dependencies=[
            Dependency(
                id="d1",
                description="Blocker A",
                status=DependencyStatus.OPEN,
                blocking=True,
            ),
            Dependency(
                id="d2",
                description="Waiting B",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ],
    )
    s2 = service.suggest_action(t_overlap_2, reference_time=_NOW)
    assert s2.action_type == NextActionType.UNBLOCKER_ACTION
    assert "d1" in s2.supporting_dependency_ids

    # 3. Sufficient evidence, no active blocker: Waiting dependency beats Open Commitment
    t_overlap_3 = _make_thread(
        status=ThreadStatus.WAITING,
        evidence=[_make_evidence("e1"), _make_evidence("e2")],
        commitments=[
            Commitment(
                id="c1", description="Do work", status=CommitmentStatus.OPEN, due_at=due
            )
        ],
        dependencies=[
            Dependency(
                id="d2",
                description="Waiting on response",
                status=DependencyStatus.OPEN,
                blocking=False,
            ),
        ],
    )
    s3 = service.suggest_action(t_overlap_3, reference_time=_NOW)
    assert s3.action_type == NextActionType.FOLLOW_UP_ACTION
    assert "d2" in s3.supporting_dependency_ids

    # 4. Sufficient evidence, no active blocker, not waiting: Open Commitment produces DIRECT_NEXT_ACTION
    t_overlap_4 = _make_thread(
        status=ThreadStatus.ACTIVE,
        evidence=[_make_evidence("e1"), _make_evidence("e2")],
        commitments=[
            Commitment(
                id="c1",
                description="Execute core task",
                status=CommitmentStatus.OPEN,
                due_at=due,
            )
        ],
        dependencies=[],
    )
    s4 = service.suggest_action(t_overlap_4, reference_time=_NOW)
    assert s4.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert "c1" in s4.supporting_commitment_ids

    # 5. Sufficient evidence, no blocker, not waiting, no commitment: Thread-level milestone review
    t_overlap_5 = _make_thread(
        status=ThreadStatus.ACTIVE,
        evidence=[_make_evidence("e1"), _make_evidence("e2")],
        commitments=[],
        dependencies=[],
    )
    s5 = service.suggest_action(t_overlap_5, reference_time=_NOW)
    assert s5.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert "review" in s5.action.lower()

    # 6. Terminal thread (COMPLETED): NO_ACTION
    t_overlap_6 = _make_thread(
        status=ThreadStatus.COMPLETED,
        evidence=[_make_evidence("e1"), _make_evidence("e2")],
        commitments=[
            Commitment(id="c1", description="Old work", status=CommitmentStatus.OPEN)
        ],
        dependencies=[
            Dependency(
                id="d1",
                description="Old blocker",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
    )
    s6 = service.suggest_action(t_overlap_6, reference_time=_NOW)
    assert s6.action_type == NextActionType.NO_ACTION

    # 7. Terminal thread (ABANDONED): NO_ACTION
    t_overlap_7 = _make_thread(
        status=ThreadStatus.ABANDONED,
        evidence=[],
    )
    s7 = service.suggest_action(t_overlap_7, reference_time=_NOW)
    assert s7.action_type == NextActionType.NO_ACTION
