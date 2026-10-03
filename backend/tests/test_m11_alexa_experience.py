"""
Milestone M11 Tests — Alexa+ Experience & Hackathon Readiness.

Validates:
  - Natural-language conversational routing for all 9 core flows
  - Conversational continuity and pronoun resolution ('it', 'that', 'this', 'the application')
  - Ambiguous thread handling (requests clarification when multiple threads exist and no context)
  - Unknown thread handling ('I couldn't find an unfinished intention matching that...')
  - Strict confirmation safety (ambiguous statements like 'maybe', 'sounds good' never execute)
  - Explicit confirmation executes in SIMULATED mode only
  - Deterministic verification cannot be hallucinated or bypassed
  - Lifecycle closure is strictly protected by verification
  - Complete 9-Phase University Application demo walkthrough
"""

from __future__ import annotations

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.domain.enums import EvidenceType
from app.domain.models import Evidence
from app.mcp.server import thread_service


@pytest.mark.asyncio
async def test_m11_conversational_discovery(live_mcp_endpoint: str) -> None:
    """Phase 1 / Discovery: 'What am I forgetting?' identifies unfinished intentions naturally."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-discovery"

    res = await service.chat("What am I forgetting?", conversation_id=conv_id)
    assert res.pending_confirmation is False
    assert "university application" in res.message.lower()
    # Checks that discover_unfinished_threads and analyze_thread were called
    assert any(act.tool_name == "discover_unfinished_threads" for act in res.activities)
    assert any(act.tool_name == "analyze_thread" for act in res.activities)
    # Session maintains active thread for conversational continuity
    session = service.conversation_manager.get(conv_id)
    assert session is not None
    assert session.active_thread_id == "thread-university-application"


@pytest.mark.asyncio
async def test_m11_context_reconstruction_with_continuity(
    live_mcp_endpoint: str,
) -> None:
    """Phase 2 / Reconstruct: pronoun 'it' or 'leave off' resolves to active context from prior turn."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-reconstruct-continuity"

    # Turn 1: Discovery sets active context to University Application
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Turn 2: Natural pronoun query without repeating full thread name
    res = await service.chat("Where did I leave off?", conversation_id=conv_id)
    assert "university application" in res.message.lower()
    assert "status:" in res.message.lower() or "blocked" in res.message.lower()
    assert any(act.tool_name == "get_thread_context" for act in res.activities)
    assert any(act.tool_name == "analyze_thread" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_blocker_investigation(live_mcp_endpoint: str) -> None:
    """Phase 3 / Blocker: 'Why haven't I finished it?' uses find_thread_blockers and explains naturally."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-blocker"

    # Turn 1: Discover to set active context
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Turn 2: Blocker query using pronoun
    res = await service.chat("Why haven't I finished it?", conversation_id=conv_id)
    assert "blocked" in res.message.lower()
    assert "recommendation" in res.message.lower()
    assert any(act.tool_name == "find_thread_blockers" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_next_action_recommendation(live_mcp_endpoint: str) -> None:
    """Phase 4 / Next Action: 'What should I do?' suggests next action and informs confirmation needed."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-next-action"

    # Turn 1: Discover
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Turn 2: Next action query
    res = await service.chat("What should I do?", conversation_id=conv_id)
    assert (
        "recommended action" in res.message.lower()
        or "next step" in res.message.lower()
    )
    assert any(act.tool_name == "suggest_next_action" for act in res.activities)
    # Does not execute or prepare yet
    assert res.pending_confirmation is False


@pytest.mark.asyncio
async def test_m11_action_preparation_requires_confirmation(
    live_mcp_endpoint: str,
) -> None:
    """Phase 5 / Prepare: 'Help me finish it.' prepares proposal and pauses for confirmation."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-prepare"

    # Turn 1: Discover
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Turn 2: Prepare action
    res = await service.chat("Help me finish it.", conversation_id=conv_id)
    assert res.pending_confirmation is True
    assert res.proposal_id is not None
    assert "simulated" in res.message.lower()
    assert "confirm" in res.message.lower()
    assert any(act.tool_name == "prepare_action" for act in res.activities)
    # execute_action was NOT called in the same turn
    assert not any(act.tool_name == "execute_action" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_confirmation_safety_ambiguous_never_executes(
    live_mcp_endpoint: str,
) -> None:
    """Safety: Ambiguous responses ('maybe', 'sounds good', etc.) MUST NOT execute the proposal."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-safety-ambiguous"

    # Prepare an action on university application
    await service.chat(
        "Help me finish the university application.", conversation_id=conv_id
    )
    session = service.conversation_manager.get(conv_id)
    assert session is not None
    assert session.pending_confirmation is True
    proposal_id = session.pending_proposal_id

    ambiguous_responses = [
        "maybe",
        "what happens if you do it?",
        "sounds good",
        "okay, what would that do?",
        "tell me more",
    ]

    for amb in ambiguous_responses:
        res = await service.chat(amb, conversation_id=conv_id)
        # MUST NOT execute
        assert res.pending_confirmation is True
        assert res.proposal_id == proposal_id
        assert (
            "explicit authorization" in res.message.lower()
            or "requires explicit" in res.message.lower()
        )
        assert not any(act.tool_name == "execute_action" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_confirmation_safety_explicit_executes_simulation_only(
    live_mcp_endpoint: str,
) -> None:
    """Phase 6 / Confirm: Explicit confirmation executes strictly in SIMULATED mode."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-confirm-exec"

    # Prepare action on client report
    await service.chat("Help me finish the client report.", conversation_id=conv_id)

    # Confirm explicitly
    res = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert res.pending_confirmation is False
    assert res.execution_status in ("EXECUTED", "ALREADY_EXECUTED")
    assert res.execution_mode == "SIMULATED"
    assert "simulated" in res.message.lower()
    assert any(act.tool_name == "execute_action" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_verification_truthfulness_unverified_then_verified(
    live_mcp_endpoint: str,
) -> None:
    """Phase 8 / Verify: Truthful reporting of unverified vs verified states based on factual evidence."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-verify-truth"

    # Set context
    await service.chat(
        "Where did I leave off with the university application?",
        conversation_id=conv_id,
    )

    # Check verification before evidence: must NOT be verified
    res1 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "not verified" in res1.message.lower() or "not yet" in res1.message.lower()
    assert any(act.tool_name == "verify_thread_completion" for act in res1.activities)

    # Introduce resolving evidence
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-m11-verified",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="University Portal",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.99,
        ),
    )

    # Check verification after evidence: must BE verified
    res2 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "verified" in res2.message.lower()
    assert "complete" in res2.message.lower()


@pytest.mark.asyncio
async def test_m11_closure_protection_cannot_bypass_verification(
    live_mcp_endpoint: str,
) -> None:
    """Phase 9 / Closure: Protected lifecycle prevents closing unverified threads."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-closure-protected"

    # Query unverified client report thread
    await service.chat(
        "Where did I leave off with the client report?", conversation_id=conv_id
    )

    # Attempt to close unverified thread
    res = await service.chat("Close it.", conversation_id=conv_id)
    assert (
        "cannot close" in res.message.lower()
        or "not been verified" in res.message.lower()
    )
    assert any(act.tool_name == "verify_thread_completion" for act in res.activities)
    assert not any(act.tool_name == "close_thread" for act in res.activities)


@pytest.mark.asyncio
async def test_m11_ambiguous_thread_requests_clarification(
    live_mcp_endpoint: str,
) -> None:
    """Ambiguity: When multiple unfinished threads exist and no context is set, ask for clarification."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-ambiguous-clarification"

    # Ambiguous pronoun query with NO prior turn or context
    res = await service.chat("Why haven't I finished it?", conversation_id=conv_id)
    assert "multiple" in res.message.lower() or "which" in res.message.lower()

    # User provides clarification
    res2 = await service.chat("The university application", conversation_id=conv_id)
    assert "university application" in res2.message.lower()
    assert "recommendation" in res2.message.lower() or "blocked" in res2.message.lower()


@pytest.mark.asyncio
async def test_m11_unknown_thread_handling(live_mcp_endpoint: str) -> None:
    """Unknown: Gracefully handle queries for unknown intentions."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-m11-unknown"

    res = await service.chat(
        "Where did I leave off with my trip to Mars?", conversation_id=conv_id
    )
    assert (
        "couldn't find" in res.message.lower() or "more context" in res.message.lower()
    )


@pytest.mark.asyncio
async def test_m11_canonical_9_phase_university_application_demo(
    live_mcp_endpoint: str,
) -> None:
    """
    Complete end-to-end multi-turn University Application demo walkthrough across all 9 phases:
      Phase 1: Discover ('What am I forgetting?')
      Phase 2: Reconstruct ('Where did I leave off?')
      Phase 3: Understand Blocker ('Why haven't I finished it?')
      Phase 4: Next Action ('What should I do?')
      Phase 5: Prepare Action ('Help me finish it.')
      Phase 6: Confirm Action ('Yes, go ahead.')
      Phase 7: New Evidence (Add recommendation letter received)
      Phase 8: Verify ('Is it actually finished?')
      Phase 9: Close ('Close it.')
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "canonical-demo-m11-university-app"

    # Phase 1: Discover
    p1 = await service.chat("What am I forgetting?", conversation_id=conv_id)
    assert "university application" in p1.message.lower()
    assert any(act.tool_name == "discover_unfinished_threads" for act in p1.activities)

    # Phase 2: Reconstruct
    p2 = await service.chat("Where did I leave off?", conversation_id=conv_id)
    assert "university application" in p2.message.lower()
    assert any(act.tool_name == "get_thread_context" for act in p2.activities)

    # Phase 3: Understand Blocker
    p3 = await service.chat("Why haven't I finished it?", conversation_id=conv_id)
    assert "blocked" in p3.message.lower()
    assert "recommendation" in p3.message.lower()
    assert any(act.tool_name == "find_thread_blockers" for act in p3.activities)

    # Phase 4: Next Action
    p4 = await service.chat("What should I do?", conversation_id=conv_id)
    assert (
        "recommended action" in p4.message.lower() or "next step" in p4.message.lower()
    )
    assert any(act.tool_name == "suggest_next_action" for act in p4.activities)

    # Phase 5: Prepare Action
    p5 = await service.chat("Help me finish it.", conversation_id=conv_id)
    assert p5.pending_confirmation is True
    assert p5.proposal_id is not None
    assert "simulated" in p5.message.lower()
    assert any(act.tool_name == "prepare_action" for act in p5.activities)
    assert not any(act.tool_name == "execute_action" for act in p5.activities)

    # Phase 6: Confirm Action
    p6 = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert p6.pending_confirmation is False
    assert p6.execution_status in ("EXECUTED", "ALREADY_EXECUTED")
    assert p6.execution_mode == "SIMULATED"
    assert any(act.tool_name == "execute_action" for act in p6.activities)

    # Phase 7: External evidence arrival
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-phase7-rec-received",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="Admissions Office",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.99,
        ),
    )

    # Phase 8: Verify Completion
    p8 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "verified" in p8.message.lower()
    assert any(act.tool_name == "verify_thread_completion" for act in p8.activities)

    # Phase 9: Close Thread
    p9 = await service.chat("Close it.", conversation_id=conv_id)
    assert "complete" in p9.message.lower()
    assert any(act.tool_name == "verify_thread_completion" for act in p9.activities)
    assert any(act.tool_name == "close_thread" for act in p9.activities)
