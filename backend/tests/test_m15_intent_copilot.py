"""
Comprehensive Integration & Regression Tests for Threadback M15:
Proactive Agent Experience & Intent Copilot.

Covers:
  1. Explainable Prioritization (Urgency vs Attention distinction)
  2. What-If Counterfactual Simulation (zero state mutation guarantee)
  3. Time-Budget Planning (15m, 30m, 120m constraints)
  4. Resume Where I Left Off (durable reconstruction & eligibility)
  5. Safe Closure Assistant (blockers vs verification proof)
  6. Contextual Follow-up Dialogue ("What first?" -> "Why?" -> "What if postpone?")
  7. Time-Budget & Closure Chat Queries
  8. Ambiguous Request Clarification (no guessing, zero mutation)
  9. Copilot REST API Endpoints (/api/copilot/*)
  10. Safety Invariants Audit (zero simulation mutation, 9 MCP tools, protocol 2025-11-25)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.data.demo_data import get_m14_demo_threads
from app.domain.enums import (
    AttentionLevel,
    CommitmentStatus,
    DecisionCardType,
    ExecutionMode,
    Priority,
    ThreadStatus,
    WhatIfScenarioType,
)
from app.domain.models import (
    Commitment,
    Dependency,
    IntentThread,
)
from app.main import _fastapi_app
from app.mcp.server import (
    intent_copilot_service,
    mcp_server,
    safe_closure_assistant,
    thread_service,
    time_budget_service,
    what_if_service,
)
from app.repositories.sqlite_repository import SQLiteThreadRepository
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME
from fastapi.testclient import TestClient


def make_test_thread(**kwargs: Any) -> IntentThread:
    now = DEFAULT_ANALYSIS_REFERENCE_TIME
    data: dict[str, Any] = {
        "description": "Default test description",
        "priority": Priority.MEDIUM,
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
# 1. Explainable Prioritization Tests
# ===========================================================================


def test_copilot_prioritization_urgency_vs_attention(ref_time: datetime) -> None:
    """Prioritizes threads clearly distinguishing Urgency from Attention."""
    threads = get_m14_demo_threads()
    priorities = intent_copilot_service.prioritize_threads(
        threads, reference_time=ref_time
    )

    assert len(priorities) > 0
    top = priorities[0]
    assert top.rank == 1
    assert top.thread_id is not None
    assert top.thread_title is not None
    assert isinstance(top.attention_level, AttentionLevel)

    # Distinguishes Urgency from Attention (not collapsed into single opaque score)
    assert 0.0 <= top.urgency_score <= 1.0
    assert 0.0 <= top.attention_score <= 1.0
    assert top.blocker_pressure >= 0.0
    assert top.deadline_pressure >= 0.0

    # Explainability fields
    assert len(top.why_it_ranks_high) > 0
    assert len(top.recommended_next_step) > 0
    assert "ranked #1" in top.why_it_ranks_high.lower()


# ===========================================================================
# 2. What-If Counterfactual Simulation Tests
# ===========================================================================


def test_what_if_simulation_read_only_zero_mutation(ref_time: datetime) -> None:
    """What-if simulation evaluates counterfactuals without mutating persistent state."""
    thread = thread_service.get_thread("thread-university-application")
    assert thread is not None
    initial_status = thread.status
    initial_blockers = [d.id for d in thread.active_blockers]
    initial_goal = thread.current_goal

    # Scenario 1: Postpone 14 days
    res_postpone = what_if_service.simulate(
        thread=thread,
        scenario=WhatIfScenarioType.POSTPONE,
        parameters={"days": 14},
        reference_time=ref_time,
    )
    assert res_postpone.label == "SIMULATION — NO STATE CHANGED"
    assert res_postpone.simulated_urgency >= 0.0
    assert res_postpone.simulated_attention >= 0.0
    assert len(res_postpone.deadline_impact_description) > 0
    assert len(res_postpone.simulation_summary) > 0

    # Scenario 2: Resolve Blocker
    res_unblock = what_if_service.simulate(
        thread=thread,
        scenario=WhatIfScenarioType.RESOLVE_BLOCKER,
        parameters={},
        reference_time=ref_time,
    )
    assert res_unblock.label == "SIMULATION — NO STATE CHANGED"
    # Resolving blocker should reduce or maintain urgency
    assert res_unblock.simulated_urgency <= res_unblock.original_urgency + 0.05
    assert "resolved" in res_unblock.blocker_impact_description.lower()

    # Scenario 3: Change Goal
    res_goal = what_if_service.simulate(
        thread=thread,
        scenario=WhatIfScenarioType.CHANGE_GOAL,
        parameters={"new_goal": "Apply for PhD instead of Masters"},
        reference_time=ref_time,
    )
    assert res_goal.label == "SIMULATION — NO STATE CHANGED"

    # MANDATORY SAFETY CHECK: Original thread in repository was NOT mutated!
    thread_after = thread_service.get_thread("thread-university-application")
    assert thread_after.status == initial_status
    assert [d.id for d in thread_after.active_blockers] == initial_blockers
    assert thread_after.current_goal == initial_goal


# ===========================================================================
# 3. Time-Budget Planning Tests
# ===========================================================================


def test_time_budget_planning(ref_time: datetime) -> None:
    """TimeBudgetService matches actionable tasks to time windows conservatively."""
    threads = get_m14_demo_threads()

    # Budget 1: Quick 15-minute slot
    plan_15 = time_budget_service.recommend(
        threads, available_minutes=15, reference_time=ref_time
    )
    assert plan_15.available_minutes == 15
    assert plan_15.selected_thread_id != "none"
    assert len(plan_15.expected_next_action) > 0
    assert len(plan_15.reason) > 0
    assert plan_15.estimated_duration_minutes is not None

    # Budget 2: 60-minute slot
    plan_60 = time_budget_service.recommend(
        threads, available_minutes=60, reference_time=ref_time
    )
    assert plan_60.available_minutes == 60
    assert plan_60.fits_budget is True

    # Empty landscape handling
    empty_plan = time_budget_service.recommend(
        [], available_minutes=30, reference_time=ref_time
    )
    assert empty_plan.selected_thread_id == "none"
    assert "no active" in empty_plan.reason.lower()


# ===========================================================================
# 4. Resume Where I Left Off Tests
# ===========================================================================


def test_resume_where_left_off_reconstruction(ref_time: datetime) -> None:
    """IntentCopilotService reconstructs context without mutating lifecycle state."""
    cert_thread = thread_service.get_thread("thread-professional-certification")
    assert cert_thread is not None
    assert cert_thread.status == ThreadStatus.DEFERRED

    context_text = intent_copilot_service.format_resume_context(
        cert_thread, reference_time=ref_time
    )
    assert "Professional Certification" in context_text
    assert "Original Goal" in context_text
    assert "Current Goal" in context_text
    assert "Resume Eligibility" in context_text
    assert "Recommended Next Step" in context_text

    # Read-only check: thread remains DEFERRED
    after = thread_service.get_thread("thread-professional-certification")
    assert after.status == ThreadStatus.DEFERRED


# ===========================================================================
# 5. Safe Closure Assistant Tests
# ===========================================================================


def test_safe_closure_assistant() -> None:
    """SafeClosureAssistant identifies whether closure is safe without closing."""
    threads = thread_service.list_threads(unfinished_only=False)
    candidates = safe_closure_assistant.evaluate_threads(threads)

    assert len(candidates) > 0

    # Blocked thread cannot be safely closed
    uni_cand = next(
        (c for c in candidates if c.thread_id == "thread-university-application"), None
    )
    assert uni_cand is not None
    assert uni_cand.is_safe_to_close is False
    assert uni_cand.active_blockers_count > 0
    assert "blocked" in uni_cand.closure_readiness_reason.lower()

    # Completed/abandoned threads are already terminal
    for c in candidates:
        if c.is_safe_to_close:
            assert c.active_blockers_count == 0
            assert c.open_commitments_count == 0
            assert c.verification_status == "VERIFIED"


# ===========================================================================
# 6. Intent Decision Cards Generation Tests
# ===========================================================================


def test_intent_decision_cards_generation(ref_time: datetime) -> None:
    """IntentCopilotService generates structured decision cards for dashboard."""
    threads = get_m14_demo_threads()
    cards = intent_copilot_service.generate_decision_cards(
        threads, reference_time=ref_time
    )

    assert len(cards) >= 3
    card_types = {c.card_type for c in cards}

    assert DecisionCardType.TOP_PRIORITY in card_types
    assert DecisionCardType.WHY_NOW in card_types
    assert DecisionCardType.TIME_BUDGET in card_types

    top_card = next(c for c in cards if c.card_type == DecisionCardType.TOP_PRIORITY)
    assert top_card.urgency_score is not None
    assert top_card.attention_score is not None
    assert len(top_card.recommended_action) > 0


# ===========================================================================
# 7. Contextual Follow-up Dialogue Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_copilot_conversational_follow_ups(live_mcp_endpoint: str) -> None:
    """Agent handles multi-turn contextual follow-ups preserving active thread context."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = f"test-copilot-{int(datetime.now(timezone.utc).timestamp())}"

    # Turn 1: "What should I deal with first?"
    res_1 = await svc.chat("What should I deal with first?", conversation_id=conv_id)
    assert res_1.message is not None
    assert "urgency" in res_1.message.lower()
    assert "attention" in res_1.message.lower()
    assert "deal with" in res_1.message.lower()

    session = svc.conversation_manager.get(conv_id)
    assert session is not None
    assert session.active_thread_id is not None
    active_thread_turn1 = session.active_thread_id

    # Turn 2: Contextual "Why is this important?"
    res_2 = await svc.chat("Why is this important?", conversation_id=conv_id)
    assert (
        active_thread_turn1 in res_2.message
        or "important right now" in res_2.message.lower()
    )

    # Turn 3: Contextual "What if I postpone it?"
    res_3 = await svc.chat("What if I postpone it?", conversation_id=conv_id)
    assert "[simulation — no state changed]" in res_3.message.lower()
    assert "urgency" in res_3.message.lower()

    # Turn 4: Contextual "Help me deal with this"
    res_4 = await svc.chat("Help me deal with this", conversation_id=conv_id)
    assert (
        "let's move" in res_4.message.lower()
        or "recommended action" in res_4.message.lower()
    )


# ===========================================================================
# 8. Time-Budget & Closure Chat Queries
# ===========================================================================


@pytest.mark.asyncio
async def test_copilot_conversational_time_and_closure(live_mcp_endpoint: str) -> None:
    """Agent handles time-budget queries and safe-closure inquiries."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = f"test-time-closure-{int(datetime.now(timezone.utc).timestamp())}"

    # Query 1: Time budget
    res_time = await svc.chat(
        "I have 30 minutes. What can I realistically finish?", conversation_id=conv_id
    )
    assert "30 minutes" in res_time.message
    assert "target intention" in res_time.message.lower()

    # Query 2: Safe closure
    res_close = await svc.chat("Can I close anything?", conversation_id=conv_id)
    assert "closure" in res_close.message.lower()
    assert (
        "verification-gated" in res_close.message.lower()
        or "never closes" in res_close.message.lower()
    )

    # Query 3: What is blocking me
    res_block = await svc.chat("What is blocking me the most?", conversation_id=conv_id)
    assert (
        "blocked" in res_block.message.lower() or "blocker" in res_block.message.lower()
    )

    # Query 4: Options
    res_opts = await svc.chat("What are my options?", conversation_id=conv_id)
    assert "prioritize" in res_opts.message.lower()
    assert "what-if" in res_opts.message.lower()


# ===========================================================================
# 9. Ambiguous Request Clarification Test
# ===========================================================================


@pytest.mark.asyncio
async def test_ambiguous_request_requires_clarification(live_mcp_endpoint: str) -> None:
    """Ambiguous requests without active thread context prompt clarification without mutating state."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = f"test-ambig-{int(datetime.now(timezone.utc).timestamp())}"

    # An ambiguous command with pronoun and no active thread
    res = await svc.chat("Help me deal with it", conversation_id=conv_id)
    assert (
        "multiple active intentions" in res.message.lower()
        or "which one" in res.message.lower()
    )
    assert res.pending_confirmation is False


# ===========================================================================
# 10. Copilot REST API Endpoints Tests
# ===========================================================================


def test_copilot_rest_endpoints(test_client: TestClient) -> None:
    """All /api/copilot/* REST endpoints return expected structured models."""
    # 1. Overview
    r_overview = test_client.get("/api/copilot/overview")
    assert r_overview.status_code == 200
    ov_data = r_overview.json()
    assert "primary_recommendation" in ov_data
    assert "ranked_priorities" in ov_data
    assert "decision_cards" in ov_data

    # 2. Priorities
    r_prio = test_client.get("/api/copilot/priorities")
    assert r_prio.status_code == 200
    prio_data = r_prio.json()
    assert isinstance(prio_data, list)
    if prio_data:
        assert "urgency_score" in prio_data[0]
        assert "attention_score" in prio_data[0]

    # 3. What-If Simulation
    r_whatif = test_client.post(
        "/api/copilot/what-if",
        json={
            "thread_id": "thread-university-application",
            "scenario": "POSTPONE",
            "parameters": {"days": 7},
        },
    )
    assert r_whatif.status_code == 200
    whatif_data = r_whatif.json()
    assert whatif_data["label"] == "SIMULATION — NO STATE CHANGED"
    assert "simulated_urgency" in whatif_data

    # 4. Time Budget
    r_budget = test_client.get("/api/copilot/time-budget?available_minutes=45")
    assert r_budget.status_code == 200
    b_data = r_budget.json()
    assert b_data["available_minutes"] == 45
    assert "fits_budget" in b_data

    # 5. Safe Closure
    r_closure = test_client.get("/api/copilot/safe-closure")
    assert r_closure.status_code == 200
    cl_data = r_closure.json()
    assert isinstance(cl_data, list)

    # 6. Decision Cards
    r_cards = test_client.get("/api/copilot/decision-cards")
    assert r_cards.status_code == 200
    cards_data = r_cards.json()
    assert isinstance(cards_data, list)


# ===========================================================================
# 11. Safety Invariants Tests
# ===========================================================================


def test_safety_invariants_copilot() -> None:
    """Verify safety invariants for M15 Intent Copilot."""
    # Invariant: exactly 9 canonical tools
    tools = mcp_server._tool_manager.list_tools()
    assert len(tools) == 9
    canonical = {
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
    assert {t.name for t in tools} == canonical

    # Invariant: Simulation labels
    assert ExecutionMode.SIMULATED.value == "SIMULATED"
    assert ExecutionMode.PERSISTENT_MUTATION.value == "PERSISTENT_MUTATION"

    # Invariant: Persistence across restart
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        repo1 = SQLiteThreadRepository(db_path=tmp.name, auto_seed=True)
        th = repo1.get_thread("thread-university-application")
        assert th is not None
        del repo1

        repo2 = SQLiteThreadRepository(db_path=tmp.name, auto_seed=False)
        th2 = repo2.get_thread("thread-university-application")
        assert th2 is not None
        assert th2.id == th.id


def test_what_if_conservative_cross_thread_consequences() -> None:
    """
    Focused verification of conservative cross-thread consequence rules:
      1. Explicit dependency -> related impact reported with structured relationship evidence.
      2. Explicit conflict -> related impact reported with structured relationship evidence.
      3. Unrelated threads -> no impact reported (affected_related_thread_ids == []).
      4. Natural-language similarity alone -> no impact reported.
      5. Simulation leaves database/original objects byte-for-byte behaviorally unchanged.
    """
    ref_time = DEFAULT_ANALYSIS_REFERENCE_TIME

    # Setup thread A and thread B with explicit dependency (B depends on A)
    th_a = make_test_thread(
        id="thread-alpha-core",
        title="Alpha Core Infrastructure",
        status=ThreadStatus.ACTIVE,
    )
    th_b = make_test_thread(
        id="thread-beta-service",
        title="Beta Microservice",
        status=ThreadStatus.ACTIVE,
        dependencies=[
            Dependency(
                id="dep-thread-alpha-core",
                description="Waiting on thread-alpha-core release",
                blocking=True,
            )
        ],
    )

    # Setup thread C: completely unrelated
    th_c = make_test_thread(
        id="thread-gamma-unrelated",
        title="Dentist Visit Routine",
        status=ThreadStatus.ACTIVE,
    )

    # Setup thread D: high lexical similarity to thread A, but NO structured relationship
    th_d = make_test_thread(
        id="thread-delta-similar-nlp",
        title="Alpha Core Infrastructure Documentation",
        description="Alpha Core Infrastructure setup guide and deployment notes",
        status=ThreadStatus.ACTIVE,
    )

    landscape = [th_a, th_b, th_c, th_d]

    # Deep copy baseline snapshots to verify zero mutation
    snapshot_a = th_a.model_dump_json()
    snapshot_b = th_b.model_dump_json()
    snapshot_c = th_c.model_dump_json()
    snapshot_d = th_d.model_dump_json()

    # Case 1: Postpone th_a -> th_b has explicit dependency -> must be reported!
    res_a = what_if_service.simulate(
        thread=th_a,
        scenario=WhatIfScenarioType.POSTPONE,
        parameters={"days": 14},
        all_threads=landscape,
        reference_time=ref_time,
    )

    # 1. Explicit dependency reported
    assert "thread-beta-service" in res_a.affected_related_thread_ids
    assert len(res_a.relationship_evidence) > 0
    assert "explicit dependency" in res_a.relationship_evidence[0].lower()

    # 3. Unrelated threads NOT reported
    assert "thread-gamma-unrelated" not in res_a.affected_related_thread_ids

    # 4. Natural-language similarity alone NOT reported
    assert "thread-delta-similar-nlp" not in res_a.affected_related_thread_ids

    # Case 2: Explicit conflict (TIME_CONFLICT)
    # Create two threads with overlapping scheduled commitment windows
    th_conf_1 = make_test_thread(
        id="thread-interview-live",
        title="Live Interview A",
        status=ThreadStatus.ACTIVE,
        commitments=[
            Commitment(
                id="com-slot-1",
                description="Interview Slot A",
                status=CommitmentStatus.OPEN,
                due_at=ref_time + timedelta(days=2),
            )
        ],
    )
    th_conf_2 = make_test_thread(
        id="thread-interview-conflict",
        title="Conflicting Interview B",
        status=ThreadStatus.ACTIVE,
        commitments=[
            Commitment(
                id="com-slot-2",
                description="Double-booked Slot B",
                status=CommitmentStatus.OPEN,
                due_at=ref_time + timedelta(days=2),
            )
        ],
    )
    res_conf = what_if_service.simulate(
        thread=th_conf_1,
        scenario=WhatIfScenarioType.IGNORE_TEMPORARILY,
        all_threads=[th_conf_1, th_conf_2],
        reference_time=ref_time,
    )
    assert "thread-interview-conflict" in res_conf.affected_related_thread_ids
    assert any(
        "explicit conflict" in ev.lower() or "time_conflict" in ev.lower()
        for ev in res_conf.relationship_evidence
    )

    # Case 3: Completely unrelated threads in simulation
    res_unrelated = what_if_service.simulate(
        thread=th_c,
        scenario=WhatIfScenarioType.POSTPONE,
        all_threads=[th_c, th_d],
        reference_time=ref_time,
    )
    assert res_unrelated.affected_related_thread_ids == []
    assert res_unrelated.relationship_evidence == []

    # 5. Simulation leaves original domain objects byte-for-byte behaviorally identical
    assert th_a.model_dump_json() == snapshot_a
    assert th_b.model_dump_json() == snapshot_b
    assert th_c.model_dump_json() == snapshot_c
    assert th_d.model_dump_json() == snapshot_d
    assert res_a.label == "SIMULATION — NO STATE CHANGED"


def test_agent_provider_persistence_boundary() -> None:
    """
    Verify architectural invariant:
      Agent / Provider -> Application/Domain Service -> Repository -> SQLite.
      Agent and ModelProvider must NEVER directly write SQLite or bypass domain services.
    """
    from app.services.thread_service import ThreadService

    # 1. ThreadService encapsulates conversation checkpoints
    ts = ThreadService()
    conv_id = f"test-arch-boundary-{datetime.now().timestamp()}"
    now_time = datetime.now(timezone.utc)
    ts.set_conversation_checkpoint(conversation_id=conv_id, last_seen_at=now_time)
    retrieved = ts.get_conversation_checkpoint(conv_id)
    assert retrieved is not None
    assert abs((retrieved - now_time).total_seconds()) < 1.0

    # 2. AgentService routes mutations via ThreadService and MCP
    agent = AgentService(provider=MockModelProvider())
    assert hasattr(agent.provider, "process_message")
    # Verify MockModelProvider does not have direct repository write attributes
    assert not hasattr(agent.provider, "sqlite_connection")
    assert not hasattr(agent.provider, "db")
