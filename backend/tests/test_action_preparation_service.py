"""
Unit tests for ActionPreparationService (Threadback M6).

Tests cover:
  - Test 1: Direct action on AWS Hackathon (READY, LOW risk)
  - Test 2: Blocker action on University Application (CONFIRMATION_REQUIRED, MEDIUM risk, recipient Ahmed)
  - Test 3: Waiting action on Client Report (CONFIRMATION_REQUIRED, MEDIUM risk, recipient Acme Corp)
  - Test 4: Evidence gathering on Dentist Appointment (READY, LOW risk)
  - Test 5: No action on Tax Filing 2025 (READY, LOW risk, non-executable)
  - Test 6: Missing required information (BLOCKED status when communication recipient is unknown)
  - Test 7: Confirmation invariant (requires_confirmation == True -> CONFIRMATION_REQUIRED or BLOCKED)
  - Test 8: Traceability (all proposal source IDs originate from M5 suggestion / thread data)
  - Test 9: Determinism (identical inputs yield identical proposals)
  - Test 10: Non-execution guarantee (no external network or execution side effects)
  - Test 11: High risk classification on financial / cancellation actions
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    NextActionType,
    Priority,
    ProposalStatus,
    RiskLevel,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Evidence,
    IntentThread,
    NextActionSuggestion,
)
from app.services.action_preparation_service import (
    ActionPreparationService,
    derive_proposal_id,
)
from app.services.analysis_service import AnalysisService
from app.services.next_action_service import NextActionService

_NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def analysis_service() -> AnalysisService:
    return AnalysisService()


@pytest.fixture
def next_action_service(analysis_service: AnalysisService) -> NextActionService:
    return NextActionService(analysis_service)


@pytest.fixture
def prep_service() -> ActionPreparationService:
    return ActionPreparationService()


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
        events=[],
    )


# ---------------------------------------------------------------------------
# Test 1: Direct Action (AWS Hackathon)
# ---------------------------------------------------------------------------


def test_prepare_action_direct_action_aws_hackathon(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """AWS Hackathon produces a READY, LOW-risk proposal."""
    threads = get_demo_threads()
    aws = next(t for t in threads if t.id == "thread-aws-hackathon")

    suggestion = next_action_service.suggest_action(aws, reference_time=_NOW)
    proposal = prep_service.prepare_action(aws, suggestion, reference_time=_NOW)

    assert proposal.thread_id == "thread-aws-hackathon"
    assert proposal.action_type == NextActionType.DIRECT_NEXT_ACTION
    assert proposal.status == ProposalStatus.READY
    assert proposal.risk_level == RiskLevel.LOW
    assert proposal.requires_confirmation is False
    assert proposal.confirmation_reason is None
    assert "com-aws-m3" in proposal.supporting_commitment_ids
    assert proposal.inputs.get("commitment_id") == "com-aws-m3"
    assert "m3" in proposal.title.lower()


# ---------------------------------------------------------------------------
# Test 2: Blocker Action (University Application)
# ---------------------------------------------------------------------------


def test_prepare_action_blocker_university_application(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """University Application produces an unblocker proposal with CONFIRMATION_REQUIRED and MEDIUM risk."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")

    suggestion = next_action_service.suggest_action(uni, reference_time=_NOW)
    proposal = prep_service.prepare_action(uni, suggestion, reference_time=_NOW)

    assert proposal.thread_id == "thread-university-application"
    assert proposal.action_type == NextActionType.UNBLOCKER_ACTION
    assert proposal.status == ProposalStatus.CONFIRMATION_REQUIRED
    assert proposal.risk_level == RiskLevel.MEDIUM
    assert proposal.requires_confirmation is True
    assert proposal.confirmation_reason is not None
    assert "ahmed" in proposal.confirmation_reason.lower()
    assert proposal.inputs.get("recipient") == "Ahmed"
    assert "dep-uni-rec-letter" in proposal.supporting_dependency_ids
    assert len(proposal.preconditions) > 0


# ---------------------------------------------------------------------------
# Test 3: Waiting Action (Client Report)
# ---------------------------------------------------------------------------


def test_prepare_action_waiting_client_report(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Client Report produces a follow-up proposal with CONFIRMATION_REQUIRED and MEDIUM risk."""
    threads = get_demo_threads()
    client = next(t for t in threads if t.id == "thread-client-report")

    suggestion = next_action_service.suggest_action(client, reference_time=_NOW)
    proposal = prep_service.prepare_action(client, suggestion, reference_time=_NOW)

    assert proposal.thread_id == "thread-client-report"
    assert proposal.action_type == NextActionType.FOLLOW_UP_ACTION
    assert proposal.status == ProposalStatus.CONFIRMATION_REQUIRED
    assert proposal.risk_level == RiskLevel.MEDIUM
    assert proposal.requires_confirmation is True
    assert proposal.confirmation_reason is not None
    assert "acme corp" in proposal.confirmation_reason.lower()
    assert proposal.inputs.get("recipient") == "Acme Corp"
    assert "dep-client-response" in proposal.supporting_dependency_ids


# ---------------------------------------------------------------------------
# Test 4: Evidence Gathering (Dentist Appointment)
# ---------------------------------------------------------------------------


def test_prepare_action_gather_evidence_dentist(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Dentist Appointment produces a READY, LOW-risk evidence-gathering proposal."""
    threads = get_demo_threads()
    dentist = next(t for t in threads if t.id == "thread-dentist-appointment")

    suggestion = next_action_service.suggest_action(dentist, reference_time=_NOW)
    proposal = prep_service.prepare_action(dentist, suggestion, reference_time=_NOW)

    assert proposal.thread_id == "thread-dentist-appointment"
    assert proposal.action_type == NextActionType.GATHER_EVIDENCE_ACTION
    assert proposal.status == ProposalStatus.READY
    assert proposal.risk_level == RiskLevel.LOW
    assert proposal.requires_confirmation is False
    assert proposal.confirmation_reason is None
    assert "gather" in proposal.title.lower()


# ---------------------------------------------------------------------------
# Test 5: No Action (Tax Filing 2025)
# ---------------------------------------------------------------------------


def test_prepare_action_no_action_tax_filing(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Completed thread produces a READY, LOW-risk non-executable proposal."""
    threads = get_demo_threads()
    tax = next(t for t in threads if t.id == "thread-tax-filing-2025")

    suggestion = next_action_service.suggest_action(tax, reference_time=_NOW)
    proposal = prep_service.prepare_action(tax, suggestion, reference_time=_NOW)

    assert proposal.thread_id == "thread-tax-filing-2025"
    assert proposal.action_type == NextActionType.NO_ACTION
    assert proposal.status == ProposalStatus.READY
    assert proposal.risk_level == RiskLevel.LOW
    assert proposal.requires_confirmation is False
    assert "no action" in proposal.title.lower()
    assert proposal.inputs == {}


# ---------------------------------------------------------------------------
# Test 6: Missing Required Information (BLOCKED Proposal)
# ---------------------------------------------------------------------------


def test_prepare_action_missing_recipient_produces_blocked(
    prep_service: ActionPreparationService,
) -> None:
    """A communication action with an unknown recipient produces BLOCKED, not fabricated data."""
    thread = _make_thread(
        status=ThreadStatus.WAITING,
        dependencies=[
            Dependency(
                id="dep-anon",
                description="Pending external approval from third party",
                type="EXTERNAL",
                status=DependencyStatus.OPEN,
                blocking=False,
            )
        ],
    )
    suggestion = NextActionSuggestion(
        thread_id=thread.id,
        action_type=NextActionType.FOLLOW_UP_ACTION,
        action="Follow up on pending external approval",
        rationale="Waiting for approval",
        confidence=0.80,
        supporting_dependency_ids=["dep-anon"],
        preconditions=["Awaiting external approval"],
        requires_confirmation=True,
    )

    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    assert proposal.status == ProposalStatus.BLOCKED
    assert proposal.requires_confirmation is True
    assert proposal.confirmation_reason is not None
    assert "recipient is not identified" in proposal.confirmation_reason
    assert "recipient" not in proposal.inputs
    assert any("recipient" in p.lower() for p in proposal.preconditions)


# ---------------------------------------------------------------------------
# Test 7: Confirmation Invariant
# ---------------------------------------------------------------------------


def test_prepare_action_confirmation_invariant(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """requires_confirmation == True must produce CONFIRMATION_REQUIRED or BLOCKED, never READY."""
    threads = get_demo_threads()
    for thread in threads:
        suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
        proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

        if proposal.requires_confirmation:
            assert proposal.status in (
                ProposalStatus.CONFIRMATION_REQUIRED,
                ProposalStatus.BLOCKED,
            )
        else:
            assert proposal.status in (ProposalStatus.READY, ProposalStatus.BLOCKED)


# ---------------------------------------------------------------------------
# Test 8: Traceability
# ---------------------------------------------------------------------------


def test_prepare_action_traceability(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """All supporting IDs in the proposal must originate from the M5 suggestion."""
    threads = get_demo_threads()
    for thread in threads:
        suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
        proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

        assert proposal.supporting_evidence_ids == suggestion.supporting_evidence_ids
        assert (
            proposal.supporting_commitment_ids == suggestion.supporting_commitment_ids
        )
        assert (
            proposal.supporting_dependency_ids == suggestion.supporting_dependency_ids
        )


# ---------------------------------------------------------------------------
# Test 9: Determinism
# ---------------------------------------------------------------------------


def test_prepare_action_determinism(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Repeated calls with identical thread and suggestion produce identical proposals and IDs."""
    threads = get_demo_threads()
    for thread in threads:
        suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
        p1 = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)
        p2 = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)
        # Verify complete model equality
        assert p1.model_dump() == p2.model_dump()
        # Verify proposal.id equality and deterministic format
        assert p1.id == p2.id
        assert p1.id.startswith("proposal-")
        assert len(p1.id) == len("proposal-") + 16


def test_prepare_action_distinct_proposals_have_distinct_ids(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Distinct threads and action suggestions produce distinct proposal IDs."""
    threads = get_demo_threads()
    proposals = []
    for thread in threads:
        suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
        proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)
        proposals.append(proposal)

    proposal_ids = [p.id for p in proposals]
    # All demo threads must yield unique proposal IDs
    assert len(proposal_ids) == len(set(proposal_ids))
    assert len(proposal_ids) >= 5


def test_derive_proposal_id_direct() -> None:
    """Direct test of deterministic proposal ID derivation."""
    id1 = derive_proposal_id(
        thread_id="thread-aws-hackathon",
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        supporting_evidence_ids=["evi-aws-1"],
        supporting_commitment_ids=["com-aws-m3"],
        supporting_dependency_ids=[],
    )
    id2 = derive_proposal_id(
        thread_id="thread-aws-hackathon",
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        supporting_evidence_ids=["evi-aws-1"],
        supporting_commitment_ids=["com-aws-m3"],
        supporting_dependency_ids=[],
    )
    id3 = derive_proposal_id(
        thread_id="thread-university-application",
        action_type=NextActionType.UNBLOCKER_ACTION,
        supporting_evidence_ids=["evi-uni-1"],
        supporting_commitment_ids=["com-uni-submit"],
        supporting_dependency_ids=["dep-uni-rec-letter"],
    )

    assert id1 == id2
    assert id1 != id3
    assert id1.startswith("proposal-")
    assert id3.startswith("proposal-")


# ---------------------------------------------------------------------------
# Test 10: Non-Execution Safety Guarantee
# ---------------------------------------------------------------------------


def test_prepare_action_does_not_call_external_services(
    next_action_service: NextActionService,
    prep_service: ActionPreparationService,
) -> None:
    """Verifies that prepare_action performs zero external HTTP or socket calls."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")
    suggestion = next_action_service.suggest_action(uni, reference_time=_NOW)

    # Patch urllib and socket to guarantee no network activity occurs
    with (
        patch("urllib.request.urlopen") as mock_url,
        patch("socket.socket") as mock_sock,
    ):
        proposal = prep_service.prepare_action(uni, suggestion, reference_time=_NOW)
        assert mock_url.call_count == 0
        assert mock_sock.call_count == 0
        assert proposal.title is not None


# ---------------------------------------------------------------------------
# Test 11: High Risk Classification
# ---------------------------------------------------------------------------


def test_prepare_action_high_risk_classification(
    prep_service: ActionPreparationService,
) -> None:
    """Actions with financial or irreversible side effects are classified as HIGH risk."""
    thread = _make_thread(
        commitments=[
            Commitment(
                id="c-pay",
                description="Submit final tuition payment",
                status=CommitmentStatus.OPEN,
            )
        ]
    )
    suggestion = NextActionSuggestion(
        thread_id=thread.id,
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        action="Submit final tuition payment",
        rationale="Payment due",
        confidence=0.90,
        supporting_commitment_ids=["c-pay"],
        requires_confirmation=True,
    )

    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)
    assert proposal.risk_level == RiskLevel.HIGH
    assert proposal.status == ProposalStatus.CONFIRMATION_REQUIRED
