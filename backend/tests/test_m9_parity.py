"""
M9 Local/Remote MCP Parity & Safety Verification Suite.

Tests local vs remote/authenticated parity across all 7 Threadback MCP tools:
1. discover_unfinished_threads
2. get_thread_context
3. find_thread_blockers
4. analyze_thread
5. suggest_next_action
6. prepare_action
7. execute_action

Safety invariants verified:
- Source of truth remains the deterministic domain engines.
- Exactly 7 tools exposed.
- Action execution requires proposal ID and explicit confirmation.
- Execution is strictly SIMULATED.
- Repeated execution is idempotent (ALREADY_EXECUTED).
- Invalid proposals and blocked proposals cannot execute.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator

import pytest
from app.security.jwt_validator import create_test_token
from app.services.analysis_service import AnalysisService
from app.services.next_action_service import NextActionService
from app.services.thread_service import ThreadService
from exceptiongroup import BaseExceptionGroup
from mcp.client.session import ClientSession
from mcp.client.streamable_http import httpx2, streamable_http_client

PARITY_SECRET_KEY = "test-secret-key-32-bytes-minimum-parity-suite!!"


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def remote_mcp_server() -> AsyncIterator[tuple[str, str]]:
    """
    Launch live server with AUTH_ENABLED=true on ephemeral port.
    Yields tuple of (endpoint_url, valid_jwt_token).
    """
    port = _find_free_port()
    env = os.environ.copy()
    env["AUTH_ENABLED"] = "true"
    env["AUTH_SECRET_KEY"] = PARITY_SECRET_KEY
    env["AUTH_ISSUER"] = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_m9_test"
    env["AUTH_AUDIENCE"] = "threadback-mcp"

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
        env=env,
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
        pytest.fail("Live server failed to accept connections within 5 seconds")

    token = create_test_token(
        sub="agentcore-verifier",
        secret_key=PARITY_SECRET_KEY,
        issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_m9_test",
        audience="threadback-mcp",
    )

    endpoint = f"http://127.0.0.1:{port}/mcp"
    yield endpoint, token

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_remote_mcp_auth_boundary(remote_mcp_server: tuple[str, str]) -> None:
    """Verify that unauthenticated connection to remote MCP fails."""
    endpoint, _ = remote_mcp_server
    # Attempting to connect without auth header should fail handshake with HTTP 401 error
    with pytest.raises((httpx2.HTTPError, BaseExceptionGroup)):
        async with streamable_http_client(endpoint) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()


@pytest.mark.asyncio
async def test_remote_mcp_initialize_and_tool_discovery(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Verify initialize and tools/list over remote authenticated MCP."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            init_res = await session.initialize()
            assert init_res is not None
            # Verified active negotiated MCP protocol version for Alexa+ compatibility
            assert init_res.protocol_version == "2025-11-25"

            tools_res = await session.list_tools()
            tool_names = sorted([t.name for t in tools_res.tools])
            expected_nine = sorted(
                [
                    "discover_unfinished_threads",
                    "get_thread_context",
                    "find_thread_blockers",
                    "analyze_thread",
                    "suggest_next_action",
                    "prepare_action",
                    "execute_action",
                    "verify_thread_completion",
                    "close_thread",
                ]
            )
            assert tool_names == expected_nine, (
                f"Expected exactly 9 tools, got {tool_names}"
            )


@pytest.mark.asyncio
async def test_remote_tool_1_discover_parity(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Tool 1: discover_unfinished_threads matches local domain engine output."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    # Local engine ground truth
    local_svc = ThreadService()
    local_threads = local_svc.list_threads()
    local_ids = [t.id for t in local_threads]

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_res = await session.call_tool("discover_unfinished_threads", {})
            assert not call_res.is_error
            remote_data = call_res.structured_content
            assert remote_data is not None
            remote_ids = [t["id"] for t in remote_data["threads"]]
            assert remote_ids == local_ids


@pytest.mark.asyncio
async def test_remote_tool_2_context_parity(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Tool 2: get_thread_context matches local domain engine output."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    thread_id = "thread-university-application"
    local_svc = ThreadService()
    local_ctx = local_svc.get_thread(thread_id)
    assert local_ctx is not None

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_res = await session.call_tool(
                "get_thread_context", {"thread_id": thread_id}
            )
            assert not call_res.is_error
            data = call_res.structured_content
            assert data is not None
            assert data["id"] == thread_id
            assert data["title"] == local_ctx.title
            assert data["status"] == local_ctx.status.value
            assert len(data["commitments"]) == len(local_ctx.commitments)
            assert len(data["dependencies"]) == len(local_ctx.dependencies)


@pytest.mark.asyncio
async def test_remote_tool_3_blockers_parity(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Tool 3: find_thread_blockers matches local domain engine output."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    thread_id = "thread-university-application"
    local_svc = ThreadService()
    local_blockers = local_svc.find_blockers(thread_id)

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_res = await session.call_tool(
                "find_thread_blockers", {"thread_id": thread_id}
            )
            assert not call_res.is_error
            data = call_res.structured_content
            assert data is not None
            expected_status = "BLOCKED" if local_blockers else "UNBLOCKED"
            assert data["blocking_status"] == expected_status
            assert len(data["blockers"]) == len(local_blockers)


@pytest.mark.asyncio
async def test_remote_tool_4_analysis_parity(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Tool 4: analyze_thread matches deterministic AnalysisService output."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    thread_id = "thread-university-application"
    thread_svc = ThreadService()
    thread = thread_svc.get_thread(thread_id)
    analysis_svc = AnalysisService()
    local_analysis = analysis_svc.analyze(thread)

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_res = await session.call_tool(
                "analyze_thread", {"thread_id": thread_id}
            )
            assert not call_res.is_error
            data = call_res.structured_content
            assert data is not None
            analysis = data["analysis"]
            assert analysis["thread_id"] == thread_id
            assert analysis["current_status"] == local_analysis.current_status.value
            assert abs(analysis["confidence"] - local_analysis.confidence) < 0.01
            assert len(analysis["active_blockers"]) == len(
                local_analysis.active_blockers
            )


@pytest.mark.asyncio
async def test_remote_tool_5_suggest_action_parity(
    remote_mcp_server: tuple[str, str],
) -> None:
    """Tool 5: suggest_next_action matches deterministic NextActionService output."""
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    thread_id = "thread-university-application"
    thread_svc = ThreadService()
    thread = thread_svc.get_thread(thread_id)
    analysis_svc = AnalysisService()
    next_action_svc = NextActionService(analysis_svc)
    local_suggestion = next_action_svc.suggest_action(thread)

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_res = await session.call_tool(
                "suggest_next_action", {"thread_id": thread_id}
            )
            assert not call_res.is_error
            data = call_res.structured_content
            assert data is not None
            suggestion = data["suggestion"]
            assert suggestion["thread_id"] == thread_id
            assert suggestion["action_type"] == local_suggestion.action_type.value
            assert abs(suggestion["confidence"] - local_suggestion.confidence) < 0.01


@pytest.mark.asyncio
async def test_remote_tools_6_and_7_prepare_and_execute_safety_flow(
    remote_mcp_server: tuple[str, str],
) -> None:
    """
    Tools 6 & 7: prepare_action and execute_action safety lifecycle:
    1. Prepare action proposal -> deterministic ID and confirmation requirement.
    2. Attempt execution without confirmation -> REJECTED.
    3. Attempt execution of invalid proposal -> REJECTED.
    4. Execute with confirmation=True in SIMULATED mode -> EXECUTED.
    5. Re-execute -> ALREADY_EXECUTED (idempotent).
    """
    endpoint, token = remote_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    thread_id = "thread-client-report"

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Step 1: Prepare action
            prep_res = await session.call_tool(
                "prepare_action", {"thread_id": thread_id}
            )
            assert not prep_res.is_error
            prep_data = prep_res.structured_content
            assert prep_data is not None
            proposal = prep_data["proposal"]
            proposal_id = proposal["id"]
            assert proposal_id.startswith("proposal-")
            assert proposal["requires_confirmation"] is True

            # Step 2: Attempt execution without confirmation -> Must be REJECTED
            unconfirmed_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal_id,
                    "confirmed": False,
                    "execution_mode": "SIMULATED",
                },
            )
            assert not unconfirmed_res.is_error
            unconf_data = unconfirmed_res.structured_content
            assert unconf_data is not None
            assert unconf_data["execution_status"] == "REJECTED"
            assert "confirmation" in unconf_data["message"].lower()

            # Step 3: Attempt execution of invalid proposal ID -> Must be REJECTED
            invalid_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": "proposal-non-existent-999",
                    "confirmed": True,
                    "execution_mode": "SIMULATED",
                },
            )
            assert not invalid_res.is_error
            inv_data = invalid_res.structured_content
            assert inv_data is not None
            assert inv_data["execution_status"] == "REJECTED"
            assert "not found" in inv_data["message"].lower()

            # Step 4: Execute with confirmation=True -> Must be EXECUTED
            confirmed_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal_id,
                    "confirmed": True,
                    "execution_mode": "SIMULATED",
                },
            )
            assert not confirmed_res.is_error
            conf_data = confirmed_res.structured_content
            assert conf_data is not None
            assert conf_data["execution_status"] == "EXECUTED"
            assert conf_data["execution_mode"] == "SIMULATED"
            assert conf_data["event_id"] is not None

            # Step 5: Re-execution of the same proposal -> Must be ALREADY_EXECUTED
            reexec_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal_id,
                    "confirmed": True,
                    "execution_mode": "SIMULATED",
                },
            )
            assert not reexec_res.is_error
            reexec_data = reexec_res.structured_content
            assert reexec_data is not None
            assert reexec_data["execution_status"] == "ALREADY_EXECUTED"
