"""
Agent integration tests for M10 lifecycle verification and closure flows.

Validates:
  - Agent uses deterministic verification rather than guessing completion
  - Agent cannot bypass verification before closing a thread
  - Agent handles unverified and verified states truthfully
  - Full end-to-end multi-turn Demo Scenario (Phases 1 to 6)
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
async def test_agent_lifecycle_verification_inquiry(live_mcp_endpoint: str) -> None:
    """Agent handles 'Is it actually finished?' via verify_thread_completion."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-conv-ver-inquiry"

    # Step 1: Initial query on university application (has active blocker)
    res = await service.chat(
        "Is the university application actually finished?", conversation_id=conv_id
    )
    assert "not verified" in res.message.lower() or "not yet" in res.message.lower()
    assert any(act.tool_name == "verify_thread_completion" for act in res.activities)

    # Step 2: Add resolving evidence
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-demo-res",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="Portal",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.98,
        ),
    )

    # Step 3: Ask again -> now verified
    res2 = await service.chat("Is it actually finished now?", conversation_id=conv_id)
    assert "verified" in res2.message.lower()
    assert "complete" in res2.message.lower()


@pytest.mark.asyncio
async def test_agent_closure_safety_cannot_bypass_verification(
    live_mcp_endpoint: str,
) -> None:
    """Agent refuses to close an unverified thread and explains why."""
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-conv-safety"

    # Set up client report with blocker
    thread_service.get_thread("thread-client-report")

    # Ask agent to close unverified thread
    res = await service.chat("Close the client report thread.", conversation_id=conv_id)
    assert (
        "cannot close" in res.message.lower()
        or "not been verified" in res.message.lower()
    )
    # verify_thread_completion was invoked
    assert any(act.tool_name == "verify_thread_completion" for act in res.activities)
    # close_thread was NOT invoked
    assert not any(act.tool_name == "close_thread" for act in res.activities)


@pytest.mark.asyncio
async def test_agent_complete_m10_demo_scenario(live_mcp_endpoint: str) -> None:
    """
    Executes the canonical M10 6-phase University Application demo walkthrough:
      Phase 1: Discover ("What am I forgetting?")
      Phase 2: Reconstruct ("Where did I leave off with the university application?")
      Phase 3: Act ("Help me finish the application." -> "Yes, go ahead.")
      Phase 4: New Evidence (Recommendation letter received)
      Phase 5: Verify ("Is it actually finished?")
      Phase 6: Close ("Close the thread.")
    """
    client = ThreadbackMCPClient(live_mcp_endpoint)
    service = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "demo-m10-university-app"

    # Phase 1: Discover
    p1 = await service.chat("What am I forgetting?", conversation_id=conv_id)
    assert "university application" in p1.message.lower()

    # Phase 2: Reconstruct
    p2 = await service.chat(
        "Where did I leave off with the university application?",
        conversation_id=conv_id,
    )
    assert "university application" in p2.message.lower()
    assert "ahmed" in p2.message.lower() or "recommendation" in p2.message.lower()

    # Phase 3: Act
    p3_prep = await service.chat(
        "Help me finish the application.", conversation_id=conv_id
    )
    assert p3_prep.pending_confirmation is True
    assert p3_prep.proposal_id is not None

    p3_exec = await service.chat("Yes, go ahead.", conversation_id=conv_id)
    assert "simulated" in p3_exec.message.lower()
    assert p3_exec.execution_status == "EXECUTED"

    # Phase 4: Introduce external evidence resolving blocker
    thread_service.add_evidence(
        "thread-university-application",
        Evidence(
            id="evi-uni-phase4-rec",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="Admissions Office",
            created_at=thread_service.get_thread(
                "thread-university-application"
            ).updated_at,
            confidence=0.98,
        ),
    )

    # Phase 5: Verify
    p5 = await service.chat("Is it actually finished?", conversation_id=conv_id)
    assert "verified" in p5.message.lower()

    # Phase 6: Close
    p6 = await service.chat("Close the thread.", conversation_id=conv_id)
    assert "complete" in p6.message.lower()
    assert (
        "recommendation-letter blocker was resolved" in p6.message.lower()
        or "closure loop" in p6.message.lower()
        or "closed" in p6.message.lower()
    )
    assert any(act.tool_name == "close_thread" for act in p6.activities)
