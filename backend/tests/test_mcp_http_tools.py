"""
Real Streamable HTTP MCP Integration Tests for Threadback M3.

Verifies all three M3 read-only tools against a live running server over the
canonical Streamable HTTP endpoint:
    http://localhost:{port}/mcp

Protocol: Streamable HTTP (2025-11-25 / 2026-07-28)
Client: Official MCP Python SDK streamable_http_client + ClientSession

Flow for all tests:
    connect to http://localhost:{port}/mcp
            ↓
       initialize
            ↓
       tools/list
            ↓
       tools/call
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

# ---------------------------------------------------------------------------
# Live server fixture
# ---------------------------------------------------------------------------


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

    # Wait up to 5 seconds for the server to accept connections
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


# ---------------------------------------------------------------------------
# 0. Protocol handshake & tool discovery over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_handshake_and_tool_discovery(live_mcp_endpoint: str) -> None:
    """
    Connect to /mcp over Streamable HTTP, perform initialize handshake,
    verify protocol version 2025-11-25, and assert exactly 3 tools are advertised.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            assert init_result is not None
            assert init_result.protocol_version in ("2025-11-25", "2026-07-28")

            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}
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
            assert tool_names == expected, f"Expected {expected}, got {tool_names}"


# ---------------------------------------------------------------------------
# 1. Tool 1: discover_unfinished_threads over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_discover_unfinished_threads(live_mcp_endpoint: str) -> None:
    """
    Call discover_unfinished_threads through the real HTTP MCP endpoint.

    Verify:
      - call succeeds (is_error is False);
      - structured result is returned with 'threads';
      - unfinished demo threads are present;
      - thread-tax-filing-2025 (COMPLETED) is absent;
      - thread-old-gym-membership (ABANDONED) is absent.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("discover_unfinished_threads", {})

            assert result.is_error is False, f"Tool call failed: {result.content}"
            assert result.structured_content is not None, "Expected structured_content"
            assert "threads" in result.structured_content

            threads = result.structured_content["threads"]
            thread_ids = [t["id"] for t in threads]

            # Unfinished threads must be present
            assert "thread-university-application" in thread_ids
            assert "thread-client-report" in thread_ids
            assert "thread-dentist-appointment" in thread_ids
            assert "thread-aws-hackathon" in thread_ids

            # Finished and abandoned threads must be strictly excluded
            assert "thread-tax-filing-2025" not in thread_ids, (
                "Completed thread must not be returned"
            )
            assert "thread-old-gym-membership" not in thread_ids, (
                "Abandoned thread must not be returned"
            )


# ---------------------------------------------------------------------------
# 2. Tool 2: get_thread_context over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_get_thread_context_existing(live_mcp_endpoint: str) -> None:
    """
    Call get_thread_context for 'thread-university-application' through real HTTP endpoint.

    Verify:
      - call succeeds;
      - structured result contains the thread;
      - commitments are present;
      - evidence is present;
      - dependencies are present;
      - events are present.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "get_thread_context",
                {"thread_id": "thread-university-application"},
            )

            assert result.is_error is False
            assert result.structured_content is not None
            data = result.structured_content

            # Structured fields verification
            assert data["id"] == "thread-university-application"
            assert data["title"] == "University Application"
            assert data["status"] == "BLOCKED"
            assert data["priority"] == "HIGH"

            # Collections present and populated
            assert "commitments" in data and len(data["commitments"]) >= 1
            assert "evidence" in data and len(data["evidence"]) >= 1
            assert "dependencies" in data and len(data["dependencies"]) >= 1
            assert "events" in data and len(data["events"]) >= 1

            # Verify specific commitment and evidence data
            assert data["commitments"][0]["id"] == "com-uni-submit"
            assert any("Ahmed" in e["description"] for e in data["evidence"])


@pytest.mark.asyncio
async def test_http_mcp_get_thread_context_unknown(live_mcp_endpoint: str) -> None:
    """
    Call get_thread_context for an unknown thread ID through real HTTP endpoint.

    Verify:
      - MCP tool call returns an error (is_error is True);
      - no HTTP/server crash occurs;
      - clear deterministic error message is returned;
      - no Python stack trace is exposed to the client.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "get_thread_context",
                {"thread_id": "thread-unknown-id-xyz"},
            )

            assert result.is_error is True
            assert len(result.content) > 0
            error_message = result.content[0].text

            # Clean error message
            assert "thread-unknown-id-xyz" in error_message
            assert "was not found" in error_message

            # No Python stack trace leaked
            assert "Traceback" not in error_message
            assert 'File "' not in error_message


# ---------------------------------------------------------------------------
# 3. Tool 3: find_thread_blockers over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_find_thread_blockers_blocked(live_mcp_endpoint: str) -> None:
    """
    Call find_thread_blockers for 'thread-university-application' through real HTTP endpoint.

    Verify:
      - blocking_status = 'BLOCKED';
      - recommendation-letter dependency is returned.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "find_thread_blockers",
                {"thread_id": "thread-university-application"},
            )

            assert result.is_error is False
            assert result.structured_content is not None
            data = result.structured_content

            assert data["thread_id"] == "thread-university-application"
            assert data["blocking_status"] == "BLOCKED"
            assert len(data["blockers"]) == 1

            blocker = data["blockers"][0]
            assert blocker["id"] == "dep-uni-rec-letter"
            assert blocker["blocking"] is True
            assert blocker["status"] == "OPEN"
            assert (
                "Ahmed" in blocker["description"]
                or "recommendation" in blocker["description"].lower()
            )


@pytest.mark.asyncio
async def test_http_mcp_find_thread_blockers_unblocked(live_mcp_endpoint: str) -> None:
    """
    Call find_thread_blockers for 'thread-dentist-appointment' through real HTTP endpoint.

    Verify:
      - blocking_status = 'UNBLOCKED';
      - blockers = [].
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "find_thread_blockers",
                {"thread_id": "thread-dentist-appointment"},
            )

            assert result.is_error is False
            assert result.structured_content is not None
            data = result.structured_content

            assert data["thread_id"] == "thread-dentist-appointment"
            assert data["blocking_status"] == "UNBLOCKED"
            assert data["blockers"] == []


# ---------------------------------------------------------------------------
# 4. Tool 4: analyze_thread over HTTP (M4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_analyze_thread_blocked(live_mcp_endpoint: str) -> None:
    """
    Call analyze_thread for the university application thread over HTTP.

    Verify:
      - thread_id matches;
      - current_status = 'BLOCKED';
      - unfinished_reasons includes OPEN_COMMITMENT and ACTIVE_BLOCKER;
      - active_blockers is non-empty;
      - evidence_summary has total >= 1;
      - confidence is within [0, 1];
      - attention level is HIGH (HIGH priority + ACTIVE blocker).
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "analyze_thread",
                {"thread_id": "thread-university-application"},
            )

            assert result.is_error is False
            assert result.structured_content is not None
            data = result.structured_content

            analysis = data["analysis"]
            assert analysis["thread_id"] == "thread-university-application"
            assert analysis["current_status"] == "BLOCKED"
            assert "OPEN_COMMITMENT" in analysis["unfinished_reasons"]
            assert "ACTIVE_BLOCKER" in analysis["unfinished_reasons"]
            assert len(analysis["active_blockers"]) == 1
            assert (
                analysis["active_blockers"][0]["dependency_id"] == "dep-uni-rec-letter"
            )
            assert analysis["evidence_summary"]["total"] == 2
            assert 0.0 <= analysis["confidence"] <= 1.0
            assert analysis["confidence_band"] in (
                "STRONG",
                "GOOD",
                "UNCERTAIN",
                "WEAK",
            )
            assert analysis["attention"]["level"] == "HIGH"
            assert 0.0 <= analysis["attention"]["score"] <= 1.0


@pytest.mark.asyncio
async def test_http_mcp_analyze_thread_active(live_mcp_endpoint: str) -> None:
    """
    Call analyze_thread for the AWS hackathon thread over HTTP.

    Verify:
      - current_status = 'ACTIVE';
      - no active blockers;
      - evidence_summary total = 2.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "analyze_thread",
                {"thread_id": "thread-aws-hackathon"},
            )

            assert result.is_error is False
            data = result.structured_content
            analysis = data["analysis"]
            assert analysis["current_status"] == "ACTIVE"
            assert len(analysis["active_blockers"]) == 0
            assert analysis["evidence_summary"]["total"] == 2


@pytest.mark.asyncio
async def test_http_mcp_analyze_thread_unknown(live_mcp_endpoint: str) -> None:
    """
    Call analyze_thread for a non-existent thread ID over HTTP.

    Verify: tool error is returned.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "analyze_thread",
                {"thread_id": "thread-nonexistent-xyz"},
            )

            assert result.is_error is True


# ---------------------------------------------------------------------------
# 5. Tool 5: suggest_next_action over HTTP (M5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_suggest_next_action_blocked(live_mcp_endpoint: str) -> None:
    """Call suggest_next_action for University Application over HTTP.

    Verify:
      - call succeeds;
      - action_type = 'UNBLOCKER_ACTION';
      - dep-uni-rec-letter is in supporting_dependency_ids;
      - requires_confirmation is True.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "suggest_next_action",
                {"thread_id": "thread-university-application"},
            )

            assert result.is_error is False
            data = result.structured_content
            suggestion = data["suggestion"]
            assert suggestion["thread_id"] == "thread-university-application"
            assert suggestion["action_type"] == "UNBLOCKER_ACTION"
            assert "dep-uni-rec-letter" in suggestion["supporting_dependency_ids"]
            assert 0.0 <= suggestion["confidence"] <= 1.0
            assert suggestion["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_http_mcp_suggest_next_action_waiting(live_mcp_endpoint: str) -> None:
    """Call suggest_next_action for Client Report over HTTP.

    Verify:
      - call succeeds;
      - action_type = 'FOLLOW_UP_ACTION';
      - dep-client-response is in supporting_dependency_ids.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "suggest_next_action",
                {"thread_id": "thread-client-report"},
            )

            assert result.is_error is False
            data = result.structured_content
            suggestion = data["suggestion"]
            assert suggestion["thread_id"] == "thread-client-report"
            assert suggestion["action_type"] == "FOLLOW_UP_ACTION"
            assert "dep-client-response" in suggestion["supporting_dependency_ids"]


@pytest.mark.asyncio
async def test_http_mcp_suggest_next_action_active(live_mcp_endpoint: str) -> None:
    """Call suggest_next_action for AWS Hackathon over HTTP.

    Verify:
      - call succeeds;
      - action_type = 'DIRECT_NEXT_ACTION';
      - com-aws-m3 is in supporting_commitment_ids.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "suggest_next_action",
                {"thread_id": "thread-aws-hackathon"},
            )

            assert result.is_error is False
            data = result.structured_content
            suggestion = data["suggestion"]
            assert suggestion["thread_id"] == "thread-aws-hackathon"
            assert suggestion["action_type"] == "DIRECT_NEXT_ACTION"
            assert "com-aws-m3" in suggestion["supporting_commitment_ids"]


@pytest.mark.asyncio
async def test_http_mcp_suggest_next_action_unknown(live_mcp_endpoint: str) -> None:
    """Call suggest_next_action for unknown thread over HTTP.

    Verify: clean tool error, no crash.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "suggest_next_action",
                {"thread_id": "thread-nonexistent-abc"},
            )

            assert result.is_error is True


# ---------------------------------------------------------------------------
# 5. Tool 6: prepare_action over HTTP (M6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_prepare_action_university_application(
    live_mcp_endpoint: str,
) -> None:
    """Call prepare_action for University Application over HTTP.

    Verify:
      - proposal returned with status CONFIRMATION_REQUIRED;
      - risk level is MEDIUM;
      - recipient is Ahmed;
      - supporting dependency is dep-uni-rec-letter.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-university-application"},
            )

            assert result.is_error is False
            data = result.structured_content
            proposal = data["proposal"]
            assert "id" in proposal
            assert proposal["id"].startswith("proposal-")
            assert len(proposal["id"]) == len("proposal-") + 16
            assert proposal["thread_id"] == "thread-university-application"
            assert proposal["action_type"] == "UNBLOCKER_ACTION"
            assert proposal["status"] == "CONFIRMATION_REQUIRED"
            assert proposal["risk_level"] == "MEDIUM"
            assert proposal["requires_confirmation"] is True
            assert proposal["inputs"]["recipient"] == "Ahmed"
            assert "dep-uni-rec-letter" in proposal["supporting_dependency_ids"]

            # Second call over HTTP to verify determinism of proposal.id
            result2 = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-university-application"},
            )
            assert result2.is_error is False
            proposal2 = result2.structured_content["proposal"]
            assert proposal2["id"] == proposal["id"]


@pytest.mark.asyncio
async def test_http_mcp_prepare_action_client_report(live_mcp_endpoint: str) -> None:
    """Call prepare_action for Client Report over HTTP.

    Verify:
      - proposal returned with status CONFIRMATION_REQUIRED;
      - proposal has deterministic id;
      - risk level is MEDIUM;
      - recipient is Acme Corp.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-client-report"},
            )

            assert result.is_error is False
            data = result.structured_content
            proposal = data["proposal"]
            assert "id" in proposal
            assert proposal["id"].startswith("proposal-")
            assert proposal["thread_id"] == "thread-client-report"
            assert proposal["action_type"] == "FOLLOW_UP_ACTION"
            assert proposal["status"] == "CONFIRMATION_REQUIRED"
            assert proposal["risk_level"] == "MEDIUM"
            assert proposal["requires_confirmation"] is True
            assert proposal["inputs"]["recipient"] == "Acme Corp"


@pytest.mark.asyncio
async def test_http_mcp_prepare_action_aws_hackathon(live_mcp_endpoint: str) -> None:
    """Call prepare_action for AWS Hackathon over HTTP.

    Verify:
      - proposal returned with status READY;
      - proposal has deterministic id distinct from other threads;
      - risk level is LOW;
      - requires_confirmation is False.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-aws-hackathon"},
            )

            assert result.is_error is False
            data = result.structured_content
            proposal = data["proposal"]
            assert "id" in proposal
            assert proposal["id"].startswith("proposal-")
            assert proposal["thread_id"] == "thread-aws-hackathon"
            assert proposal["action_type"] == "DIRECT_NEXT_ACTION"
            assert proposal["status"] == "READY"
            assert proposal["risk_level"] == "LOW"
            assert proposal["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_http_mcp_prepare_action_unknown(live_mcp_endpoint: str) -> None:
    """Call prepare_action for unknown thread over HTTP.

    Verify: clean tool error, no crash.
    """
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-nonexistent-m6"},
            )

            assert result.is_error is True


# ---------------------------------------------------------------------------
# 6. Tool 7: execute_action over HTTP (M7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_mcp_execute_action_ready_flow(live_mcp_endpoint: str) -> None:
    """Prepare and execute a READY proposal over Streamable HTTP."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. Prepare action
            prep_res = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-aws-hackathon"},
            )
            assert prep_res.is_error is False
            proposal = prep_res.structured_content["proposal"]

            # 2. Execute action without confirmation (READY proposal)
            exec_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal["id"],
                    "confirmed": False,
                    "execution_mode": "SIMULATED",
                },
            )
            assert exec_res.is_error is False
            data = exec_res.structured_content
            assert data["execution_status"] == "EXECUTED"
            assert data["execution_mode"] == "SIMULATED"
            assert data["proposal_id"] == proposal["id"]
            assert data["thread_id"] == "thread-aws-hackathon"
            assert (
                "direct next action was simulated successfully"
                in data["message"].lower()
            )
            assert data["event_id"] is not None


@pytest.mark.asyncio
async def test_http_mcp_execute_action_confirmation_required_flow(
    live_mcp_endpoint: str,
) -> None:
    """Prepare and execute a confirmation-required proposal over Streamable HTTP."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. Prepare action for University Application
            prep_res = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-university-application"},
            )
            assert prep_res.is_error is False
            proposal = prep_res.structured_content["proposal"]
            assert proposal["requires_confirmation"] is True

            # 2. Attempt execute without confirmation -> REJECTED
            rej_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal["id"],
                    "confirmed": False,
                },
            )
            assert rej_res.is_error is False
            rej_data = rej_res.structured_content
            assert rej_data["execution_status"] == "REJECTED"
            assert "explicit user confirmation" in rej_data["message"]

            # 3. Execute with explicit confirmation -> EXECUTED
            ok_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal["id"],
                    "confirmed": True,
                },
            )
            assert ok_res.is_error is False
            ok_data = ok_res.structured_content
            assert ok_data["execution_status"] == "EXECUTED"
            assert ok_data["execution_mode"] == "SIMULATED"
            assert (
                "unblocker action was simulated successfully"
                in ok_data["message"].lower()
            )


@pytest.mark.asyncio
async def test_http_mcp_execute_action_idempotency_flow(live_mcp_endpoint: str) -> None:
    """Re-executing the same proposal over Streamable HTTP returns ALREADY_EXECUTED."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            prep_res = await session.call_tool(
                "prepare_action",
                {"thread_id": "thread-client-report"},
            )
            assert prep_res.is_error is False
            proposal = prep_res.structured_content["proposal"]

            # First execution
            res1 = await session.call_tool(
                "execute_action",
                {"proposal_id": proposal["id"], "confirmed": True},
            )
            assert res1.is_error is False
            assert res1.structured_content["execution_status"] == "EXECUTED"

            # Second execution
            res2 = await session.call_tool(
                "execute_action",
                {"proposal_id": proposal["id"], "confirmed": True},
            )
            assert res2.is_error is False
            assert res2.structured_content["execution_status"] == "ALREADY_EXECUTED"
            assert "already executed" in res2.structured_content["message"].lower()


@pytest.mark.asyncio
async def test_http_mcp_execute_action_unknown_proposal(live_mcp_endpoint: str) -> None:
    """Execute unknown proposal over Streamable HTTP returns structured REJECTED."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            res = await session.call_tool(
                "execute_action",
                {"proposal_id": "proposal-nonexistent-http-xyz", "confirmed": True},
            )
            assert res.is_error is False
            assert res.structured_content["execution_status"] == "REJECTED"
            assert (
                "was not found in the proposal registry"
                in res.structured_content["message"]
            )
