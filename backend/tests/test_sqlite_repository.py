"""
Unit and integration tests for SQLiteThreadRepository (M10).

Validates:
  - Thread aggregate persistence and retrieval
  - Evidence, commitment, dependency, and event persistence
  - Proposal and verification storage
  - Restart / reload persistence across distinct connection lifecycles
  - Seed idempotency (mutated state is never silently overwritten on restart)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    Priority,
    ProposalStatus,
    RiskLevel,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import (
    ActionProposal,
    Commitment,
    Dependency,
    Evidence,
    IntentThread,
    ThreadEvent,
    ThreadVerification,
)
from app.repositories.sqlite_repository import SQLiteThreadRepository
from app.services.action_preparation_service import ActionPreparationService
from app.services.analysis_service import AnalysisService
from app.services.execution_service import ExecutionService
from app.services.next_action_service import NextActionService
from app.services.proposal_registry import ProposalRegistry
from app.services.thread_service import ThreadService

_NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def temp_db_path() -> str:
    """Provide a temporary database file path cleaned up after each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    p = Path(path)
    if p.exists():
        p.unlink(missing_ok=True)
    for ext in ("-wal", "-shm"):
        extra = Path(f"{path}{ext}")
        if extra.exists():
            extra.unlink(missing_ok=True)


def test_sqlite_repository_initial_seed(temp_db_path: str) -> None:
    """Repository automatically seeds demo data on empty database."""
    repo = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    try:
        count = repo.count_threads()
        assert count >= 4

        uni = repo.get_thread("thread-university-application")
        assert uni is not None
        assert uni.title == "University Application"
        assert len(uni.commitments) > 0
        assert len(uni.evidence) > 0
        assert len(uni.dependencies) > 0
        assert len(uni.events) > 0
    finally:
        repo.close()


def test_sqlite_repository_persistence_across_restart(temp_db_path: str) -> None:
    """Data saved in one repository instance survives process restart/reload."""
    # First instance: create and mutate a thread
    repo1 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    new_thread = IntentThread(
        id="thread-custom-relocation",
        title="Relocation to Seattle",
        description="Organize moving and housing in Seattle",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        created_at=_NOW,
        updated_at=_NOW,
        last_activity_at=_NOW,
        confidence=0.88,
        commitments=[
            Commitment(
                id="com-lease",
                description="Sign apartment lease agreement",
                status=CommitmentStatus.OPEN,
            )
        ],
        evidence=[
            Evidence(
                id="evi-lease-1",
                type=EvidenceType.DOCUMENT,
                description="Draft lease PDF from property management",
                source="Email attachment",
                created_at=_NOW,
                confidence=0.92,
            )
        ],
        dependencies=[
            Dependency(
                id="dep-background-check",
                description="Landlord background check verification",
                type="LANDLORD",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        events=[
            ThreadEvent(
                id="evt-relo-1",
                thread_id="thread-custom-relocation",
                event_type=ThreadEventType.THREAD_DISCOVERED,
                type=ThreadEventType.THREAD_DISCOVERED.value,
                description="Relocation intent detected",
                timestamp=_NOW,
            )
        ],
    )
    repo1.save_thread(new_thread)

    # Add an event and evidence
    new_evidence = Evidence(
        id="evi-lease-2",
        type=EvidenceType.MESSAGE,
        description="Background check approved by management",
        source="SMS notification",
        created_at=_NOW,
        confidence=0.95,
    )
    repo1.add_evidence("thread-custom-relocation", new_evidence)

    repo1.add_event(
        "thread-custom-relocation",
        ThreadEvent(
            id="evt-relo-2",
            thread_id="thread-custom-relocation",
            event_type=ThreadEventType.EVIDENCE_ADDED,
            type=ThreadEventType.EVIDENCE_ADDED.value,
            description="Background check approval evidence logged",
            timestamp=_NOW,
        ),
    )
    repo1.close()

    # Simulate restart: open a completely new repository instance on the same DB file
    repo2 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    try:
        thread = repo2.get_thread("thread-custom-relocation")
        assert thread is not None
        assert thread.title == "Relocation to Seattle"
        assert len(thread.evidence) == 2
        evidence_ids = {e.id for e in thread.evidence}
        assert "evi-lease-1" in evidence_ids
        assert "evi-lease-2" in evidence_ids

        # Verify events
        events = repo2.get_events("thread-custom-relocation")
        assert len(events) >= 2
        event_types = [e.event_type for e in events]
        assert ThreadEventType.THREAD_DISCOVERED in event_types
        assert ThreadEventType.EVIDENCE_ADDED in event_types
    finally:
        repo2.close()


def test_sqlite_repository_seed_idempotency_does_not_overwrite_state(
    temp_db_path: str,
) -> None:
    """Restarting must not reset modified thread state back to demo seed data."""
    repo1 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    # Mutate university application status to COMPLETED
    uni = repo1.get_thread("thread-university-application")
    assert uni is not None
    uni.status = ThreadStatus.COMPLETED
    repo1.save_thread(uni)
    repo1.close()

    # Restart
    repo2 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    try:
        reloaded = repo2.get_thread("thread-university-application")
        assert reloaded is not None
        # Must retain COMPLETED status and not be reset to BLOCKED
        assert reloaded.status == ThreadStatus.COMPLETED
    finally:
        repo2.close()


def test_sqlite_repository_proposal_and_verification_persistence(
    temp_db_path: str,
) -> None:
    """Action proposals and verifications are persisted and retrieved correctly."""
    repo = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    try:
        proposal = ActionProposal(
            id="proposal-aabbccddeeff0011",
            thread_id="thread-university-application",
            action_type=NextActionType.UNBLOCKER_ACTION,
            title="Follow up with Ahmed",
            description="Send reminder regarding recommendation letter",
            rationale="Unblock submission",
            status=ProposalStatus.CONFIRMATION_REQUIRED,
            requires_confirmation=True,
            confirmation_reason="Action creates external communication",
            inputs={"recipient": "Ahmed"},
            preconditions=["Ahmed contact info available"],
            supporting_evidence_ids=["evi-uni-1"],
            supporting_commitment_ids=["com-uni-submit"],
            supporting_dependency_ids=["dep-uni-rec-letter"],
            risk_level=RiskLevel.MEDIUM,
            created_at=_NOW,
        )
        repo.save_proposal(proposal)

        loaded_prop = repo.get_proposal("proposal-aabbccddeeff0011")
        assert loaded_prop is not None
        assert loaded_prop.id == proposal.id
        assert loaded_prop.inputs == {"recipient": "Ahmed"}
        assert loaded_prop.requires_confirmation is True

        verification = ThreadVerification(
            thread_id="thread-university-application",
            verified=True,
            confidence=0.94,
            reason="Required completion evidence present",
            required_evidence=["Recommendation letter"],
            matched_evidence=["evi-uni-3"],
            missing_evidence=[],
            verified_at=_NOW,
        )
        repo.save_verification(verification)

        latest_ver = repo.get_latest_verification("thread-university-application")
        assert latest_ver is not None
        assert latest_ver.verified is True
        assert latest_ver.confidence == 0.94
        assert "evi-uni-3" in latest_ver.matched_evidence
    finally:
        repo.close()


def test_persistent_action_proposal_authority_across_restart(
    temp_db_path: str,
) -> None:
    """Gate 1: Verify persistent ActionProposal authority and idempotency across restart.

    Workflow:
      1. Prepare an action proposal.
      2. Persist proposal into SQLite repository.
      3. Terminate / recreate service state (drop all in-memory references).
      4. Reload repository from database.
      5. Execute action using the same proposal_id on fresh service instance.
      6. Verify execution succeeds strictly from the persisted proposal.
      7. Verify cross-restart idempotency remains intact.
    """
    # Phase 1: Prepare proposal in initial service lifecycle
    repo1 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    thread_svc1 = ThreadService(repository=repo1)
    analysis_svc = AnalysisService()
    next_action_svc = NextActionService(analysis_svc)
    prep_svc1 = ActionPreparationService(repository=repo1)

    thread = thread_svc1.get_thread("thread-university-application")
    suggestion = next_action_svc.suggest_action(thread, reference_time=_NOW)
    proposal = prep_svc1.prepare_action(thread, suggestion, reference_time=_NOW)

    # Verify persisted in SQLite
    persisted_prop = repo1.get_proposal(proposal.id)
    assert persisted_prop is not None
    assert persisted_prop.id == proposal.id
    assert persisted_prop.requires_confirmation is True

    # Terminate service state 1 completely
    repo1.close()
    del repo1, thread_svc1, prep_svc1

    # Phase 2: Fresh service instance after restart (reloaded from SQLite)
    repo2 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
    try:
        thread_svc2 = ThreadService(repository=repo2)
        fresh_registry = ProposalRegistry(repository=repo2)
        # Verify in-memory dictionary is completely empty on reload
        assert len(fresh_registry._proposals) == 0

        exec_svc2 = ExecutionService(
            proposal_registry=fresh_registry,
            thread_service=thread_svc2,
            repository=repo2,
        )

        # Execute proposal from persisted state (confirmed=True)
        res1 = exec_svc2.execute_action(
            proposal_id=proposal.id,
            confirmed=True,
            reference_time=_NOW,
        )

        assert res1.execution_status == ExecutionStatus.EXECUTED
        assert res1.execution_mode == ExecutionMode.SIMULATED
        assert res1.proposal_id == proposal.id
        assert res1.event_id is not None

        # Verify audit event is persisted on the thread in SQLite
        updated_thread = repo2.get_thread("thread-university-application")
        assert updated_thread is not None
        assert any(e.id == res1.event_id for e in updated_thread.events)

        # Terminate service state 2
        repo2.close()

        # Phase 3: Fresh service instance to test cross-restart idempotency
        repo3 = SQLiteThreadRepository(db_path=temp_db_path, auto_seed=True)
        try:
            thread_svc3 = ThreadService(repository=repo3)
            fresh_registry3 = ProposalRegistry(repository=repo3)
            exec_svc3 = ExecutionService(
                proposal_registry=fresh_registry3,
                thread_service=thread_svc3,
                repository=repo3,
            )

            # Re-execute the same proposal on a clean restarted service
            res2 = exec_svc3.execute_action(
                proposal_id=proposal.id,
                confirmed=True,
                reference_time=_NOW,
            )

            # Idempotency is enforced: ALREADY_EXECUTED with identical event_id
            assert res2.execution_status == ExecutionStatus.ALREADY_EXECUTED
            assert res2.event_id == res1.event_id
            assert "already executed" in res2.message.lower()
        finally:
            repo3.close()
    finally:
        pass
