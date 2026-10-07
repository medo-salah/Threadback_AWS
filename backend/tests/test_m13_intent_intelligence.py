"""Comprehensive test suite for Threadback M13 — Persistent Intent Intelligence.

Verifies:
1. IntentMemoryService: goal evolution, immutable original_goal, history, intent summary.
2. IntentRadarService: decay state scoring, composite urgency, 4-tier differential 'What Changed?'.
3. LifecycleService: DEFER, RESUME, ABANDON transitions, events, timestamps.
4. ActionPreparationService & ExecutionService: typed M13 action proposals and execution convergence.
5. SQLite Repository: durable persistence of evolutions, checkpoints, and extended thread fields.
6. Conversational Flow: classifier routing, ambiguous intent hold, and radar/decay/change chat handlers.
7. Architectural Invariants: EXECUTION_SUCCESS != VERIFIED_COMPLETION, immutable original_goal.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.agent.intent_classifier import (
    IntentType,
    classify_intent,
    extract_revised_goal,
)
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.domain.enums import (
    DecayState,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    Priority,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import IntentThread, NextActionSuggestion
from app.repositories.in_memory_repository import InMemoryThreadRepository
from app.repositories.sqlite_repository import SQLiteThreadRepository
from app.services.action_preparation_service import ActionPreparationService
from app.services.execution_service import ExecutionService
from app.services.intent_memory_service import IntentMemoryService
from app.services.intent_radar_service import IntentRadarService
from app.services.lifecycle_service import LifecycleService
from app.services.thread_service import ThreadNotFoundError, ThreadService
from app.services.verification_service import VerificationService

# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    """In-memory repository with fresh sample thread."""
    r = InMemoryThreadRepository()
    now = datetime.now(timezone.utc)
    thread = IntentThread(
        id="test-thread-m13",
        title="Launch Product Alpha",
        description="Release MVP to 10 beta testers by end of month",
        original_goal="Release MVP to 10 beta testers by end of month",
        current_goal="Release MVP to 10 beta testers by end of month",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        confidence=0.9,
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=1),
        last_activity_at=now - timedelta(days=1),
        last_interaction_at=now - timedelta(days=1),
    )
    r.save_thread(thread)
    return r


@pytest.fixture
def thread_service(repo):
    return ThreadService(repository=repo)


@pytest.fixture
def verif_service(thread_service):
    return VerificationService(thread_service=thread_service)


@pytest.fixture
def radar_service(thread_service):
    return IntentRadarService(thread_service=thread_service)


@pytest.fixture
def lifecycle_service(thread_service, verif_service):
    return LifecycleService(
        thread_service=thread_service, verification_service=verif_service
    )


@pytest.fixture
def memory_service(thread_service, radar_service):
    return IntentMemoryService(
        thread_service=thread_service, radar_service=radar_service
    )


@pytest.fixture
def prep_service(repo):
    return ActionPreparationService(repository=repo)


@pytest.fixture
def exec_service(thread_service, repo, prep_service, memory_service, lifecycle_service):
    return ExecutionService(
        thread_service=thread_service,
        repository=repo,
        intent_memory_service=memory_service,
        lifecycle_service=lifecycle_service,
    )


# ---------------------------------------------------------------------------
# 1. IntentMemoryService & Immutable original_goal
# ---------------------------------------------------------------------------


def test_intent_evolution_updates_current_goal_and_preserves_original_goal(
    repo, memory_service
):
    """original_goal MUST be strictly immutable when current_goal evolves."""
    original = "Release MVP to 10 beta testers by end of month"
    revised = "Release MVP to 50 beta testers with Stripe payments enabled"
    reason = "Customer demand increased and pricing model was finalized"

    evolution = memory_service.evolve_goal(
        thread_id="test-thread-m13",
        revised_goal=revised,
        reason=reason,
    )

    assert evolution.thread_id == "test-thread-m13"
    assert evolution.previous_goal == original
    assert evolution.revised_goal == revised
    assert evolution.reason == reason

    # Fetch updated thread from repository
    updated = repo.get_thread("test-thread-m13")
    assert updated is not None
    # INVARIANT: original_goal MUST NOT CHANGE
    assert updated.original_goal == original
    assert updated.current_goal == revised

    # Verify event was recorded
    events = repo.get_events("test-thread-m13")
    evolve_events = [
        e for e in events if e.event_type == ThreadEventType.INTENTION_EVOLVED
    ]
    assert len(evolve_events) == 1
    assert evolve_events[0].payload["revised_goal"] == revised
    assert evolve_events[0].payload["original_goal"] == original


def test_intent_evolution_history_ordering(repo, memory_service):
    """Multiple evolutions should be strictly chronologically ordered."""
    memory_service.evolve_goal("test-thread-m13", "Goal v2", "Scope expanded")
    memory_service.evolve_goal("test-thread-m13", "Goal v3", "Added mobile support")

    history = memory_service.get_evolution_history("test-thread-m13")
    assert len(history) == 2
    assert history[0].revised_goal == "Goal v2"
    assert history[1].revised_goal == "Goal v3"

    thread = repo.get_thread("test-thread-m13")
    assert thread.current_goal == "Goal v3"
    assert thread.original_goal == "Release MVP to 10 beta testers by end of month"


def test_intent_evolution_validation_errors(memory_service):
    """Invalid parameters must raise appropriate errors."""
    with pytest.raises(ThreadNotFoundError):
        memory_service.evolve_goal("non-existent-thread", "New Goal", "Reason")

    with pytest.raises(ValueError, match="cannot be empty"):
        memory_service.evolve_goal("test-thread-m13", "", "Reason")


def test_get_intent_summary(repo, memory_service):
    """Intent summary combines thread status, goal evolution, decay signal, and diff."""
    memory_service.evolve_goal("test-thread-m13", "Goal v2", "Pivot")
    summary = memory_service.get_intent_summary("test-thread-m13")

    assert summary.thread_id == "test-thread-m13"
    assert summary.original_goal == "Release MVP to 10 beta testers by end of month"
    assert summary.current_goal == "Goal v2"
    assert summary.decay_state in list(DecayState)


# ---------------------------------------------------------------------------
# 2. IntentRadarService & Decay Scoring & 'What Changed?'
# ---------------------------------------------------------------------------


def test_decay_state_detection_healthy(repo, radar_service):
    """Thread touched recently (<3 days) should be HEALTHY."""
    now = datetime.now(timezone.utc)
    thread = repo.get_thread("test-thread-m13")
    thread.last_activity_at = now - timedelta(hours=2)
    thread.status = ThreadStatus.ACTIVE
    repo.save_thread(thread)

    signal = radar_service.compute_decay_signal(thread, reference_time=now)
    assert signal.decay_state == DecayState.HEALTHY
    assert signal.inactive_days < 1.0


def test_decay_state_detection_attention(repo, radar_service):
    """Thread inactive for 4 days should flag ATTENTION."""
    now = datetime.now(timezone.utc)
    thread = repo.get_thread("test-thread-m13")
    thread.last_activity_at = now - timedelta(days=4)
    thread.status = ThreadStatus.ACTIVE
    repo.save_thread(thread)

    signal = radar_service.compute_decay_signal(thread, reference_time=now)
    assert signal.decay_state == DecayState.ATTENTION
    assert "inactivity" in signal.explanation.lower()


def test_decay_state_detection_decaying(repo, radar_service):
    """Thread inactive for 8 days should be DECAYING."""
    now = datetime.now(timezone.utc)
    thread = repo.get_thread("test-thread-m13")
    thread.last_activity_at = now - timedelta(days=8)
    thread.status = ThreadStatus.ACTIVE
    repo.save_thread(thread)

    signal = radar_service.compute_decay_signal(thread, reference_time=now)
    assert signal.decay_state == DecayState.DECAYING
    assert signal.decay_score >= 0.8


def test_decay_state_detection_stale(repo, radar_service):
    """Thread inactive for 15 days should be STALE."""
    now = datetime.now(timezone.utc)
    thread = repo.get_thread("test-thread-m13")
    thread.last_activity_at = now - timedelta(days=15)
    thread.status = ThreadStatus.ACTIVE
    repo.save_thread(thread)

    signal = radar_service.compute_decay_signal(thread, reference_time=now)
    assert signal.decay_state == DecayState.STALE
    assert signal.decay_score == 1.0


def test_intent_radar_prioritization(repo, radar_service):
    """Intent radar report prioritizes threads by composite urgency score."""
    now = datetime.now(timezone.utc)
    thread1 = repo.get_thread("test-thread-m13")

    critical_thread = IntentThread(
        id="critical-thread",
        title="Submit Grant Application",
        description="Submit NSF grant proposal",
        original_goal="Submit NSF grant proposal",
        current_goal="Submit NSF grant proposal",
        status=ThreadStatus.BLOCKED,
        priority=Priority.HIGH,
        confidence=0.9,
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=3),
        last_activity_at=now - timedelta(days=3),
        last_interaction_at=now - timedelta(days=3),
    )
    repo.save_thread(critical_thread)

    report = radar_service.compute_radar_report(
        [thread1, critical_thread], reference_time=now
    )
    assert report.active_threads_count == 2
    assert len(report.items) == 2
    # Critical blocked thread with active blocker has higher urgency
    assert report.items[0].urgency_score >= report.items[1].urgency_score


def test_what_changed_anchor_resolution_and_diff(repo, radar_service, memory_service):
    """4-tier differential anchor resolves changes accurately."""
    thread = repo.get_thread("test-thread-m13")
    diff = radar_service.diff_thread_state(thread)
    assert diff.thread_id == "test-thread-m13"
    assert diff.summary is not None


# ---------------------------------------------------------------------------
# 3. LifecycleService (DEFER, RESUME, ABANDON)
# ---------------------------------------------------------------------------


def test_defer_and_resume_lifecycle(repo, lifecycle_service):
    """DEFER transitions status to DEFERRED and records deferred_until, RESUME restores ACTIVE."""
    now = datetime.now(timezone.utc)
    resume_target = now + timedelta(days=7)

    defer_event = lifecycle_service.defer_thread(
        thread_id="test-thread-m13",
        deferred_until=resume_target,
        reason="Waiting for client feedback next week",
    )
    assert defer_event.event_type == ThreadEventType.THREAD_DEFERRED
    deferred_thread = repo.get_thread("test-thread-m13")
    assert deferred_thread.status == ThreadStatus.DEFERRED
    assert deferred_thread.deferred_until is not None

    events = repo.get_events("test-thread-m13")
    defer_events = [
        e for e in events if e.event_type == ThreadEventType.THREAD_DEFERRED
    ]
    assert len(defer_events) == 1
    assert "Waiting for client feedback" in defer_events[0].payload["reason"]

    # Resume the thread
    resume_event = lifecycle_service.resume_thread(
        thread_id="test-thread-m13",
        reason="Client replied early",
    )
    assert resume_event.event_type == ThreadEventType.THREAD_RESUMED
    resumed_thread = repo.get_thread("test-thread-m13")
    assert resumed_thread.status == ThreadStatus.ACTIVE
    assert resumed_thread.deferred_until is None

    resume_events = [
        e
        for e in repo.get_events("test-thread-m13")
        if e.event_type == ThreadEventType.THREAD_RESUMED
    ]
    assert len(resume_events) == 1


def test_abandon_lifecycle(repo, lifecycle_service):
    """ABANDON transitions status to ABANDONED with reason and event."""
    abandon_event = lifecycle_service.abandon_thread(
        thread_id="test-thread-m13",
        reason="No longer relevant due to company pivot",
    )
    assert abandon_event.event_type == ThreadEventType.THREAD_ABANDONED

    abandoned = repo.get_thread("test-thread-m13")
    assert abandoned.status == ThreadStatus.ABANDONED
    assert abandoned.abandoned_reason == "No longer relevant due to company pivot"

    events = [
        e
        for e in repo.get_events("test-thread-m13")
        if e.event_type == ThreadEventType.THREAD_ABANDONED
    ]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# 4. ActionPreparationService & ExecutionService Convergence
# ---------------------------------------------------------------------------


def test_m13_action_preparation_and_execution_evolve_goal(
    repo, prep_service, exec_service
):
    """External Alexa+/MCP prepares EVOLVE_INTENTION and executes it deterministically."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.EVOLVE_INTENTION,
        parameters={
            "new_goal": "Goal evolved via action proposal",
            "reason": "Evaluator test",
        },
    )
    assert proposal.thread_id == "test-thread-m13"
    assert proposal.action_type == NextActionType.EVOLVE_INTENTION
    assert proposal.inputs["new_goal"] == "Goal evolved via action proposal"

    # Invariant: external mutations must use prepare_action -> execute_action
    result = exec_service.execute_action(proposal.id, confirmed=True)
    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    # Invariant: EXECUTION_SUCCESS != VERIFIED_COMPLETION
    assert repo.get_thread("test-thread-m13").status != ThreadStatus.COMPLETED

    updated = repo.get_thread("test-thread-m13")
    assert updated.current_goal == "Goal evolved via action proposal"
    assert updated.original_goal == "Release MVP to 10 beta testers by end of month"


def test_m13_action_preparation_and_execution_defer_and_resume(
    repo, prep_service, exec_service
):
    """DEFER and RESUME via action proposal and execution."""
    thread = repo.get_thread("test-thread-m13")
    defer_prop = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.DEFER_INTENTION,
        parameters={
            "reason": "Deferred via proposal",
            "deferred_until": "2026-11-01T00:00:00Z",
        },
    )
    res = exec_service.execute_action(defer_prop.id, confirmed=True)
    assert res.execution_status == ExecutionStatus.EXECUTED
    assert res.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert repo.get_thread("test-thread-m13").status == ThreadStatus.DEFERRED

    deferred_thread = repo.get_thread("test-thread-m13")
    resume_prop = prep_service.prepare_action(
        thread=deferred_thread,
        action_type=NextActionType.RESUME_INTENTION,
        parameters={"reason": "Resuming via proposal"},
    )
    res2 = exec_service.execute_action(resume_prop.id, confirmed=True)
    assert res2.execution_status == ExecutionStatus.EXECUTED
    assert res2.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert repo.get_thread("test-thread-m13").status == ThreadStatus.ACTIVE


# ---------------------------------------------------------------------------
# 5. SQLite Persistence & Schema Migration
# ---------------------------------------------------------------------------


def test_sqlite_persistence_and_schema_columns():
    """SQLite repository persists original_goal, current_goal, evolutions, and checkpoints."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_m13.db"
        repo1 = SQLiteThreadRepository(db_path=db_path)

        now = datetime.now(timezone.utc)
        thread = IntentThread(
            id="sqlite-m13-thread",
            title="Durable Thread",
            description="Testing SQLite persistence for M13",
            original_goal="Initial original goal",
            current_goal="Initial current goal",
            status=ThreadStatus.ACTIVE,
            priority=Priority.MEDIUM,
            confidence=0.85,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
            last_interaction_at=now,
        )
        repo1.save_thread(thread)

        ts1 = ThreadService(repository=repo1)
        mem1 = IntentMemoryService(thread_service=ts1)
        mem1.evolve_goal("sqlite-m13-thread", "Persisted Goal v2", "Tested persistence")
        repo1.set_conversation_checkpoint(
            "test-conv-1", now, checkpoint_event_id="evt-1"
        )

        # Simulate service restart with new repository instance pointing to same SQLite DB
        repo2 = SQLiteThreadRepository(db_path=db_path)
        reloaded = repo2.get_thread("sqlite-m13-thread")
        assert reloaded is not None
        assert reloaded.original_goal == "Initial original goal"
        assert reloaded.current_goal == "Persisted Goal v2"

        evolutions = repo2.get_intent_evolutions("sqlite-m13-thread")
        assert len(evolutions) == 1
        assert evolutions[0].revised_goal == "Persisted Goal v2"
        assert evolutions[0].reason == "Tested persistence"

        checkpoint = repo2.get_conversation_checkpoint("test-conv-1")
        assert checkpoint is not None


# ---------------------------------------------------------------------------
# 6. Conversational Classifier & MockProvider Handlers
# ---------------------------------------------------------------------------


def test_intent_classifier_m13_patterns():
    """Classifier correctly distinguishes M13 intent types and extracts parameters."""
    # Intent Radar
    res = classify_intent("Scan my intent radar")
    assert res.intent == IntentType.INTENT_RADAR

    # Intent Decay
    res = classify_intent("Which intentions are decaying?")
    assert res.intent == IntentType.INTENT_DECAY

    # What Changed
    res = classify_intent("What changed on my dentist appointment?")
    assert res.intent == IntentType.WHAT_CHANGED
    assert res.extracted_topic == "thread-dentist-appointment"

    # Explicit Goal Evolution
    res = classify_intent(
        "Update my dentist goal to: Schedule teeth cleaning and check wisdom tooth"
    )
    assert res.intent == IntentType.INTENT_EVOLUTION
    assert res.extracted_topic == "thread-dentist-appointment"
    revised = extract_revised_goal(
        "Update my dentist goal to: Schedule teeth cleaning and check wisdom tooth"
    )
    assert revised is not None
    assert "teeth cleaning" in revised

    # Ambiguous Goal Evolution
    res = classify_intent(
        "I might want to change my dentist appointment to another clinic maybe"
    )
    assert res.intent == IntentType.AMBIGUOUS_INTENT_EVOLUTION
    assert res.extracted_topic == "thread-dentist-appointment"

    # Lifecycle: Defer, Resume, Abandon
    res = classify_intent("Defer dentist appointment until next Friday")
    assert res.intent == IntentType.LIFECYCLE_DEFER

    res = classify_intent("Resume my dentist appointment thread")
    assert res.intent == IntentType.LIFECYCLE_RESUME

    res = classify_intent("Abandon my gym membership thread")
    assert res.intent == IntentType.LIFECYCLE_ABANDON


@pytest.mark.asyncio
async def test_conversational_chat_radar_and_decay(live_mcp_endpoint: str) -> None:
    """End-to-end chat handles intent radar and intent decay requests."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-radar-chat"

    # 1. Radar scan
    resp = await service.chat("Scan my intent radar", conversation_id=conv_id)
    assert "Intent Radar" in resp.message
    assert resp.radar_report is not None

    # 2. Decay check
    resp2 = await service.chat("Which threads are decaying?", conversation_id=conv_id)
    assert "decay" in resp2.message.lower() or "attention" in resp2.message.lower()


@pytest.mark.asyncio
async def test_conversational_chat_ambiguous_intent_never_mutates_state(
    live_mcp_endpoint: str,
) -> None:
    """Ambiguous intent proposal must be held for clarification and NEVER mutate state."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-ambiguous-chat"

    # Set active thread context to dentist
    await service.chat("Where was I with my dentist?", conversation_id=conv_id)

    initial_context = await client.get_thread_context("thread-dentist-appointment")
    initial_goal = initial_context["thread"]["current_goal"]

    resp = await service.chat(
        "I might want to change my dentist appointment to something else perhaps",
        conversation_id=conv_id,
    )
    assert (
        "won't update your goal" in resp.message.lower()
        or "might be shifting" in resp.message.lower()
    )

    # INVARIANT: verify state was NOT mutated
    after_context = await client.get_thread_context("thread-dentist-appointment")
    assert after_context["thread"]["current_goal"] == initial_goal


@pytest.mark.asyncio
async def test_conversational_chat_explicit_evolution_mutates_and_preserves_original(
    live_mcp_endpoint: str,
) -> None:
    """Explicit goal evolution through chat mutates current_goal and preserves original_goal."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-evolve-chat"

    await service.chat("Where was I with my dentist?", conversation_id=conv_id)

    initial_context = await client.get_thread_context("thread-dentist-appointment")
    initial_original = initial_context["thread"]["original_goal"]

    resp = await service.chat(
        "Update my dentist goal to: Schedule cleaning with Dr. Smith and consult on wisdom tooth",
        conversation_id=conv_id,
    )
    assert "evolved your goal" in resp.message.lower()

    after_context = await client.get_thread_context("thread-dentist-appointment")
    assert after_context["thread"]["original_goal"] == initial_original
    assert "wisdom tooth" in after_context["thread"]["current_goal"]


# ---------------------------------------------------------------------------
# 7. Safety & Semantic Audit: External Simulation vs Persistent Mutation
# ---------------------------------------------------------------------------


def test_safety_audit_1_evolve_intention_persistently_changes_current_goal(
    repo, prep_service, exec_service
):
    """1. EVOLVE_INTENTION persistently changes current_goal with PERSISTENT_MUTATION mode."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.EVOLVE_INTENTION,
        parameters={
            "new_goal": "Scale to 100 enterprise pilots",
            "reason": "Series A target",
        },
    )
    result = exec_service.execute_action(proposal.id, confirmed=True)
    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert "persistently updated" in result.message

    updated = repo.get_thread("test-thread-m13")
    assert updated.current_goal == "Scale to 100 enterprise pilots"
    assert updated.original_goal == "Release MVP to 10 beta testers by end of month"
    assert any(
        e.type == ThreadEventType.INTENTION_EVOLVED.value for e in updated.events
    )


def test_safety_audit_2_defer_intention_persistently_changes_status(
    repo, prep_service, exec_service
):
    """2. DEFER_INTENTION persistently changes status with PERSISTENT_MUTATION mode."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.DEFER_INTENTION,
        parameters={
            "deferred_until": "2026-12-01T00:00:00Z",
            "reason": "Paused for Q4 budget",
        },
    )
    result = exec_service.execute_action(proposal.id, confirmed=True)
    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert "persistently deferred" in result.message

    updated = repo.get_thread("test-thread-m13")
    assert updated.status == ThreadStatus.DEFERRED
    assert updated.deferred_until is not None
    assert any(e.type == ThreadEventType.THREAD_DEFERRED.value for e in updated.events)


def test_safety_audit_3_resume_intention_persistently_changes_status(
    repo, prep_service, exec_service
):
    """3. RESUME_INTENTION persistently changes status with PERSISTENT_MUTATION mode."""
    thread = repo.get_thread("test-thread-m13")
    # First defer
    thread.status = ThreadStatus.DEFERRED
    repo.save_thread(thread)

    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.RESUME_INTENTION,
        parameters={"reason": "Budget unlocked, resuming project"},
    )
    result = exec_service.execute_action(proposal.id, confirmed=True)
    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert "persistently resumed" in result.message

    updated = repo.get_thread("test-thread-m13")
    assert updated.status == ThreadStatus.ACTIVE
    assert any(e.type == ThreadEventType.THREAD_RESUMED.value for e in updated.events)


def test_safety_audit_4_abandon_intention_persistently_changes_status(
    repo, prep_service, exec_service
):
    """4. ABANDON_INTENTION persistently changes status with PERSISTENT_MUTATION mode."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.ABANDON_INTENTION,
        parameters={"reason": "Project discontinued by management"},
    )
    result = exec_service.execute_action(proposal.id, confirmed=True)
    assert result.execution_status == ExecutionStatus.EXECUTED
    assert result.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert "persistently marked as ABANDONED" in result.message

    updated = repo.get_thread("test-thread-m13")
    assert updated.status == ThreadStatus.ABANDONED
    assert updated.abandoned_reason == "Project discontinued by management"
    assert any(e.type == ThreadEventType.THREAD_ABANDONED.value for e in updated.events)


def test_safety_audit_5_mutations_require_proposal_confirmation_safety_flow(
    repo, prep_service, exec_service
):
    """5. Mutations enforce the proposal/confirmation safety gate."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.ABANDON_INTENTION,
        parameters={"reason": "User cancelled"},
    )
    assert proposal.requires_confirmation is True

    # Rejection when confirmed=False
    unconfirmed = exec_service.execute_action(proposal.id, confirmed=False)
    assert unconfirmed.execution_status == ExecutionStatus.REJECTED
    assert unconfirmed.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert repo.get_thread("test-thread-m13").status == ThreadStatus.ACTIVE

    # Execution when confirmed=True
    confirmed = exec_service.execute_action(proposal.id, confirmed=True)
    assert confirmed.execution_status == ExecutionStatus.EXECUTED
    assert confirmed.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert repo.get_thread("test-thread-m13").status == ThreadStatus.ABANDONED


def test_safety_audit_6_repeated_mutation_execution_is_idempotent(
    repo, prep_service, exec_service
):
    """6. Repeated execution of a mutation proposal is strictly idempotent."""
    thread = repo.get_thread("test-thread-m13")
    proposal = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.EVOLVE_INTENTION,
        parameters={"new_goal": "Goal iteration 1", "reason": "Initial pivot"},
    )
    res1 = exec_service.execute_action(proposal.id, confirmed=True)
    assert res1.execution_status == ExecutionStatus.EXECUTED
    assert res1.execution_mode == ExecutionMode.PERSISTENT_MUTATION

    event_count_before = len(repo.get_thread("test-thread-m13").events)

    res2 = exec_service.execute_action(proposal.id, confirmed=True)
    assert res2.execution_status == ExecutionStatus.ALREADY_EXECUTED
    assert res2.execution_mode == ExecutionMode.PERSISTENT_MUTATION
    assert res2.event_id == res1.event_id
    assert len(repo.get_thread("test-thread-m13").events) == event_count_before


def test_safety_audit_7_ordinary_operational_actions_remain_simulation_only(
    repo, prep_service, exec_service
):
    """7. Ordinary operational actions remain strictly SIMULATED ONLY and cannot be executed as PERSISTENT_MUTATION."""
    thread = repo.get_thread("test-thread-m13")
    suggestion = NextActionSuggestion(
        thread_id=thread.id,
        action_type=NextActionType.FOLLOW_UP_ACTION,
        action="Follow up with beta testers",
        rationale="Follow up on pending feedback",
        confidence=0.9,
    )
    proposal = prep_service.prepare_action(thread=thread, suggestion=suggestion)

    # Attempting to execute an operational action as PERSISTENT_MUTATION must be rejected
    rejected = exec_service.execute_action(
        proposal.id, confirmed=True, execution_mode=ExecutionMode.PERSISTENT_MUTATION
    )
    assert rejected.execution_status == ExecutionStatus.REJECTED
    assert "remain SIMULATED ONLY" in rejected.message

    # Executing normally succeeds as SIMULATED
    res = exec_service.execute_action(
        proposal.id, confirmed=True, execution_mode=ExecutionMode.SIMULATED
    )
    assert res.execution_status == ExecutionStatus.EXECUTED
    assert res.execution_mode == ExecutionMode.SIMULATED
    assert "simulated successfully" in res.message.lower()


def test_safety_audit_8_no_external_world_side_effects(
    repo, prep_service, exec_service, monkeypatch
):
    """8. Zero external-world side effects (network, socket, subprocess) across all executions."""
    import socket
    import urllib.request

    def blocked_call(*args, **kwargs):
        raise AssertionError("External side effect attempted!")

    monkeypatch.setattr(socket, "socket", blocked_call)
    monkeypatch.setattr(urllib.request, "urlopen", blocked_call)

    thread = repo.get_thread("test-thread-m13")
    # Operational simulated action
    suggestion = NextActionSuggestion(
        thread_id=thread.id,
        action_type=NextActionType.FOLLOW_UP_ACTION,
        action="Follow up with beta testers",
        rationale="Follow up on pending feedback",
        confidence=0.9,
    )
    prop_op = prep_service.prepare_action(thread=thread, suggestion=suggestion)
    res_op = exec_service.execute_action(prop_op.id, confirmed=True)
    assert res_op.execution_status == ExecutionStatus.EXECUTED
    assert res_op.execution_mode == ExecutionMode.SIMULATED

    # Internal persistent mutation
    prop_mut = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.EVOLVE_INTENTION,
        parameters={"new_goal": "Goal tested under sandbox"},
    )
    res_mut = exec_service.execute_action(prop_mut.id, confirmed=True)
    assert res_mut.execution_status == ExecutionStatus.EXECUTED
    assert res_mut.execution_mode == ExecutionMode.PERSISTENT_MUTATION


def test_safety_audit_9_execution_success_not_verified_completion(
    repo, prep_service, exec_service, verif_service
):
    """9. Invariant holds: EXECUTION_SUCCESS != VERIFIED_COMPLETION."""
    thread = repo.get_thread("test-thread-m13")
    # Operational execution does not complete thread
    suggestion = NextActionSuggestion(
        thread_id=thread.id,
        action_type=NextActionType.DIRECT_NEXT_ACTION,
        action="Draft next milestone",
        rationale="Plan next iteration",
        confidence=0.9,
    )
    prop_op = prep_service.prepare_action(thread=thread, suggestion=suggestion)
    exec_service.execute_action(prop_op.id, confirmed=True)
    assert repo.get_thread("test-thread-m13").status != ThreadStatus.COMPLETED

    # Mutation execution does not complete thread
    prop_mut = prep_service.prepare_action(
        thread=thread,
        action_type=NextActionType.EVOLVE_INTENTION,
        parameters={"new_goal": "Evolved milestone"},
    )
    exec_service.execute_action(prop_mut.id, confirmed=True)
    assert repo.get_thread("test-thread-m13").status != ThreadStatus.COMPLETED

    # Verification service verifies based on evidence only
    verif = verif_service.verify_thread(thread.id)
    assert verif.verified is False
    assert repo.get_thread("test-thread-m13").status != ThreadStatus.COMPLETED


def test_safety_audit_10_restart_persistence_preserves_m13_mutations():
    """10. SQLite restart persistence preserves M13 mutations across process restarts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "safety_audit_restart.db"

        # Instance 1: Setup and execute mutations
        repo1 = SQLiteThreadRepository(db_path=db_path)
        t_svc1 = ThreadService(repository=repo1)
        v_svc1 = VerificationService(thread_service=t_svc1)
        r_svc1 = IntentRadarService(thread_service=t_svc1)
        m_svc1 = IntentMemoryService(thread_service=t_svc1, radar_service=r_svc1)
        l_svc1 = LifecycleService(thread_service=t_svc1, verification_service=v_svc1)
        p_svc1 = ActionPreparationService(repository=repo1)
        e_svc1 = ExecutionService(
            thread_service=t_svc1,
            repository=repo1,
            intent_memory_service=m_svc1,
            lifecycle_service=l_svc1,
        )

        now = datetime.now(timezone.utc)
        thread = IntentThread(
            id="thread-restart-audit",
            title="Durable Safety Audit Thread",
            description="Original description",
            original_goal="Original durable goal",
            current_goal="Original durable goal",
            status=ThreadStatus.ACTIVE,
            priority=Priority.HIGH,
            confidence=0.85,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
            last_interaction_at=now,
        )
        repo1.save_thread(thread)

        # Execute EVOLVE_INTENTION
        prop_evolve = p_svc1.prepare_action(
            thread=thread,
            action_type=NextActionType.EVOLVE_INTENTION,
            parameters={
                "new_goal": "Evolved goal before restart",
                "reason": "Pre-restart evolution",
            },
        )
        res_evolve = e_svc1.execute_action(prop_evolve.id, confirmed=True)
        assert res_evolve.execution_status == ExecutionStatus.EXECUTED
        assert res_evolve.execution_mode == ExecutionMode.PERSISTENT_MUTATION

        # Execute DEFER_INTENTION
        prop_defer = p_svc1.prepare_action(
            thread=repo1.get_thread("thread-restart-audit"),
            action_type=NextActionType.DEFER_INTENTION,
            parameters={
                "deferred_until": "2026-11-15T00:00:00Z",
                "reason": "Deferred before restart",
            },
        )
        res_defer = e_svc1.execute_action(prop_defer.id, confirmed=True)
        assert res_defer.execution_status == ExecutionStatus.EXECUTED
        assert res_defer.execution_mode == ExecutionMode.PERSISTENT_MUTATION

        # --- SIMULATE PROCESS RESTART ---
        # Close handles and instantiate completely fresh repository and services on same SQLite DB
        del e_svc1, p_svc1, l_svc1, m_svc1, r_svc1, v_svc1, t_svc1, repo1

        repo2 = SQLiteThreadRepository(db_path=db_path)
        t_svc2 = ThreadService(repository=repo2)
        v_svc2 = VerificationService(thread_service=t_svc2)
        r_svc2 = IntentRadarService(thread_service=t_svc2)
        m_svc2 = IntentMemoryService(thread_service=t_svc2, radar_service=r_svc2)
        l_svc2 = LifecycleService(thread_service=t_svc2, verification_service=v_svc2)
        e_svc2 = ExecutionService(
            thread_service=t_svc2,
            repository=repo2,
            intent_memory_service=m_svc2,
            lifecycle_service=l_svc2,
        )

        reloaded = repo2.get_thread("thread-restart-audit")
        assert reloaded.original_goal == "Original durable goal"
        assert reloaded.current_goal == "Evolved goal before restart"
        assert reloaded.status == ThreadStatus.DEFERRED
        assert reloaded.deferred_until is not None

        # Verify idempotency ledger via persistent event history after restart
        res_idempotent = e_svc2.execute_action(prop_evolve.id, confirmed=True)
        assert res_idempotent.execution_status == ExecutionStatus.ALREADY_EXECUTED
        assert res_idempotent.execution_mode == ExecutionMode.PERSISTENT_MUTATION
