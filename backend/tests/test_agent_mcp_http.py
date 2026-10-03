"""
Real Streamable HTTP MCP Integration Tests for Threadback M8 Agent.

Verifies end-to-end agent orchestration using real Streamable HTTP calls
to the running Threadback MCP server at http://127.0.0.1:{port}/mcp.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_mcp_endpoint() -> str:
    """
    Start a live uvicorn server running app.main:app on an ephemeral port.
    Yields the canonical Streamable HTTP endpoint URL:
        http://127.0.0.1:{port}/mcp
    """
    port = _find_free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("Live uvicorn server failed to accept connections within 5 seconds")

    yield f"http://127.0.0.1:{port}/mcp"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_agent_http_mcp_demo_a_discovery(live_mcp_endpoint: str) -> None:
    """
    Demo A: Natural-language discovery flow over real Streamable HTTP MCP.
    "What am I forgetting?" -> calls discover_unfinished_threads + analyze_thread.
    """
    mcp_client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=mcp_client)

    res = await svc.chat("What am I forgetting?")
    assert "University Application" in res.message
    assert "Client Report" in res.message
    assert res.pending_confirmation is False
    assert len(res.activities) >= 2
    tool_names = [a.tool_name for a in res.activities]
    assert "discover_unfinished_threads" in tool_names
    assert "analyze_thread" in tool_names


@pytest.mark.asyncio
async def test_agent_http_mcp_demo_b_context_reconstruction(
    live_mcp_endpoint: str,
) -> None:
    """
    Demo B: Context reconstruction flow over real Streamable HTTP MCP.
    "Where did I leave off with the university application?"
    -> calls discover_unfinished_threads + get_thread_context + analyze_thread.
    """
    mcp_client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=mcp_client)

    res = await svc.chat("Where did I leave off with the university application?")
    assert "University Application" in res.message
    assert "BLOCKED" in res.message
    assert "Ahmed" in res.message
    assert res.pending_confirmation is False
    tool_names = [a.tool_name for a in res.activities]
    assert "discover_unfinished_threads" in tool_names
    assert "get_thread_context" in tool_names
    assert "analyze_thread" in tool_names


@pytest.mark.asyncio
async def test_agent_http_mcp_demo_c_controlled_action_and_confirmation(
    live_mcp_endpoint: str,
) -> None:
    """
    Demo C: Controlled action flow with explicit confirmation gate over real HTTP MCP.
    1. "Help me finish the application" -> prepare_action -> returns proposal requiring confirmation.
    2. Ambiguous message "Maybe, what would happen?" -> stops, asks for explicit confirmation.
    3. Explicit confirmation "Yes, go ahead" -> execute_action in SIMULATED mode.
    """
    mcp_client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=mcp_client)
    conv_id = "test-conv-demo-c"

    # Step 1: Request help to trigger action preparation
    res1 = await svc.chat("Help me finish the application.", conversation_id=conv_id)
    assert res1.pending_confirmation is True
    assert res1.proposal_id is not None
    assert res1.proposal_id.startswith("proposal-")
    assert "SIMULATED" in res1.message
    tool_names1 = [a.tool_name for a in res1.activities]
    assert "prepare_action" in tool_names1

    # Step 2: Ambiguous response must NOT execute
    res2 = await svc.chat("Maybe, what would happen?", conversation_id=conv_id)
    assert res2.pending_confirmation is True
    assert res2.proposal_id == res1.proposal_id
    assert "explicit authorization" in res2.message.lower()

    # Step 3: Explicit confirmation authorizes simulated execution
    res3 = await svc.chat("Yes, go ahead", conversation_id=conv_id)
    assert res3.pending_confirmation is False
    assert res3.execution_status == "EXECUTED"
    assert res3.execution_mode == "SIMULATED"
    assert "No real external messages" in res3.message
    tool_names3 = [a.tool_name for a in res3.activities]
    assert "execute_action" in tool_names3


@pytest.mark.asyncio
async def test_agent_http_mcp_blocker_flow(live_mcp_endpoint: str) -> None:
    """
    Blocker flow over real Streamable HTTP MCP.
    "What is blocking me?" -> calls find_thread_blockers.
    """
    mcp_client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=mcp_client)

    res = await svc.chat("What is blocking me?")
    assert "University Application" in res.message
    assert "Ahmed" in res.message or "recommendation" in res.message.lower()
    tool_names = [a.tool_name for a in res.activities]
    assert "find_thread_blockers" in tool_names


@pytest.mark.asyncio
async def test_agent_http_mcp_next_action_flow(live_mcp_endpoint: str) -> None:
    """
    Next action flow over real Streamable HTTP MCP.
    "What should I do next?" -> calls suggest_next_action.
    """
    mcp_client = ThreadbackMCPClient(live_mcp_endpoint)
    svc = AgentService(provider=MockModelProvider(), mcp_client=mcp_client)

    res = await svc.chat("What should I do next?")
    assert "Recommended Action" in res.message
    tool_names = [a.tool_name for a in res.activities]
    assert "suggest_next_action" in tool_names
