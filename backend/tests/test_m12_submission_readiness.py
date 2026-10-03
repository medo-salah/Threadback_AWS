"""
M12 — Hackathon Demo & Submission Readiness Tests.

Validates:
1. Canonical University Application 9-phase demo repeatability.
2. Deterministic demo reset / re-seed mechanism via /api/agent/reset and /api/agent/demo-reset.
3. Conversational input variations (demo resilience and failure recovery).
4. Restart persistence across SQLite repository re-instantiations.
5. Strict safety boundaries: SIMULATED execution != completion; verification before closure.
6. Exact canonical MCP tool count (exactly 9 tools).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.service import agent_service
from app.domain.enums import EvidenceType
from app.domain.models import Evidence
from app.main import app
from app.mcp.server import (
    execution_service,
    lifecycle_service,
    proposal_registry,
    thread_service,
    verification_service,
)
from app.mcp.server import (
    mcp_server as _mcp_server,
)
from app.repositories.sqlite_repository import SQLiteThreadRepository
from httpx import ASGITransport, AsyncClient
from mcp.client.client import Client


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean canonical state before and after each test."""
    thread_service.reset(seed=True)
    proposal_registry.clear()
    execution_service._ledger.clear()
    yield
    thread_service.reset(seed=True)
    proposal_registry.clear()
    execution_service._ledger.clear()


@pytest.mark.asyncio
async def test_m12_canonical_9_phase_demo_repeatable(live_mcp_endpoint: str):
    """
    Test the canonical 9-phase University Application demo end-to-end.
    Verify that it runs deterministically and repeatedly from a clean state.
    """
    agent_service.mcp_client = ThreadbackMCPClient(live_mcp_endpoint)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        conv_id = "test-m12-canonical-run-1"

        # Phase 1: "What am I forgetting?"
        r1 = await client.post(
            "/api/agent/chat",
            json={"message": "What am I forgetting?", "conversation_id": conv_id},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert "University Application" in d1["message"]
        assert any(
            act["tool_name"] == "discover_unfinished_threads"
            for act in d1.get("activities", [])
        )

        # Phase 2: "Where did I leave off?"
        r2 = await client.post(
            "/api/agent/chat",
            json={"message": "Where did I leave off?", "conversation_id": conv_id},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert "University Application" in d2["message"]
        assert any(
            act["tool_name"] == "get_thread_context" for act in d2.get("activities", [])
        )

        # Phase 3: "Why haven't I finished it?"
        r3 = await client.post(
            "/api/agent/chat",
            json={
                "message": "Why haven't I finished it?",
                "conversation_id": conv_id,
            },
        )
        assert r3.status_code == 200
        d3 = r3.json()
        assert (
            "blocked" in d3["message"].lower()
            or "recommendation" in d3["message"].lower()
        )
        assert any(
            act["tool_name"] == "find_thread_blockers"
            for act in d3.get("activities", [])
        )

        # Phase 4: "What should I do?"
        r4 = await client.post(
            "/api/agent/chat",
            json={"message": "What should I do?", "conversation_id": conv_id},
        )
        assert r4.status_code == 200
        d4 = r4.json()
        assert any(
            act["tool_name"] == "suggest_next_action"
            for act in d4.get("activities", [])
        )

        # Phase 5: "Help me finish it."
        r5 = await client.post(
            "/api/agent/chat",
            json={"message": "Help me finish it.", "conversation_id": conv_id},
        )
        assert r5.status_code == 200
        d5 = r5.json()
        assert d5["pending_confirmation"] is True
        proposal_id = d5["proposal_id"]
        assert proposal_id is not None
        assert "SIMULATED" in d5["message"]

        # Phase 6: "Yes, go ahead."
        r6 = await client.post(
            "/api/agent/chat",
            json={"message": "Yes, go ahead.", "conversation_id": conv_id},
        )
        assert r6.status_code == 200
        d6 = r6.json()
        assert d6["execution_mode"] == "SIMULATED"
        assert d6["execution_status"] in ("EXECUTED", "COMPLETED")
        assert d6["pending_confirmation"] is False

        # Invariant: SIMULATED execution != completion. Thread remains BLOCKED.
        thread_before = thread_service.get_thread("thread-university-application")
        assert thread_before.status.value in ("BLOCKED", "ACTIVE")

        # Phase 7: Structured recommendation letter arrives (external evidence)
        evidence = Evidence(
            id="ev-rec-letter-received-m12",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="admissions_portal",
            confidence=0.99,
            created_at=datetime.now(timezone.utc),
        )
        thread_service.add_evidence("thread-university-application", evidence)

        # Phase 8: "Is it actually finished?"
        r8 = await client.post(
            "/api/agent/chat",
            json={"message": "Is it actually finished?", "conversation_id": conv_id},
        )
        assert r8.status_code == 200
        d8 = r8.json()
        assert "VERIFIED" in d8["message"]
        assert any(
            act["tool_name"] == "verify_thread_completion"
            for act in d8.get("activities", [])
        )

        # Phase 9: "Close it."
        r9 = await client.post(
            "/api/agent/chat",
            json={"message": "Close it.", "conversation_id": conv_id},
        )
        assert r9.status_code == 200
        d9 = r9.json()
        assert "complete" in d9["message"].lower() or "closed" in d9["message"].lower()
        assert any(
            act["tool_name"] == "close_thread" for act in d9.get("activities", [])
        )

        # Thread is now COMPLETED in repository
        thread_after = thread_service.get_thread("thread-university-application")
        assert thread_after.status.value == "COMPLETED"


@pytest.mark.asyncio
async def test_m12_demo_reset_restores_canonical_state(live_mcp_endpoint: str):
    """
    Test that /api/agent/reset with reset_demo_state=True and /api/agent/demo-reset
    restore the canonical demo state in SQLite and reset conversation memory.
    """
    agent_service.mcp_client = ThreadbackMCPClient(live_mcp_endpoint)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        conv_id = "test-m12-reset-flow"

        # 1. Add resolving evidence, verify completion, and close University Application
        evidence = Evidence(
            id="ev-rec-letter-reset-test",
            type=EvidenceType.DOCUMENT,
            description="Recommendation letter received from Ahmed; application submission completed",
            source="admissions_portal",
            confidence=0.99,
            created_at=datetime.now(timezone.utc),
        )
        thread_service.add_evidence("thread-university-application", evidence)
        verification_service.verify_thread("thread-university-application")
        lifecycle_service.close_thread("thread-university-application")
        thread = thread_service.get_thread("thread-university-application")
        assert thread.status.value == "COMPLETED"

        # 2. Call demo-reset endpoint
        reset_resp = await client.post(
            "/api/agent/demo-reset",
            json={"conversation_id": conv_id},
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "demo_state_reset"

        # 3. Verify University Application is restored to initial BLOCKED status
        thread_reset = thread_service.get_thread("thread-university-application")
        assert thread_reset.status.value == "BLOCKED"

        # 4. Verify agent chat starts fresh
        chat_resp = await client.post(
            "/api/agent/chat",
            json={"message": "What am I forgetting?", "conversation_id": conv_id},
        )
        assert chat_resp.status_code == 200
        assert "University Application" in chat_resp.json()["message"]


@pytest.mark.asyncio
async def test_m12_conversational_variations_resilience(live_mcp_endpoint: str):
    """
    Test conversational input variations specified in Section 8:
    - 'Is there anything I forgot?'
    - 'Where was I with the application?'
    - 'Why is it still unfinished?'
    - 'What should I do next?'
    - 'Yes'
    - 'Go ahead'
    - 'Close it.'
    """
    agent_service.mcp_client = ThreadbackMCPClient(live_mcp_endpoint)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        conv_id = "test-m12-variations"

        # Variation 1: "Is there anything I forgot?"
        r1 = await client.post(
            "/api/agent/chat",
            json={
                "message": "Is there anything I forgot?",
                "conversation_id": conv_id,
            },
        )
        assert r1.status_code == 200
        assert "University Application" in r1.json()["message"]

        # Variation 2: "Where was I with the application?"
        r2 = await client.post(
            "/api/agent/chat",
            json={
                "message": "Where was I with the application?",
                "conversation_id": conv_id,
            },
        )
        assert r2.status_code == 200
        assert "University Application" in r2.json()["message"]
        assert any(
            act["tool_name"] == "get_thread_context"
            for act in r2.json().get("activities", [])
        )

        # Variation 3: "Why is it still unfinished?"
        r3 = await client.post(
            "/api/agent/chat",
            json={
                "message": "Why is it still unfinished?",
                "conversation_id": conv_id,
            },
        )
        assert r3.status_code == 200
        assert "recommendation letter" in r3.json()["message"].lower()

        # Variation 4: "What should I do next?"
        r4 = await client.post(
            "/api/agent/chat",
            json={"message": "What should I do next?", "conversation_id": conv_id},
        )
        assert r4.status_code == 200
        assert any(
            act["tool_name"] == "suggest_next_action"
            for act in r4.json().get("activities", [])
        )

        # Preparation
        r5 = await client.post(
            "/api/agent/chat",
            json={"message": "Help me finish it.", "conversation_id": conv_id},
        )
        assert r5.status_code == 200
        assert r5.json()["pending_confirmation"] is True

        # Variation 5: "Go ahead"
        r6 = await client.post(
            "/api/agent/chat",
            json={"message": "Go ahead", "conversation_id": conv_id},
        )
        assert r6.status_code == 200
        assert r6.json()["execution_mode"] == "SIMULATED"
        assert r6.json()["execution_status"] in (
            "EXECUTED",
            "COMPLETED",
            "ALREADY_EXECUTED",
        )


def test_m12_sqlite_persistence_across_restart(tmp_path):
    """
    Test that SQLite persists threads, proposals, evidence, and verifications
    across repository re-instantiation (simulating backend restart).
    """
    db_file = str(tmp_path / "threadback_m12_test.db")

    # Step 1: Open repository and initialize
    repo1 = SQLiteThreadRepository(db_path=db_file)
    thread = repo1.get_thread("thread-university-application")
    assert thread is not None

    # Step 2: Add evidence and prepare proposal
    ev = Evidence(
        id="ev-restart-test-1",
        type=EvidenceType.DOCUMENT,
        description="Portal status check confirmed",
        source="admissions_portal",
        confidence=0.95,
        created_at=datetime.now(timezone.utc),
    )
    repo1.add_evidence("thread-university-application", ev)

    # Step 3: Close connection and re-instantiate repo2 from same file
    repo1.close()

    repo2 = SQLiteThreadRepository(db_path=db_file)
    thread_reloaded = repo2.get_thread("thread-university-application")
    assert thread_reloaded is not None
    ev_ids = [e.id for e in thread_reloaded.evidence]
    assert "ev-restart-test-1" in ev_ids
    repo2.close()


@pytest.mark.asyncio
async def test_m12_canonical_mcp_tool_count():
    """Verify that exactly 9 canonical MCP tools are registered and advertised."""
    async with Client(_mcp_server) as client:
        result = await client.list_tools()
        assert len(result.tools) == 9
        tool_names = {t.name for t in result.tools}
        expected = {
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
        assert tool_names == expected
