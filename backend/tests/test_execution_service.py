"""
Unit tests for ProposalRegistry, SimulatedActionExecutor, and ExecutionService (Threadback M7).

Covers all M7 safety, validation, idempotency, and simulation requirements:
  - Proposal registry: registration, retrieval, unknown proposal, object preservation
  - Confirmation semantics: READY executes without confirmed, CONFIRMATION_REQUIRED requires confirmed=True, rejected if confirmed=False
  - Blocked proposals: BLOCKED cannot execute, no event created
  - Preconditions: valid preconditions pass, failed preconditions return BLOCKED, no event created
  - Thread validation: unknown thread rejected, COMPLETED thread rejected, ABANDONED thread rejected
  - Idempotency: re-execution returns ALREADY_EXECUTED, no duplicate event
  - Action types: DIRECT_NEXT_ACTION, UNBLOCKER_ACTION, FOLLOW_UP_ACTION, GATHER_EVIDENCE_ACTION, NO_ACTION
  - Execution mode: unsupported mode rejected
  - Safety boundary: zero external network or process side effects
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    ProposalStatus,
    RiskLevel,
    ThreadStatus,
)
from app.domain.models import ActionProposal
from app.services.action_executor import SimulatedActionExecutor
from app.services.action_preparation_service import ActionPreparationService
from app.services.analysis_service import AnalysisService
from app.services.execution_service import ExecutionService, validate_preconditions
from app.services.next_action_service import NextActionService
from app.services.proposal_registry import ProposalRegistry
from app.services.thread_service import ThreadService

_NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def thread_service() -> ThreadService:
    return ThreadService()


@pytest.fixture
def analysis_service() -> AnalysisService:
    return AnalysisService()


@pytest.fixture
def next_action_service(analysis_service: AnalysisService) -> NextActionService:
    return NextActionService(analysis_service)


@pytest.fixture
def proposal_registry() -> ProposalRegistry:
    return ProposalRegistry()


@pytest.fixture
def prep_service(proposal_registry: ProposalRegistry) -> ActionPreparationService:
    return ActionPreparationService(registry=proposal_registry)


@pytest.fixture
def execution_service(
    proposal_registry: ProposalRegistry,
    thread_service: ThreadService,
) -> ExecutionService:
    return ExecutionService(
        proposal_registry=proposal_registry,
        thread_service=thread_service,
        executor=SimulatedActionExecutor(),
    )


# ---------------------------------------------------------------------------
# 1. Proposal Registry Tests
# ---------------------------------------------------------------------------


def test_proposal_registry_lifecycle(proposal_registry: ProposalRegistry) -> None:
    """Test registration, retrieval, existence checks, and exact preservation."""
    proposal = ActionProposal(
        id="proposal-test-lifecycle-1234",
        thread_id="thread-aws-hackathon",
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        title="Test Proposal",
        description="Detailed test description",
        rationale="Structured test rationale",
        status=ProposalStatus.READY,
        requires_confirmation=False,
        risk_level=RiskLevel.LOW,
        created_at=_NOW,
    )

    assert proposal.id not in proposal_registry
    assert len(proposal_registry) == 0
    assert proposal_registry.get(proposal.id) is None

    registered = proposal_registry.register(proposal)
    assert registered is proposal
    assert proposal.id in proposal_registry
    assert len(proposal_registry) == 1

    retrieved = proposal_registry.get(proposal.id)
    assert retrieved is proposal
    assert retrieved.id == proposal.id
    assert retrieved.title == "Test Proposal"

    # List all
    all_props = proposal_registry.list_all()
    assert len(all_props) == 1
    assert all_props[0] is proposal

    # Clear
    proposal_registry.clear()
    assert len(proposal_registry) == 0
    assert proposal.id not in proposal_registry
    assert proposal_registry.get(proposal.id) is None


# ---------------------------------------------------------------------------
# 2. Confirmation Semantics
# ---------------------------------------------------------------------------


def test_execute_ready_action_without_confirmation(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """READY proposal (requires_confirmation=False) executes successfully without confirmed=True."""
    thread = thread_service.get_thread("thread-aws-hackathon")
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    assert proposal.status == ProposalStatus.READY
    assert proposal.requires_confirmation is False

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
        reference_time=_NOW,
    )

    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.SIMULATED
    assert "simulated successfully" in result.message.lower()
    assert result.event_id is not None

    # Verify event recorded on thread
    updated_thread = thread_service.get_thread("thread-aws-hackathon")
    assert any(e.id == result.event_id for e in updated_thread.events)


def test_execute_confirmation_required_with_confirmed_true(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """CONFIRMATION_REQUIRED proposal executes successfully when confirmed=True."""
    thread = thread_service.get_thread("thread-university-application")
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    assert proposal.status == ProposalStatus.CONFIRMATION_REQUIRED
    assert proposal.requires_confirmation is True

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=True,
        reference_time=_NOW,
    )

    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.SIMULATED
    assert "unblocker action was simulated successfully" in result.message.lower()
    assert result.event_id is not None

    # Verify event recorded on thread
    updated_thread = thread_service.get_thread("thread-university-application")
    assert any(e.id == result.event_id for e in updated_thread.events)


def test_execute_confirmation_required_rejected_without_confirmed(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """CONFIRMATION_REQUIRED proposal is REJECTED when confirmed=False, creating no event."""
    thread = thread_service.get_thread("thread-university-application")
    events_before = len(thread.events)
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
        reference_time=_NOW,
    )

    assert result.execution_status == ExecutionStatus.REJECTED
    assert "explicit user confirmation" in result.message
    assert result.event_id is None

    # Verify no new event was created on thread
    updated_thread = thread_service.get_thread("thread-university-application")
    assert len(updated_thread.events) == events_before


# ---------------------------------------------------------------------------
# 3. Blocked Proposals & Missing Information
# ---------------------------------------------------------------------------


def test_execute_blocked_proposal_rejected(
    proposal_registry: ProposalRegistry,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """A proposal with status BLOCKED is immediately blocked/rejected and creates no event."""
    thread = thread_service.get_thread("thread-client-report")
    events_before = len(thread.events)

    blocked_proposal = ActionProposal(
        id="proposal-blocked-test-9999",
        thread_id=thread.id,
        action_type=NextActionType.FOLLOW_UP_ACTION,
        title="Follow up with unknown client",
        description="Follow-up blocked due to missing recipient",
        rationale="Recipient identity missing",
        status=ProposalStatus.BLOCKED,
        requires_confirmation=True,
        confirmation_reason="The follow-up cannot be prepared because the recipient is unknown.",
        preconditions=["Recipient identity must be established before preparation"],
        risk_level=RiskLevel.MEDIUM,
        created_at=_NOW,
    )
    proposal_registry.register(blocked_proposal)

    result = execution_service.execute_action(
        proposal_id=blocked_proposal.id,
        confirmed=True,
        reference_time=_NOW,
    )

    assert result.execution_status == ExecutionStatus.BLOCKED
    assert "BLOCKED and cannot be executed" in result.message
    assert result.event_id is None

    # No event added
    updated_thread = thread_service.get_thread("thread-client-report")
    assert len(updated_thread.events) == events_before


# ---------------------------------------------------------------------------
# 4. Precondition Validation
# ---------------------------------------------------------------------------


def test_precondition_validation_failure_blocks_execution(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Execution is BLOCKED if a required precondition fails against thread state."""
    thread = thread_service.get_thread("thread-aws-hackathon")
    events_before = len(thread.events)
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    # Invalidate the supporting commitment on the thread to cause precondition failure
    thread_internal = thread_service._threads["thread-aws-hackathon"]
    for c in thread_internal.commitments:
        if c.id == "com-aws-m3":
            c.status = CommitmentStatus.COMPLETED

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=True,
        reference_time=_NOW,
    )

    assert result.execution_status == ExecutionStatus.BLOCKED
    assert "Precondition failed" in result.message
    assert result.event_id is None

    # No event added
    updated_thread = thread_service.get_thread("thread-aws-hackathon")
    assert len(updated_thread.events) == events_before


def test_precondition_validation_helper_direct() -> None:
    """Direct test of the validate_preconditions helper."""
    threads = get_demo_threads()
    uni = next(t for t in threads if t.id == "thread-university-application")

    proposal = ActionProposal(
        id="proposal-test-prec",
        thread_id=uni.id,
        action_type=NextActionType.UNBLOCKER_ACTION,
        title="Resolve blocker",
        description="Desc",
        rationale="Rationale",
        status=ProposalStatus.CONFIRMATION_REQUIRED,
        requires_confirmation=True,
        supporting_dependency_ids=["dep-uni-rec-letter"],
        preconditions=[
            "Dependency 'Recommendation letter from Ahmed' must be resolved"
        ],
        risk_level=RiskLevel.MEDIUM,
        created_at=_NOW,
    )

    # Valid dependency open
    ok, err = validate_preconditions(proposal, uni)
    assert ok is True
    assert err is None

    # Invalidate dependency
    uni_copy = uni.model_copy(deep=True)
    uni_copy.dependencies[0].status = DependencyStatus.RESOLVED
    ok, err = validate_preconditions(proposal, uni_copy)
    assert ok is False
    assert err is not None
    assert "Supporting dependency" in err


# ---------------------------------------------------------------------------
# 5. Thread Validation & Terminal Thread Protection
# ---------------------------------------------------------------------------


def test_execute_unknown_proposal_rejected(
    execution_service: ExecutionService,
) -> None:
    """An unknown proposal_id returns REJECTED cleanly without crashing."""
    result = execution_service.execute_action(
        proposal_id="proposal-completely-unknown-999",
        confirmed=True,
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert "was not found in the proposal registry" in result.message
    assert result.event_id is None


def test_execute_unknown_thread_rejected(
    proposal_registry: ProposalRegistry,
    execution_service: ExecutionService,
) -> None:
    """A proposal pointing to a non-existent thread is REJECTED cleanly."""
    proposal = ActionProposal(
        id="proposal-orphan-thread-123",
        thread_id="thread-nonexistent-xyz",
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        title="Orphan Action",
        description="Description",
        rationale="Rationale",
        status=ProposalStatus.READY,
        requires_confirmation=False,
        risk_level=RiskLevel.LOW,
        created_at=_NOW,
    )
    proposal_registry.register(proposal)

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert "Source thread 'thread-nonexistent-xyz' was not found" in result.message
    assert result.event_id is None


def test_execute_completed_thread_rejected(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Proposals for COMPLETED threads (e.g. Tax Filing 2025) are REJECTED."""
    tax = thread_service.get_thread("thread-tax-filing-2025")
    assert tax.status == ThreadStatus.COMPLETED

    suggestion = next_action_service.suggest_action(tax, reference_time=_NOW)
    proposal = prep_service.prepare_action(tax, suggestion, reference_time=_NOW)

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=True,
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert (
        "terminal status" in result.message.lower()
        or "no_action" in result.message.lower()
    )
    assert result.event_id is None


def test_execute_abandoned_thread_rejected(
    proposal_registry: ProposalRegistry,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Proposals for ABANDONED threads are REJECTED."""
    thread_internal = thread_service._threads["thread-dentist-appointment"]
    thread_internal.status = ThreadStatus.ABANDONED

    proposal = ActionProposal(
        id="proposal-abandoned-test",
        thread_id="thread-dentist-appointment",
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        title="Some action",
        description="Desc",
        rationale="Rationale",
        status=ProposalStatus.READY,
        requires_confirmation=False,
        risk_level=RiskLevel.LOW,
        created_at=_NOW,
    )
    proposal_registry.register(proposal)

    result = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert "terminal status 'ABANDONED'" in result.message
    assert result.event_id is None


# ---------------------------------------------------------------------------
# 6. Idempotency & Repeated Execution
# ---------------------------------------------------------------------------


def test_execute_action_idempotency(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Repeated execution of the same proposal returns ALREADY_EXECUTED and creates no duplicate event."""
    thread = thread_service.get_thread("thread-aws-hackathon")
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    # First execution
    res1 = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
        reference_time=_NOW,
    )
    assert res1.execution_status == ExecutionStatus.EXECUTED
    assert res1.event_id is not None

    count_after_first = len(thread_service.get_thread("thread-aws-hackathon").events)

    # Second execution
    res2 = execution_service.execute_action(
        proposal_id=proposal.id,
        confirmed=False,
        reference_time=_NOW,
    )
    assert res2.execution_status == ExecutionStatus.ALREADY_EXECUTED
    assert "already executed" in res2.message.lower()
    assert res2.event_id == res1.event_id

    # Verify no second event was appended
    count_after_second = len(thread_service.get_thread("thread-aws-hackathon").events)
    assert count_after_second == count_after_first


# ---------------------------------------------------------------------------
# 7. Action Type Coverage
# ---------------------------------------------------------------------------


def test_execute_all_executable_action_types(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Verifies that DIRECT_NEXT_ACTION, UNBLOCKER_ACTION, FOLLOW_UP_ACTION, and GATHER_EVIDENCE_ACTION simulate successfully."""
    # 1. DIRECT_NEXT_ACTION (AWS Hackathon)
    aws = thread_service.get_thread("thread-aws-hackathon")
    sug_aws = next_action_service.suggest_action(aws, reference_time=_NOW)
    p_aws = prep_service.prepare_action(aws, sug_aws, reference_time=_NOW)
    r_aws = execution_service.execute_action(
        p_aws.id, confirmed=False, reference_time=_NOW
    )
    assert r_aws.execution_status == ExecutionStatus.EXECUTED
    assert "direct next action was simulated successfully" in r_aws.message.lower()

    # 2. UNBLOCKER_ACTION (University Application)
    uni = thread_service.get_thread("thread-university-application")
    sug_uni = next_action_service.suggest_action(uni, reference_time=_NOW)
    p_uni = prep_service.prepare_action(uni, sug_uni, reference_time=_NOW)
    r_uni = execution_service.execute_action(
        p_uni.id, confirmed=True, reference_time=_NOW
    )
    assert r_uni.execution_status == ExecutionStatus.EXECUTED
    assert "unblocker action was simulated successfully" in r_uni.message.lower()

    # 3. FOLLOW_UP_ACTION (Client Report)
    client = thread_service.get_thread("thread-client-report")
    sug_client = next_action_service.suggest_action(client, reference_time=_NOW)
    p_client = prep_service.prepare_action(client, sug_client, reference_time=_NOW)
    r_client = execution_service.execute_action(
        p_client.id, confirmed=True, reference_time=_NOW
    )
    assert r_client.execution_status == ExecutionStatus.EXECUTED
    assert "follow-up action was simulated successfully" in r_client.message.lower()

    # 4. GATHER_EVIDENCE_ACTION (Dentist Appointment)
    dentist = thread_service.get_thread("thread-dentist-appointment")
    sug_dentist = next_action_service.suggest_action(dentist, reference_time=_NOW)
    p_dentist = prep_service.prepare_action(dentist, sug_dentist, reference_time=_NOW)
    r_dentist = execution_service.execute_action(
        p_dentist.id, confirmed=False, reference_time=_NOW
    )
    assert r_dentist.execution_status == ExecutionStatus.EXECUTED
    assert (
        "evidence-gathering action was simulated successfully"
        in r_dentist.message.lower()
    )


def test_execute_no_action_proposal_rejected(
    proposal_registry: ProposalRegistry,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """NO_ACTION proposals cannot be executed and are REJECTED."""
    thread = thread_service.get_thread("thread-aws-hackathon")
    no_act_prop = ActionProposal(
        id="proposal-no-action-custom",
        thread_id=thread.id,
        action_type=NextActionType.NO_ACTION,
        title="No action required",
        description="Thread is quiescent.",
        rationale="No pending obligations.",
        status=ProposalStatus.READY,
        requires_confirmation=False,
        risk_level=RiskLevel.LOW,
        created_at=_NOW,
    )
    proposal_registry.register(no_act_prop)

    result = execution_service.execute_action(
        proposal_id=no_act_prop.id,
        confirmed=False,
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert "NO_ACTION proposal cannot be executed" in result.message


# ---------------------------------------------------------------------------
# 8. Execution Mode Validation
# ---------------------------------------------------------------------------


def test_execute_unsupported_execution_mode_rejected(
    execution_service: ExecutionService,
) -> None:
    """Unsupported execution mode (e.g. 'REAL' or 'LIVE') is rejected."""
    result = execution_service.execute_action(
        proposal_id="proposal-any-id",
        confirmed=True,
        execution_mode="REAL",
    )
    assert result.execution_status == ExecutionStatus.REJECTED
    assert "Unsupported execution mode 'REAL'" in result.message


# ---------------------------------------------------------------------------
# 9. Non-Execution Safety Guarantee
# ---------------------------------------------------------------------------


def test_execute_action_does_not_call_external_services(
    prep_service: ActionPreparationService,
    next_action_service: NextActionService,
    execution_service: ExecutionService,
    thread_service: ThreadService,
) -> None:
    """Verifies that execute_action performs zero external HTTP, socket, or real-world calls."""
    thread = thread_service.get_thread("thread-university-application")
    suggestion = next_action_service.suggest_action(thread, reference_time=_NOW)
    proposal = prep_service.prepare_action(thread, suggestion, reference_time=_NOW)

    # Patch urllib and socket to guarantee no network activity occurs
    with (
        patch("urllib.request.urlopen") as mock_url,
        patch("socket.socket") as mock_sock,
    ):
        result = execution_service.execute_action(
            proposal_id=proposal.id,
            confirmed=True,
            reference_time=_NOW,
        )
        assert mock_url.call_count == 0
        assert mock_sock.call_count == 0
        assert result.execution_status == ExecutionStatus.EXECUTED
