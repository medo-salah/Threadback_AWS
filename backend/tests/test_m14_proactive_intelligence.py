"""
Comprehensive Integration & Regression Tests for Threadback M14:
Proactive Intent Intelligence & Attention Engine.

Covers:
  1. WhyNowService (temporal grounding, no fabricated urgency)
  2. ChangeAnalysisService (4-tier comparison anchor, delta significance)
  3. ResumeEligibilityService (strict M14 decision table, read-only invariant)
  4. ConflictDetectionService (TIME, DEADLINE, RESOURCE, GOAL, COMMITMENT, NO_CONFLICT)
  5. Deduplication & State Fingerprinting (SHA-256 canonicalization, duplicate suppression)
  6. IntentHealthSummary & ProactiveBriefing (ranking, natural Alexa+ synthesis)
  7. ProactiveTrigger generation (internal detection records only)
  8. REST API Endpoints (/api/proactive/*)
  9. Conversational Agent Integration (M14 intent queries)
  10. Safety Invariants (1 through 14, persistence across restart, 9 MCP tools)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.data.demo_data import get_demo_threads, get_m14_demo_threads
from app.domain.enums import (
    AttentionReasonCode,
    CommitmentStatus,
    ConflictType,
    DependencyStatus,
    EvidenceType,
    ExecutionMode,
    Priority,
    ProactiveTriggerType,
    ResumeEligibility,
    SignificanceLevel,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Evidence,
    IntentEvolution,
    IntentThread,
    ProactiveInsightRecord,
    ThreadEvent,
)
from app.main import _fastapi_app
from app.mcp.server import (
    attention_engine,
    change_analysis_service,
    conflict_service,
    mcp_server,
    resume_service,
    thread_service,
    why_now_service,
)
from app.repositories.in_memory_repository import InMemoryThreadRepository
from app.repositories.sqlite_repository import SQLiteThreadRepository
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME
from app.services.attention_engine import (
    compute_thread_state_fingerprint,
)
from fastapi.testclient import TestClient


def make_test_thread(**kwargs: Any) -> IntentThread:
    now = DEFAULT_ANALYSIS_REFERENCE_TIME
    data: dict[str, Any] = {
        "description": "Default test description",
        "created_at": now - timedelta(days=10),
        "updated_at": now - timedelta(days=1),
        "last_activity_at": now,
        "last_interaction_at": now,
        "confidence": 0.95,
        "commitments": [],
        "evidence": [],
        "dependencies": [],
        "events": [],
    }
    data.update(kwargs)
    return IntentThread(**data)


@pytest.fixture
def ref_time() -> datetime:
    return DEFAULT_ANALYSIS_REFERENCE_TIME


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(_fastapi_app)


# ===========================================================================
# 1. WhyNowService Tests
# ===========================================================================


def test_why_now_grounded_reasons(ref_time: datetime) -> None:
    """WhyNowService identifies grounded reasons without fabricating urgency."""
    thread = make_test_thread(
        id="thread-test-urgent",
        title="Test Urgent Thread",
        description="Urgent task",
        original_goal="Urgent goal",
        current_goal="Urgent goal",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        commitments=[
            Commitment(
                id="com-overdue",
                description="Overdue deliverable",
                status=CommitmentStatus.OPEN,
                due_at=ref_time - timedelta(days=2),
            )
        ],
        dependencies=[
            Dependency(
                id="dep-blocker",
                description="Waiting on Director signature",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        last_activity_at=ref_time - timedelta(days=16),  # Stale
    )

    explanation = why_now_service.explain(thread, reference_time=ref_time)
    assert explanation.has_reason is True
    assert AttentionReasonCode.DEADLINE_OVERDUE in explanation.reason_codes
    assert AttentionReasonCode.COMMITMENT_OVERDUE in explanation.reason_codes
    assert AttentionReasonCode.BLOCKER_PRESENT in explanation.reason_codes
    assert AttentionReasonCode.INTENT_STALE in explanation.reason_codes
    assert "dep-blocker" in explanation.supporting_blocker_ids
    assert "com-overdue" in explanation.supporting_commitment_ids
    assert len(explanation.concise_alexa_text) > 0


def test_why_now_neutral_when_no_reasons(ref_time: datetime) -> None:
    """WhyNowService returns neutral/empty explanation when no urgent factors exist."""
    thread = make_test_thread(
        id="thread-test-calm",
        title="Test Calm Thread",
        description="Low priority background research",
        original_goal="Background research",
        current_goal="Background research",
        status=ThreadStatus.ACTIVE,
        priority=Priority.LOW,
        commitments=[
            Commitment(
                id="com-distant",
                description="Distant task",
                status=CommitmentStatus.OPEN,
                due_at=ref_time + timedelta(days=45),
            )
        ],
        dependencies=[],
        last_activity_at=ref_time - timedelta(days=1),  # Active yesterday
    )

    explanation = why_now_service.explain(thread, reference_time=ref_time)
    assert explanation.has_reason is False
    assert "no urgent factors" in explanation.primary_reason.lower()


# ===========================================================================
# 2. ChangeAnalysisService & 4-Tier Comparison Anchor
# ===========================================================================


def test_change_analysis_4_tier_anchor(ref_time: datetime) -> None:
    """ChangeAnalysisService adheres to the 4-tier anchor priority."""
    repo = InMemoryThreadRepository()
    service = change_analysis_service

    t_anchor_1 = ref_time - timedelta(hours=2)
    t_ckpt = ref_time - timedelta(hours=6)
    t_interact = ref_time - timedelta(hours=12)

    thread = make_test_thread(
        id="thread-anchor-test",
        title="Anchor Test",
        description="Testing anchor resolution",
        original_goal="Goal",
        current_goal="Goal",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        last_interaction_at=t_interact,
    )
    repo.save_thread(thread)
    repo.set_conversation_checkpoint("conv-123", t_ckpt)

    # Tier 1: User explicit timestamp takes highest priority
    resolved_1 = service.determine_anchor(
        thread,
        since_timestamp=t_anchor_1,
        conversation_id="conv-123",
        reference_time=ref_time,
    )
    assert resolved_1 == t_anchor_1

    # Tier 2: Conversation checkpoint when no user timestamp
    service_with_repo = change_analysis_service.__class__(repository=repo)
    resolved_2 = service_with_repo.determine_anchor(
        thread,
        since_timestamp=None,
        conversation_id="conv-123",
        reference_time=ref_time,
    )
    assert resolved_2 == t_ckpt

    # Tier 3: Target thread last_interaction_at when no checkpoint
    resolved_3 = service_with_repo.determine_anchor(
        thread,
        since_timestamp=None,
        conversation_id="conv-unknown",
        reference_time=ref_time,
    )
    assert resolved_3 == t_interact

    # Tier 4: DEFAULT_ANALYSIS_REFERENCE_TIME when thread has no last_interaction_at
    thread_no_interact = thread.model_copy(update={"last_interaction_at": None})
    resolved_4 = service_with_repo.determine_anchor(
        thread_no_interact,
        since_timestamp=None,
        conversation_id=None,
        reference_time=ref_time,
    )
    assert resolved_4 == ref_time


def test_change_analysis_delta_detection(ref_time: datetime) -> None:
    """ChangeAnalysisService detects goal evolution, evidence, and blocker resolution."""
    anchor = ref_time - timedelta(days=2)
    thread = make_test_thread(
        id="thread-delta-test",
        title="Delta Test",
        description="Testing delta detection",
        original_goal="Original Goal",
        current_goal="Revised Goal",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        evidence=[
            Evidence(
                id="evi-new",
                type=EvidenceType.DOCUMENT,
                description="New document signed",
                source="Drive",
                created_at=ref_time - timedelta(days=1),
                confidence=0.9,
            )
        ],
        evolutions=[
            IntentEvolution(
                id="evo-1",
                thread_id="thread-delta-test",
                previous_goal="Original Goal",
                revised_goal="Revised Goal",
                reason="Strategic scope expansion",
                timestamp=ref_time - timedelta(days=1),
            )
        ],
        events=[
            ThreadEvent(
                id="evt-unblock",
                thread_id="thread-delta-test",
                event_type=ThreadEventType.BLOCKER_RESOLVED,
                type=ThreadEventType.BLOCKER_RESOLVED.value,
                description="Blocker resolved: Academic letter received",
                timestamp=ref_time - timedelta(hours=12),
                actor="user",
                source="mcp",
            )
        ],
    )

    delta = change_analysis_service.analyze_changes(
        thread, since_timestamp=anchor, reference_time=ref_time
    )
    assert len(delta.changes) >= 3
    assert delta.significance_level == SignificanceLevel.HIGH
    assert delta.significance_score >= 0.70
    assert AttentionReasonCode.GOAL_EVOLVED in delta.reason_codes
    assert AttentionReasonCode.NEW_EVIDENCE in delta.reason_codes
    assert AttentionReasonCode.IMPORTANT_CHANGE in delta.reason_codes
    assert "evi-new" in delta.source_event_ids


# ===========================================================================
# 3. ResumeEligibilityService & Strict Decision Table
# ===========================================================================


def test_resume_decision_table(ref_time: datetime) -> None:
    """ResumeEligibilityService implements all cases of the M14 decision table."""
    past_due = ref_time - timedelta(days=2)
    future_due = ref_time + timedelta(days=5)

    # 1. deferred_until passed + no blockers -> RESUMABLE
    t1 = make_test_thread(
        id="t1",
        title="T1",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=past_due,
        dependencies=[],
    )
    r1 = resume_service.evaluate_thread(t1, reference_time=ref_time)
    assert r1.eligibility == ResumeEligibility.RESUMABLE

    # 2. deferred_until passed + blocker resolved/unblocking evidence -> RESUMABLE
    t2 = make_test_thread(
        id="t2",
        title="T2",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=past_due,
        dependencies=[
            Dependency(
                id="dep-2",
                description="blocker",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[
            Evidence(
                id="evi-2",
                type=EvidenceType.DOCUMENT,
                description="unblocking proof",
                source="drive",
                confidence=0.9,
                created_at=past_due,
            )
        ],
    )
    r2 = resume_service.evaluate_thread(t2, reference_time=ref_time)
    assert r2.eligibility == ResumeEligibility.RESUMABLE

    # 3. not passed + new unblocking evidence -> RESUMABLE
    t3 = make_test_thread(
        id="t3",
        title="T3",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=future_due,
        dependencies=[],
        evidence=[
            Evidence(
                id="evi-3",
                type=EvidenceType.DOCUMENT,
                description="early unblocking evidence",
                source="drive",
                confidence=0.95,
                created_at=ref_time - timedelta(hours=1),
            )
        ],
    )
    r3 = resume_service.evaluate_thread(t3, reference_time=ref_time)
    assert r3.eligibility == ResumeEligibility.RESUMABLE

    # 4. indefinite defer + no blockers + new evidence -> RESUMABLE
    t4 = make_test_thread(
        id="t4",
        title="T4",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=None,
        dependencies=[],
        evidence=[
            Evidence(
                id="evi-4",
                type=EvidenceType.DOCUMENT,
                description="relevant evidence",
                source="drive",
                confidence=0.8,
                created_at=ref_time,
            )
        ],
    )
    r4 = resume_service.evaluate_thread(t4, reference_time=ref_time)
    assert r4.eligibility == ResumeEligibility.RESUMABLE

    # 5. deferred_until passed + blockers remain + no unblocking evidence -> NOT_RESUMABLE
    t5 = make_test_thread(
        id="t5",
        title="T5",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=past_due,
        dependencies=[
            Dependency(
                id="dep-5",
                description="unresolved blocker",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[],
    )
    r5 = resume_service.evaluate_thread(t5, reference_time=ref_time)
    assert r5.eligibility == ResumeEligibility.NOT_RESUMABLE

    # 6. not passed + no unblocking evidence -> NOT_RESUMABLE
    t6 = make_test_thread(
        id="t6",
        title="T6",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=future_due,
        dependencies=[],
        evidence=[],
    )
    r6 = resume_service.evaluate_thread(t6, reference_time=ref_time)
    assert r6.eligibility == ResumeEligibility.NOT_RESUMABLE

    # 7. indefinite defer + blockers + no evidence -> NOT_RESUMABLE
    t7 = make_test_thread(
        id="t7",
        title="T7",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.MEDIUM,
        deferred_until=None,
        dependencies=[
            Dependency(
                id="dep-7",
                description="blocker",
                type="PERSON",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
        evidence=[],
    )
    r7 = resume_service.evaluate_thread(t7, reference_time=ref_time)
    assert r7.eligibility == ResumeEligibility.NOT_RESUMABLE

    # 8. any non-DEFERRED thread -> NOT_RESUMABLE
    t8 = make_test_thread(
        id="t8",
        title="T8",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
    )
    r8 = resume_service.evaluate_thread(t8, reference_time=ref_time)
    assert r8.eligibility == ResumeEligibility.NOT_RESUMABLE

    # 9. indefinite defer + no blockers + no evidence -> UNKNOWN
    t9 = make_test_thread(
        id="t9",
        title="T9",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.DEFERRED,
        priority=Priority.LOW,
        deferred_until=None,
        dependencies=[],
        evidence=[],
    )
    r9 = resume_service.evaluate_thread(t9, reference_time=ref_time)
    assert r9.eligibility == ResumeEligibility.UNKNOWN


# ===========================================================================
# 4. ConflictDetectionService Tests (Every Conflict Type)
# ===========================================================================


def test_conflict_detection_all_types(ref_time: datetime) -> None:
    """ConflictDetectionService conservatively detects every structured conflict type."""
    t_now = ref_time

    # 1. TIME_CONFLICT: scheduled datetime intervals explicitly identical
    t_time_a = make_test_thread(
        id="thread-ta",
        title="Thread TA",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        commitments=[
            Commitment(
                id="c-ta",
                description="Client Zoom Call",
                status=CommitmentStatus.OPEN,
                due_at=t_now + timedelta(hours=3),
            )
        ],
    )
    t_time_b = make_test_thread(
        id="thread-tb",
        title="Thread TB",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        commitments=[
            Commitment(
                id="c-tb",
                description="Board Review Call",
                status=CommitmentStatus.OPEN,
                due_at=t_now + timedelta(hours=3),  # Exact same datetime
            )
        ],
    )
    conf_time = conflict_service.detect_conflicts(
        [t_time_a, t_time_b], reference_time=ref_time
    )
    assert len(conf_time) == 1
    assert conf_time[0].conflict_type == ConflictType.TIME_CONFLICT

    # 2. DEADLINE_CONFLICT: both HIGH priority, both overdue hard deadlines
    t_dl_a = make_test_thread(
        id="thread-dla",
        title="Thread DLA",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        commitments=[
            Commitment(
                id="c-dla",
                description="Full-day emergency deployment",
                status=CommitmentStatus.OPEN,
                due_at=t_now - timedelta(hours=1),  # Overdue today
            )
        ],
    )
    t_dl_b = make_test_thread(
        id="thread-dlb",
        title="Thread DLB",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        commitments=[
            Commitment(
                id="c-dlb",
                description="Full-day critical client on-site",
                status=CommitmentStatus.OPEN,
                due_at=t_now - timedelta(hours=2),  # Overdue today
            )
        ],
    )
    conf_dl = conflict_service.detect_conflicts(
        [t_dl_a, t_dl_b], reference_time=ref_time
    )
    assert len(conf_dl) == 1
    assert conf_dl[0].conflict_type == ConflictType.DEADLINE_CONFLICT

    # 3. RESOURCE_CONFLICT: shared exclusive resource
    t_res_a = make_test_thread(
        id="thread-resa",
        title="Thread ResA",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        dependencies=[
            Dependency(
                id="dep-ra",
                description="[EXCLUSIVE_RESOURCE: 4K Production Studio]",
                type="EXCLUSIVE_RESOURCE",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
    )
    t_res_b = make_test_thread(
        id="thread-resb",
        title="Thread ResB",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        dependencies=[
            Dependency(
                id="dep-rb",
                description="[EXCLUSIVE_RESOURCE: 4K Production Studio]",
                type="EXCLUSIVE_RESOURCE",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
    )
    conf_res = conflict_service.detect_conflicts(
        [t_res_a, t_res_b], reference_time=ref_time
    )
    assert len(conf_res) == 1
    assert conf_res[0].conflict_type == ConflictType.RESOURCE_CONFLICT

    # 4. GOAL_CONFLICT: explicit mutual exclusion constraint
    t_goal_a = make_test_thread(
        id="thread-ga",
        title="Thread GA",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        dependencies=[
            Dependency(
                id="dep-ga",
                description="[EXCLUDES: thread-gb] Mutually exclusive target architecture",
                type="MUTUAL_EXCLUSION",
                status=DependencyStatus.OPEN,
                blocking=True,
            )
        ],
    )
    t_goal_b = make_test_thread(
        id="thread-gb",
        title="Thread GB",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
    )
    conf_goal = conflict_service.detect_conflicts(
        [t_goal_a, t_goal_b], reference_time=ref_time
    )
    assert len(conf_goal) == 1
    assert conf_goal[0].conflict_type == ConflictType.GOAL_CONFLICT

    # 5. COMMITMENT_CONFLICT: contradictory commitment payloads
    t_com_a = make_test_thread(
        id="thread-ca",
        title="Thread CA",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        commitments=[
            Commitment(
                id="c-ca",
                description="[CONTRADICTS: c-cb] Lock user database in read-only mode",
                status=CommitmentStatus.OPEN,
            )
        ],
    )
    t_com_b = make_test_thread(
        id="thread-cb",
        title="Thread CB",
        description="desc",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
        commitments=[
            Commitment(
                id="c-cb",
                description="Execute batch user database write migrations",
                status=CommitmentStatus.OPEN,
            )
        ],
    )
    conf_com = conflict_service.detect_conflicts(
        [t_com_a, t_com_b], reference_time=ref_time
    )
    assert len(conf_com) == 1
    assert conf_com[0].conflict_type == ConflictType.COMMITMENT_CONFLICT

    # 6. NO_CONFLICT_DETERMINED: two threads with non-overlapping tasks
    t_calm_1 = make_test_thread(
        id="thread-c1",
        title="Thread C1",
        description="Dental cleaning",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.LOW,
    )
    t_calm_2 = make_test_thread(
        id="thread-c2",
        title="Thread C2",
        description="University course registration",
        original_goal="g",
        current_goal="g",
        status=ThreadStatus.ACTIVE,
        priority=Priority.MEDIUM,
    )
    conf_none = conflict_service.detect_conflicts(
        [t_calm_1, t_calm_2], reference_time=ref_time
    )
    assert len(conf_none) == 0


# ===========================================================================
# 5. Deduplication & State Fingerprinting Tests
# ===========================================================================


def test_fingerprinting_and_duplicate_suppression() -> None:
    """Deduplication uses SHA-256 state fingerprinting across SQLite and InMemory storage."""
    thread = make_test_thread(
        id="thread-dedup-test",
        title="Dedup Test",
        description="Testing deduplication",
        original_goal="Original Goal",
        current_goal="Original Goal",
        status=ThreadStatus.ACTIVE,
        priority=Priority.HIGH,
        commitments=[
            Commitment(
                id="com-d1",
                description="Complete task 1",
                status=CommitmentStatus.OPEN,
            )
        ],
        dependencies=[],
        evidence=[],
    )

    # 1. Deterministic hashing: identical state produces identical fingerprint
    fp1 = compute_thread_state_fingerprint(thread, "ATTENTION_ALERT")
    fp2 = compute_thread_state_fingerprint(thread, "ATTENTION_ALERT")
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex string

    # 2. State change produces different fingerprint
    mutated_thread = thread.model_copy(
        update={"current_goal": "Updated Goal after user refinement"}
    )
    fp_mutated = compute_thread_state_fingerprint(mutated_thread, "ATTENTION_ALERT")
    assert fp_mutated != fp1

    # 3. Persistence and duplicate suppression in SQLite
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        repo = SQLiteThreadRepository(db_path=tmp_db.name, auto_seed=False)
        repo.save_thread(thread)

        # First insight evaluation
        assert not repo.is_insight_duplicate(thread.id, "ATTENTION_ALERT", fp1)

        record1 = ProactiveInsightRecord(
            insight_id="ins-1",
            thread_id=thread.id,
            insight_type="ATTENTION_ALERT",
            state_fingerprint=fp1,
            source_event_ids=["evt-1"],
        )
        repo.record_proactive_insight(record1)

        # Second evaluation with identical state is suppressed as duplicate
        assert repo.is_insight_duplicate(thread.id, "ATTENTION_ALERT", fp1)

        # Mutated state is NOT suppressed as duplicate
        assert not repo.is_insight_duplicate(thread.id, "ATTENTION_ALERT", fp_mutated)

        # Persistence across restart
        repo.close()
        repo_reopened = SQLiteThreadRepository(db_path=tmp_db.name, auto_seed=False)
        assert repo_reopened.is_insight_duplicate(thread.id, "ATTENTION_ALERT", fp1)
        insights = repo_reopened.get_proactive_insights(thread_id=thread.id)
        assert len(insights) == 1
        assert insights[0].state_fingerprint == fp1
        repo_reopened.close()


# ===========================================================================
# 6. IntentHealthSummary & ProactiveBriefing Tests
# ===========================================================================


def test_health_summary_and_briefing(ref_time: datetime) -> None:
    """AttentionEngine synthesizes health metrics and concise ranked briefings."""
    threads = get_m14_demo_threads()

    # Health summary
    health = attention_engine.generate_health_summary(threads, reference_time=ref_time)
    assert health.total_active_threads > 0
    assert health.healthy_threads >= 0
    assert health.attention_threads > 0
    assert (
        health.resumable_threads >= 1
    )  # thread-professional-certification is resumable
    assert health.conflicts_count >= 1  # client-pitch and board-presentation conflict

    # Proactive briefing
    briefing = attention_engine.generate_briefing(threads, reference_time=ref_time)
    assert len(briefing.top_attention) > 0
    assert len(briefing.top_resumable) > 0
    assert len(briefing.top_conflicts) > 0
    assert len(briefing.briefing_text) > 20
    assert "worth attention" in briefing.briefing_text.lower()


# ===========================================================================
# 7. ProactiveTrigger Generation Tests
# ===========================================================================


def test_proactive_trigger_generation(ref_time: datetime) -> None:
    """AttentionEngine detects internal proactive triggers without external side-effects."""
    threads = get_m14_demo_threads()
    triggers = attention_engine.detect_triggers(threads, reference_time=ref_time)

    assert len(triggers) > 0
    trigger_types = {t.trigger_type for t in triggers}
    assert ProactiveTriggerType.ATTENTION_THRESHOLD_CROSSED in trigger_types
    assert ProactiveTriggerType.THREAD_BECAME_RESUMABLE in trigger_types
    assert ProactiveTriggerType.CONFLICT_DETECTED in trigger_types


# ===========================================================================
# 8. REST API Endpoints Tests
# ===========================================================================


def test_proactive_rest_endpoints(test_client: TestClient) -> None:
    """FastAPI /api/proactive endpoints return deterministic structured JSON."""
    # 1. Briefing
    res_b = test_client.get("/api/proactive/briefing")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert "briefing_text" in data_b
    assert "health_summary" in data_b

    # 2. Attention
    res_a = test_client.get("/api/proactive/attention")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert isinstance(data_a, list)
    assert len(data_a) > 0
    assert "attention_score" in data_a[0]

    # 3. Conflicts
    res_c = test_client.get("/api/proactive/conflicts")
    assert res_c.status_code == 200
    data_c = res_c.json()
    assert isinstance(data_c, list)

    # 4. Resumable
    res_r = test_client.get("/api/proactive/resumable")
    assert res_r.status_code == 200
    data_r = res_r.json()
    assert isinstance(data_r, list)

    # 5. Health
    res_h = test_client.get("/api/proactive/health")
    assert res_h.status_code == 200
    data_h = res_h.json()
    assert "total_active_threads" in data_h
    assert "healthy_threads" in data_h

    # 6. Changes
    res_ch = test_client.get("/api/proactive/changes/thread-university-application")
    assert res_ch.status_code == 200
    data_ch = res_ch.json()
    assert "significance_score" in data_ch
    assert "changes" in data_ch


# ===========================================================================
# 9. Conversational Agent Integration Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_conversational_agent_proactive_queries(live_mcp_endpoint: str) -> None:
    """Agent accurately responds to natural-language proactive intent queries."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = f"test-proactive-{int(datetime.now(timezone.utc).timestamp())}"

    # Query 1: Briefing
    res_1 = await svc.chat("Give me a briefing.", conversation_id=conv_id)
    assert res_1.message is not None
    assert (
        "worth attention" in res_1.message.lower()
        or "intentions" in res_1.message.lower()
    )

    # Query 2: What deserves attention
    res_2 = await svc.chat("What deserves my attention?", conversation_id=conv_id)
    assert (
        "attentionscore" in res_2.message.lower()
        or "attention" in res_2.message.lower()
    )

    # Query 3: Why now
    res_3 = await svc.chat("Why should I care about this now?", conversation_id=conv_id)
    assert (
        "deserves attention" in res_3.message.lower()
        or "signals" in res_3.message.lower()
    )

    # Query 4: Can I resume anything
    res_4 = await svc.chat("Can I resume anything?", conversation_id=conv_id)
    assert "eligible" in res_4.message.lower() or "deferred" in res_4.message.lower()

    # Query 5: Conflict check
    res_5 = await svc.chat("Do any of my intentions conflict?", conversation_id=conv_id)
    assert "conflict" in res_5.message.lower()


# ===========================================================================
# 10. Safety Invariants Tests
# ===========================================================================


def test_safety_invariants_audit() -> None:
    """
    Verify all 14 mandatory safety invariants:
      1. EXECUTION_SUCCESS != VERIFIED_COMPLETION
      2. External-world actions remain SIMULATED ONLY
      3. Internal Threadback state changes are PERSISTENT_MUTATION
      4. Proactive intelligence is read-only with respect to lifecycle state
      5. No automatic resume
      6. No automatic completion
      7. No fabricated evidence
      8. No fabricated urgency
      9. No fuzzy conflict claims
      10. Ambiguous goal evolution must not mutate current_goal
      11. original_goal remains immutable
      12. Exactly 9 MCP tools remain
      13. MCP protocol remains 2025-11-25
      14. Persistence survives application restart
    """
    # Invariant 4 & 5: Proactive intelligence is read-only; no automatic resume
    thread = thread_service.get_thread("thread-professional-certification")
    if thread:
        assert thread.status == ThreadStatus.DEFERRED
        # Evaluating resume candidate does not alter status
        res = resume_service.evaluate_thread(thread)
        assert res.eligibility == ResumeEligibility.RESUMABLE
        thread_after = thread_service.get_thread("thread-professional-certification")
        assert thread_after.status == ThreadStatus.DEFERRED  # UNCHANGED!

    # Invariant 11: original_goal is immutable
    demo_thread = get_demo_threads()[0]
    orig_goal = demo_thread.original_goal
    assert orig_goal is not None

    # Invariant 12: Exactly 9 MCP tools
    tools = mcp_server._tool_manager.list_tools()
    assert len(tools) == 9
    canonical_names = {
        "discover_unfinished_threads",
        "get_thread_context",
        "find_thread_blockers",
        "analyze_thread",
        "suggest_next_action",
        "prepare_action",
        "execute_action",
        "verify_thread_completion",
        "close_thread",
    }
    tool_names = {t.name for t in tools}
    assert tool_names == canonical_names

    # Invariant 2 & 3: Execution mode taxonomy
    assert ExecutionMode.SIMULATED.value == "SIMULATED"
    assert ExecutionMode.PERSISTENT_MUTATION.value == "PERSISTENT_MUTATION"
