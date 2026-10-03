"""
Automated tests verifying MCP Source-of-Truth enforcement in Threadback Agent (M8).

Proves that:
1. The agent relies strictly on MCP tool returns for all domain facts.
2. The agent does not manufacture, invent, or extrapolate facts (people, dates,
   identifiers, blockers, statuses, evidence) that are absent from MCP output.
3. The factual boundary is strictly enforced without hardcoding specific prose.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService


class ControlledSyntheticMCPClient(ThreadbackMCPClient):
    """
    Controlled MCP client returning uniquely identifiable synthetic domain facts.
    Used to verify that the agent reflects ONLY returned facts and does not hallucinate
    unsupported facts or default thread data.
    """

    def __init__(self) -> None:
        super().__init__("http://localhost:8000/mcp")
        self.synthetic_thread_id = "thread-synthetic-delta-7"
        self.synthetic_title = "Delta Quantum Synthesis"
        self.synthetic_person = "Dr. Vance"
        self.synthetic_due_year = "2029"
        self.synthetic_due_date = "2029-12-31"
        self.synthetic_proposal_id = "proposal-syn-88889999"

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = arguments or {}

        if tool_name == "discover_unfinished_threads":
            query = args.get("query")
            if query and "spaceship" in query.lower():
                # Nonexistent thread search should return empty
                return {"threads": []}
            return {
                "threads": [
                    {
                        "id": self.synthetic_thread_id,
                        "title": self.synthetic_title,
                        "status": "BLOCKED",
                        "priority": "HIGH",
                        "attention_level": "HIGH",
                    }
                ]
            }

        if tool_name == "get_thread_context":
            return {
                "id": self.synthetic_thread_id,
                "title": self.synthetic_title,
                "status": "BLOCKED",
                "priority": "HIGH",
                "commitments": [
                    {
                        "id": "com-synthetic-01",
                        "description": "Finalize laboratory protocol",
                        "status": "OPEN",
                        "due_at": self.synthetic_due_date,
                    }
                ],
                "dependencies": [
                    {
                        "id": "dep-synthetic-clearance",
                        "description": f"Security clearance from {self.synthetic_person}",
                        "status": "OPEN",
                        "blocking": True,
                    }
                ],
                "evidence": [
                    {
                        "id": "ev-synthetic-01",
                        "type": "DOCUMENT",
                        "description": f"Initial protocol signed by {self.synthetic_person}",
                        "source": "Controlled-Archive",
                        "confidence": 0.95,
                    }
                ],
                "events": [],
            }

        if tool_name == "find_thread_blockers":
            return {
                "thread_id": self.synthetic_thread_id,
                "blocking_status": "BLOCKED",
                "blockers": [
                    {
                        "id": "dep-synthetic-clearance",
                        "title": f"Security clearance from {self.synthetic_person}",
                        "description": f"Security clearance from {self.synthetic_person}",
                        "blocking": True,
                        "status": "OPEN",
                    }
                ],
            }

        if tool_name == "analyze_thread":
            return {
                "analysis": {
                    "thread_id": self.synthetic_thread_id,
                    "current_status": "BLOCKED",
                    "attention": {"level": "HIGH", "score": 0.92},
                    "confidence": 0.95,
                    "confidence_band": "STRONG",
                    "unfinished_reasons": ["ACTIVE_BLOCKER", "OPEN_COMMITMENT"],
                    "active_blockers": [{"dependency_id": "dep-synthetic-clearance"}],
                }
            }

        if tool_name == "suggest_next_action":
            return {
                "suggestion": {
                    "thread_id": self.synthetic_thread_id,
                    "action_type": "UNBLOCKER_ACTION",
                    "reason": f"Obtain security clearance from {self.synthetic_person}",
                    "confidence": 0.90,
                    "requires_confirmation": True,
                    "supporting_dependency_ids": ["dep-synthetic-clearance"],
                }
            }

        if tool_name == "prepare_action":
            return {
                "proposal": {
                    "id": self.synthetic_proposal_id,
                    "thread_id": self.synthetic_thread_id,
                    "action_type": "UNBLOCKER_ACTION",
                    "status": "CONFIRMATION_REQUIRED",
                    "risk_level": "MEDIUM",
                    "requires_confirmation": True,
                    "description": f"Send clearance request to {self.synthetic_person}",
                }
            }

        if tool_name == "execute_action":
            return {
                "execution_status": "EXECUTED",
                "execution_mode": args.get("execution_mode", "SIMULATED"),
                "proposal_id": args.get("proposal_id"),
                "thread_id": self.synthetic_thread_id,
                "event_id": "evt-syn-execute-99",
                "message": "Clearance request simulation completed successfully.",
            }

        return {}


@pytest.mark.asyncio
async def test_agent_faithfully_reports_only_mcp_facts() -> None:
    """
    Verify that the agent only asserts facts delivered by the MCP tool,
    and does NOT hallucinate people, dates, or default project threads.
    """
    client = ControlledSyntheticMCPClient()
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)

    # 1. Ask about unfinished intentions
    res = await svc.chat("What am I forgetting?")

    # MUST assert facts provided by MCP
    assert client.synthetic_title in res.message
    assert "HIGH" in res.message

    # MUST NOT manufacture facts absent from MCP return
    forbidden_people = ["Ahmed", "Sarah", "Alice", "Bob", "Charlie", "John"]
    for person in forbidden_people:
        assert person not in res.message, f"Hallucinated unsupported person: '{person}'"

    forbidden_threads = [
        "University Application",
        "Client Report",
        "Dentist Appointment",
        "AWS Hackathon",
    ]
    for thread in forbidden_threads:
        assert thread not in res.message, (
            f"Hallucinated default thread not returned by MCP: '{thread}'"
        )


@pytest.mark.asyncio
async def test_agent_context_reconstruction_does_not_invent_blockers_or_people() -> (
    None
):
    """
    Verify context reconstruction only includes returned blocker and person details.
    """
    client = ControlledSyntheticMCPClient()
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)

    res = await svc.chat("Where did I leave off?")

    # Verifies authorized person from MCP
    assert client.synthetic_person in res.message
    assert client.synthetic_due_year in res.message
    assert "BLOCKED" in res.message

    # Verifies that absent default names are NOT introduced
    assert "Ahmed" not in res.message
    assert "2026-10-15" not in res.message


@pytest.mark.asyncio
async def test_agent_never_claims_real_world_execution() -> None:
    """
    Verify that simulated execution never claims an email was actually sent
    or that a real external action took place.
    """
    client = ControlledSyntheticMCPClient()
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-truth-exec"

    # Step 1: Trigger preparation
    res1 = await svc.chat("Help me finish the project.", conversation_id=conv_id)
    assert res1.pending_confirmation is True
    assert res1.proposal_id == client.synthetic_proposal_id
    assert "SIMULATED" in res1.message

    # Step 2: Confirm
    res2 = await svc.chat("Yes, go ahead.", conversation_id=conv_id)
    assert res2.pending_confirmation is False
    assert res2.execution_status == "EXECUTED"
    assert res2.execution_mode == "SIMULATED"

    # Proves the agent explicitly states execution was simulated without external actions
    msg = res2.message.lower()
    assert "simulat" in msg
    assert "no real" in msg or "no external" in msg or "no actual" in msg
    assert "i sent the email" not in msg
    assert "i have sent an email" not in msg


@pytest.mark.asyncio
async def test_agent_handles_nonexistent_thread_without_defaulting() -> None:
    """
    Verify that when user references an unknown thread, the agent does NOT
    default to an arbitrary thread like University Application.
    """
    client = ControlledSyntheticMCPClient()
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)

    res = await svc.chat("Help me finish the spaceship project.")
    assert "could not find" in res.message.lower()
    assert res.pending_confirmation is False
    assert "University Application" not in res.message


@pytest.mark.asyncio
async def test_agent_demo_c_orchestration_known_thread_fast_path() -> None:
    """
    Verify Demo C orchestration decision flow:
    1. Unknown thread: calls discover_unfinished_threads + get_thread_context + suggest_next_action + prepare_action.
    2. Known thread (session.pending_thread_id already populated): skips discover and context,
       going directly to suggest_next_action + prepare_action.
    """
    client = ControlledSyntheticMCPClient()
    svc = AgentService(provider=MockModelProvider(), mcp_client=client)
    conv_id = "test-conv-fast-path"

    # Step 1: Pre-populate thread knowledge via Demo B
    res_b = await svc.chat("Where did I leave off?", conversation_id=conv_id)
    assert res_b.thread_id == client.synthetic_thread_id
    tool_names_b = [a.tool_name for a in res_b.activities]
    assert "discover_unfinished_threads" in tool_names_b
    assert "get_thread_context" in tool_names_b

    # Step 2: Now ask to help finish it. Since thread is already known, it takes the fast path
    res_c = await svc.chat("Help me finish it.", conversation_id=conv_id)
    assert res_c.pending_confirmation is True
    assert res_c.proposal_id == client.synthetic_proposal_id
    assert res_c.thread_id == client.synthetic_thread_id

    tool_names_c = [a.tool_name for a in res_c.activities]
    # Fast path: does NOT re-run discover or context
    assert "discover_unfinished_threads" not in tool_names_c
    assert "get_thread_context" not in tool_names_c
    assert "suggest_next_action" in tool_names_c
    assert "prepare_action" in tool_names_c
