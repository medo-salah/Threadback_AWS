"""
Regression Tests for Expanded Alexa+ Conversational Coverage.

Validates:
1. General/Unrelated Conversation (Greetings, Thanks, Capabilities, Out-of-Scope)
   - Zero MCP tools invoked
   - Transparent responses without data fabrication
2. Natural-Language Intent Recognition across varied phrasing:
   - Discovery ("What am I forgetting?", "Did I leave anything unfinished?", "Is there anything I still need to deal with?")
   - Context / Reconstruction ("Where was I with my application?", "Can you remind me what I had done?", "What happened with that application?")
   - Blocker Investigation ("Why isn't it finished?", "What's holding this up?", "What's blocking me?")
   - Next Action ("What should I do now?", "What's my next step?")
   - Prepare Action ("Can you help me do that?", "Let's take care of it.")
   - Confirmation Safety & Execution ("Yes, do it.", "Go ahead.")
   - Verification ("Is it actually finished?", "Did I complete it?")
   - Closure ("Close it.", "I'm done with it.")
3. Contextual Multi-turn Follow-ups (active_thread_id preservation)
4. Ambiguous reference handling without silent switching
5. Unknown thread handling without data fabrication
6. Complete canonical 9-phase demo preservation
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
async def test_general_conversation_zero_mcp_activity(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 1 & 8: Greetings, thanks, capabilities, and out-of-scope questions invoke zero MCP tools."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-gen-conv"

    # A: Greeting
    res_greet = await service.chat("Hello", conversation_id=conv_id)
    assert res_greet.pending_confirmation is False
    assert len(res_greet.activities) == 0
    assert "threadback" in res_greet.message.lower()

    # Greeting variation
    res_greet2 = await service.chat("Hi there", conversation_id=conv_id)
    assert len(res_greet2.activities) == 0
    assert "threadback" in res_greet2.message.lower()

    # B: Capabilities
    res_cap1 = await service.chat("What can you help me with?", conversation_id=conv_id)
    assert len(res_cap1.activities) == 0
    assert (
        "intent-recovery" in res_cap1.message.lower()
        or "help" in res_cap1.message.lower()
    )
    assert "discover" in res_cap1.message.lower()

    # C: About Threadback
    res_cap2 = await service.chat("What is Threadback?", conversation_id=conv_id)
    assert len(res_cap2.activities) == 0
    assert "threadback" in res_cap2.message.lower()

    # H: Thanks
    res_thanks = await service.chat("Thanks", conversation_id=conv_id)
    assert len(res_thanks.activities) == 0
    assert "welcome" in res_thanks.message.lower()

    # Out-of-scope question
    res_weather = await service.chat(
        "What is the weather today in Seattle?", conversation_id=conv_id
    )
    assert len(res_weather.activities) == 0
    assert "don't have information" in res_weather.message.lower()

    # Out-of-scope chitchat
    res_joke = await service.chat("Tell me a joke", conversation_id=conv_id)
    assert len(res_joke.activities) == 0
    assert "don't have information" in res_joke.message.lower()


@pytest.mark.asyncio
async def test_natural_variations_discovery(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Discovery."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)

    discovery_phrases = [
        "What am I forgetting?",
        "Did I leave anything unfinished?",
        "Is there anything I still need to deal with?",
        "Do I have any open commitments?",
        "What's on my plate?",
        "Show me my open threads",
    ]

    for idx, phrase in enumerate(discovery_phrases):
        conv_id = f"test-disc-var-{idx}"
        res = await service.chat(phrase, conversation_id=conv_id)
        assert res.pending_confirmation is False
        assert "university application" in res.message.lower()
        assert any(
            act.tool_name == "discover_unfinished_threads" for act in res.activities
        )
        assert any(act.tool_name == "analyze_thread" for act in res.activities)


@pytest.mark.asyncio
async def test_natural_variations_context_reconstruction(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 2: Varied natural phrasing for Context Reconstruction."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)

    # 1. "Where was I with my application?"
    conv1 = "test-ctx-var-1"
    r1 = await service.chat("Where was I with my application?", conversation_id=conv1)
    assert "university application" in r1.message.lower()
    assert any(act.tool_name == "get_thread_context" for act in r1.activities)

    # 2. "What happened with that application?"
    conv2 = "test-ctx-var-2"
    r2 = await service.chat(
        "What happened with that application?", conversation_id=conv2
    )
    assert "university application" in r2.message.lower()
    assert any(act.tool_name == "get_thread_context" for act in r2.activities)

    # 3. Contextual pronoun follow-up: "Can you remind me what I had done?"
    conv3 = "test-ctx-var-3"
    await service.chat("What am I forgetting?", conversation_id=conv3)
    r3 = await service.chat("Can you remind me what I had done?", conversation_id=conv3)
    assert "university application" in r3.message.lower()
    assert any(act.tool_name == "get_thread_context" for act in r3.activities)


@pytest.mark.asyncio
async def test_natural_variations_blockers(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Blocker Investigation."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)

    # Setup active thread via discovery
    conv_id = "test-blocker-vars"
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Variation 1: "Why isn't it finished?"
    r1 = await service.chat("Why isn't it finished?", conversation_id=conv_id)
    assert "blocked" in r1.message.lower()
    assert "recommendation" in r1.message.lower()
    assert any(act.tool_name == "find_thread_blockers" for act in r1.activities)

    # Variation 2: "What's holding this up?"
    r2 = await service.chat("What's holding this up?", conversation_id=conv_id)
    assert "blocked" in r2.message.lower()
    assert any(act.tool_name == "find_thread_blockers" for act in r2.activities)

    # Variation 3: "What's blocking me?"
    r3 = await service.chat("What's blocking me?", conversation_id=conv_id)
    assert "blocked" in r3.message.lower()
    assert any(act.tool_name == "find_thread_blockers" for act in r3.activities)


@pytest.mark.asyncio
async def test_natural_variations_next_action(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Next Action."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-next-action-vars"
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Variation 1: "What should I do now?"
    r1 = await service.chat("What should I do now?", conversation_id=conv_id)
    assert (
        "recommended action" in r1.message.lower() or "next step" in r1.message.lower()
    )
    assert any(act.tool_name == "suggest_next_action" for act in r1.activities)

    # Variation 2: "What's my next step?"
    r2 = await service.chat("What's my next step?", conversation_id=conv_id)
    assert (
        "recommended action" in r2.message.lower() or "next step" in r2.message.lower()
    )
    assert any(act.tool_name == "suggest_next_action" for act in r2.activities)


@pytest.mark.asyncio
async def test_natural_variations_prepare_action(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Prepare Action."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)

    # Variation 1: "Can you help me do that?"
    conv1 = "test-prep-var-1"
    await service.chat("What am I forgetting?", conversation_id=conv1)
    r1 = await service.chat("Can you help me do that?", conversation_id=conv1)
    assert r1.pending_confirmation is True
    assert r1.proposal_id is not None
    assert "simulated" in r1.message.lower()
    assert any(act.tool_name == "prepare_action" for act in r1.activities)

    # Variation 2: "Let's take care of it."
    conv2 = "test-prep-var-2"
    await service.chat("What am I forgetting?", conversation_id=conv2)
    r2 = await service.chat("Let's take care of it.", conversation_id=conv2)
    assert r2.pending_confirmation is True
    assert r2.proposal_id is not None
    assert "simulated" in r2.message.lower()
    assert any(act.tool_name == "prepare_action" for act in r2.activities)


@pytest.mark.asyncio
async def test_confirmation_safety_and_varied_phrasing(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 2 & 4: Confirmation executes only when valid proposal exists, strictly simulated."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-confirm-safety"

    # Unsolicited confirmation: must NOT execute anything
    r_unsol = await service.chat("Yes, do it.", conversation_id=conv_id)
    assert r_unsol.pending_confirmation is False
    assert len(r_unsol.activities) == 0
    assert (
        "no action proposal currently awaiting confirmation" in r_unsol.message.lower()
    )

    # Prepare an action
    await service.chat("What am I forgetting?", conversation_id=conv_id)
    await service.chat("Help me finish it.", conversation_id=conv_id)
    session = service.conversation_manager.get(conv_id)
    assert session is not None
    assert session.pending_confirmation is True

    # Ambiguous phrasing: must NOT execute
    r_amb = await service.chat("sounds good to me", conversation_id=conv_id)
    assert r_amb.pending_confirmation is True
    assert not any(act.tool_name == "execute_action" for act in r_amb.activities)

    # Affirmative execution: "Yes, do it."
    r_exec = await service.chat("Yes, do it.", conversation_id=conv_id)
    assert r_exec.pending_confirmation is False
    assert r_exec.execution_mode == "SIMULATED"
    assert r_exec.execution_status in ("EXECUTED", "ALREADY_EXECUTED")
    assert any(act.tool_name == "execute_action" for act in r_exec.activities)


@pytest.mark.asyncio
async def test_natural_variations_verification(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Verification."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-ver-vars"
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Variation 1: "Is it actually finished?"
    r1 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert any(act.tool_name == "verify_thread_completion" for act in r1.activities)
    assert "not verified" in r1.message.lower() or "not yet" in r1.message.lower()

    # Variation 2: "Did I complete it?"
    r2 = await service.chat("Did I complete it?", conversation_id=conv_id)
    assert any(act.tool_name == "verify_thread_completion" for act in r2.activities)


@pytest.mark.asyncio
async def test_natural_variations_closure(live_mcp_endpoint: str) -> None:
    """Requirement 2: Varied natural phrasing for Closure ('Close it', 'I'm done with it')."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-closure-vars"
    await service.chat(
        "Where did I leave off with the client report?", conversation_id=conv_id
    )

    # Variation 1: "I'm done with it." (unverified client report cannot close)
    r1 = await service.chat("I'm done with it.", conversation_id=conv_id)
    assert (
        "cannot close" in r1.message.lower()
        or "not been verified" in r1.message.lower()
    )
    assert any(act.tool_name == "verify_thread_completion" for act in r1.activities)
    assert not any(act.tool_name == "close_thread" for act in r1.activities)


@pytest.mark.asyncio
async def test_contextual_multi_turn_follow_up_sequence(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 3: Follow-up sequence preserving active thread without re-mentioning it."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-followup-sequence"

    # Turn 1: "What am I forgetting?" -> agent identifies University Application
    t1 = await service.chat("What am I forgetting?", conversation_id=conv_id)
    assert "university application" in t1.message.lower()

    # Turn 2: "Why is that still unfinished?" -> uses active University Application
    t2 = await service.chat("Why is that still unfinished?", conversation_id=conv_id)
    assert "university application" in t2.message.lower()
    assert "blocked" in t2.message.lower()
    assert "recommendation" in t2.message.lower()

    # Turn 3: "What should I do?" -> uses active thread
    t3 = await service.chat("What should I do?", conversation_id=conv_id)
    assert (
        "recommended action" in t3.message.lower() or "next step" in t3.message.lower()
    )

    # Turn 4: "Let's take care of it." -> prepares action for active thread
    t4 = await service.chat("Let's take care of it.", conversation_id=conv_id)
    assert t4.pending_confirmation is True
    assert t4.proposal_id is not None

    # Turn 5: "Go ahead." -> executes
    t5 = await service.chat("Go ahead.", conversation_id=conv_id)
    assert t5.execution_mode == "SIMULATED"
    assert t5.execution_status in ("EXECUTED", "ALREADY_EXECUTED")

    # Turn 6: "Thanks" -> zero MCP tools
    t6 = await service.chat("Thanks", conversation_id=conv_id)
    assert len(t6.activities) == 0
    assert "welcome" in t6.message.lower()


@pytest.mark.asyncio
async def test_ambiguity_no_silent_switch_asks_clarification(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 3: When ambiguous, ask for clarification instead of silently switching."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-ambig-no-switch"

    # Fresh session, no context, ambiguous question
    res = await service.chat("Why isn't it finished?", conversation_id=conv_id)
    assert "multiple" in res.message.lower() or "which" in res.message.lower()

    # User disambiguates
    res2 = await service.chat("The university application", conversation_id=conv_id)
    assert "university application" in res2.message.lower()
    assert "blocked" in res2.message.lower() or "recommendation" in res2.message.lower()


@pytest.mark.asyncio
async def test_unknown_threads_handled_transparently(
    live_mcp_endpoint: str,
) -> None:
    """Requirement 1 & 4: Unknown intentions do not fabricate data."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-unknown-handling"

    r1 = await service.chat(
        "Where was I with my trip to Mars?", conversation_id=conv_id
    )
    assert "couldn't find" in r1.message.lower() or "more context" in r1.message.lower()
    assert len(r1.activities) == 0

    r2 = await service.chat(
        "Can you close my passport renewal?", conversation_id=conv_id
    )
    assert "couldn't find" in r2.message.lower() or "more context" in r2.message.lower()
    assert len(r2.activities) == 0


@pytest.mark.asyncio
async def test_manual_verification_items_a_through_i(
    live_mcp_endpoint: str,
) -> None:
    """
    Requirement 10: Explicit verification of Prompts A through I:
      A. 'Hello'
      B. 'What can you help me with?'
      C. 'What is Threadback?'
      D. 'What am I forgetting?'
      E. 'Why is my application still unfinished?'
      F. 'What should I do next?'
      G. 'Yes, go ahead.' with pending confirmation
      H. 'Thanks'
      I. canonical 9-phase demo

    Verifies that A, B, C, and H do not unnecessarily invoke Threadback MCP tools (activities == []).
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)

    # A: "Hello"
    res_a = await service.chat("Hello", conversation_id="verify-A")
    assert len(res_a.activities) == 0
    assert "threadback" in res_a.message.lower()

    # B: "What can you help me with?"
    res_b = await service.chat("What can you help me with?", conversation_id="verify-B")
    assert len(res_b.activities) == 0
    assert "discover" in res_b.message.lower()

    # C: "What is Threadback?"
    res_c = await service.chat("What is Threadback?", conversation_id="verify-C")
    assert len(res_c.activities) == 0
    assert "threadback" in res_c.message.lower()

    # D: "What am I forgetting?"
    conv_e = "verify-E-F-G"
    res_d = await service.chat("What am I forgetting?", conversation_id=conv_e)
    assert len(res_d.activities) > 0
    assert "university application" in res_d.message.lower()

    # E: "Why is my application still unfinished?"
    res_e = await service.chat(
        "Why is my application still unfinished?", conversation_id=conv_e
    )
    assert len(res_e.activities) > 0
    assert "blocked" in res_e.message.lower()
    assert "recommendation" in res_e.message.lower()

    # F: "What should I do next?"
    res_f = await service.chat("What should I do next?", conversation_id=conv_e)
    assert len(res_f.activities) > 0
    assert (
        "recommended action" in res_f.message.lower()
        or "next step" in res_f.message.lower()
    )

    # G: "Yes, go ahead." with pending confirmation
    prep = await service.chat("Help me finish it.", conversation_id=conv_e)
    assert prep.pending_confirmation is True
    res_g = await service.chat("Yes, go ahead.", conversation_id=conv_e)
    assert len(res_g.activities) > 0
    assert res_g.execution_mode == "SIMULATED"
    assert res_g.execution_status in ("EXECUTED", "ALREADY_EXECUTED")

    # H: "Thanks"
    res_h = await service.chat("Thanks", conversation_id="verify-H")
    assert len(res_h.activities) == 0
    assert "welcome" in res_h.message.lower()

    # I: Canonical 9-phase demo flow
    conv_i = "verify-I-canonical-demo"
    p1 = await service.chat("What am I forgetting?", conversation_id=conv_i)
    assert "university application" in p1.message.lower()
    assert any(a.tool_name == "discover_unfinished_threads" for a in p1.activities)

    p2 = await service.chat("Where did I leave off?", conversation_id=conv_i)
    assert "university application" in p2.message.lower()
    assert any(a.tool_name == "get_thread_context" for a in p2.activities)

    p3 = await service.chat("Why haven't I finished it?", conversation_id=conv_i)
    assert "blocked" in p3.message.lower()
    assert any(a.tool_name == "find_thread_blockers" for a in p3.activities)

    p4 = await service.chat("What should I do?", conversation_id=conv_i)
    assert any(a.tool_name == "suggest_next_action" for a in p4.activities)

    p5 = await service.chat("Help me finish it.", conversation_id=conv_i)
    assert p5.pending_confirmation is True
    assert any(a.tool_name == "prepare_action" for a in p5.activities)

    p6 = await service.chat("Yes, go ahead.", conversation_id=conv_i)
    assert p6.execution_mode == "SIMULATED"
    assert any(a.tool_name == "execute_action" for a in p6.activities)

    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-phase7-canonical-verify",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="University Portal",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.99,
        ),
    )

    p8 = await service.chat("Is it actually finished?", conversation_id=conv_i)
    assert "verified" in p8.message.lower()
    assert any(a.tool_name == "verify_thread_completion" for a in p8.activities)

    p9 = await service.chat("Close it.", conversation_id=conv_i)
    assert "complete" in p9.message.lower()
    assert any(a.tool_name == "close_thread" for a in p9.activities)


@pytest.mark.asyncio
async def test_repeated_confirmation_after_action_already_executed(
    live_mcp_endpoint: str,
) -> None:
    """
    Requirement 1 & 4:
    Second/repeated confirmation after an action has already executed gives a helpful
    response, does NOT execute anything, and does not create an action proposal.
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-repeated-confirm"

    # Step 1: Prepare action
    await service.chat("What am I forgetting?", conversation_id=conv_id)
    r_prep = await service.chat("Help me finish it.", conversation_id=conv_id)
    assert r_prep.pending_confirmation is True
    assert r_prep.proposal_id is not None

    # Step 2: First confirmation -> executes simulation exactly once
    r_exec = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert r_exec.pending_confirmation is False
    assert r_exec.execution_mode == "SIMULATED"
    assert any(act.tool_name == "execute_action" for act in r_exec.activities)

    # Step 3: Repeated confirmation -> helpful message, no execution
    r_repeat = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert r_repeat.pending_confirmation is False
    assert len(r_repeat.activities) == 0
    assert not any(act.tool_name == "execute_action" for act in r_repeat.activities)
    assert (
        "there isn't another action waiting for confirmation"
        in r_repeat.message.lower()
    )
    assert "already been executed in simulation mode" in r_repeat.message.lower()
    assert (
        "would you like me to check whether the intention is actually complete"
        in r_repeat.message.lower()
    )

    # Step 4: Another repeated confirmation variant -> also safe
    r_repeat2 = await service.chat("Yes, do it.", conversation_id=conv_id)
    assert r_repeat2.pending_confirmation is False
    assert len(r_repeat2.activities) == 0
    assert "already been executed in simulation mode" in r_repeat2.message.lower()


@pytest.mark.asyncio
async def test_verification_telemetry_wording_unverified_and_verified(
    live_mcp_endpoint: str,
) -> None:
    """
    Requirement 2 & 4:
    Verification telemetry clearly represents an evaluation, displaying NOT VERIFIED when
    unverified and VERIFIED when completion evidence is present.
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-ver-telemetry-wording"

    # Turn 1: Discover to establish active thread
    await service.chat("What am I forgetting?", conversation_id=conv_id)

    # Turn 2: Verify unverified thread -> telemetry MUST say NOT VERIFIED
    r_unver = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "not verified" in r_unver.message.lower()
    ver_acts = [
        a for a in r_unver.activities if a.tool_name == "verify_thread_completion"
    ]
    assert len(ver_acts) == 1
    assert "NOT VERIFIED" in ver_acts[0].summary
    assert "Completion evidence evaluated" in ver_acts[0].summary

    # Turn 3: Add resolving evidence
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-telemetry-test-verified",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="University Portal",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.99,
        ),
    )

    # Turn 4: Verify completed thread -> telemetry MUST say VERIFIED
    r_ver = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "verified" in r_ver.message.lower()
    ver_acts_success = [
        a for a in r_ver.activities if a.tool_name == "verify_thread_completion"
    ]
    assert len(ver_acts_success) == 1
    assert "VERIFIED" in ver_acts_success[0].summary
    assert "NOT VERIFIED" not in ver_acts_success[0].summary


@pytest.mark.asyncio
async def test_canonical_sequence_with_repeated_confirmation_and_unverified_closure(
    live_mcp_endpoint: str,
) -> None:
    """
    Requirement 5: Complete exact sequence verification:
      1. 'What am I forgetting?'
      2. 'Where did I leave off?'
      3. 'Why haven't I finished it?'
      4. 'What should I do?'
      5. 'Help me finish it.'
      6. 'Yes, go ahead.'
      7. 'Yes, go ahead.'
      8. 'Is it actually finished?'
      9. 'Close it.'

    Expected:
      - First confirmation executes simulation once.
      - Second confirmation does NOT execute anything and gives a helpful response.
      - Verification clearly says NOT VERIFIED and telemetry indicates evaluation — NOT VERIFIED.
      - Close is rejected because completion is not verified.
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-exact-manual-seq"

    # 1. "What am I forgetting?"
    s1 = await service.chat("What am I forgetting?", conversation_id=conv_id)
    assert "university application" in s1.message.lower()

    # 2. "Where did I leave off?"
    s2 = await service.chat("Where did I leave off?", conversation_id=conv_id)
    assert "university application" in s2.message.lower()

    # 3. "Why haven't I finished it?"
    s3 = await service.chat("Why haven't I finished it?", conversation_id=conv_id)
    assert "blocked" in s3.message.lower()

    # 4. "What should I do?"
    s4 = await service.chat("What should I do?", conversation_id=conv_id)
    assert (
        "recommended action" in s4.message.lower() or "next step" in s4.message.lower()
    )

    # 5. "Help me finish it."
    s5 = await service.chat("Help me finish it.", conversation_id=conv_id)
    assert s5.pending_confirmation is True

    # 6. "Yes, go ahead." -> executes simulation exactly once
    s6 = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert s6.pending_confirmation is False
    assert s6.execution_mode == "SIMULATED"
    assert any(act.tool_name == "execute_action" for act in s6.activities)

    # 7. "Yes, go ahead." -> does NOT execute, natural helpful response
    s7 = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert s7.pending_confirmation is False
    assert len(s7.activities) == 0
    assert not any(act.tool_name == "execute_action" for act in s7.activities)
    assert "there isn't another action waiting for confirmation" in s7.message.lower()

    # 8. "Is it actually finished?" -> NOT VERIFIED, telemetry reflects failure
    s8 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "not verified" in s8.message.lower() or "not yet" in s8.message.lower()
    s8_ver = [a for a in s8.activities if a.tool_name == "verify_thread_completion"]
    assert len(s8_ver) == 1
    assert "NOT VERIFIED" in s8_ver[0].summary

    # 9. "Close it." -> Rejected because not verified
    s9 = await service.chat("Close it.", conversation_id=conv_id)
    assert (
        "cannot close" in s9.message.lower()
        or "not been verified" in s9.message.lower()
    )
    assert any(act.tool_name == "verify_thread_completion" for act in s9.activities)
    assert not any(act.tool_name == "close_thread" for act in s9.activities)
