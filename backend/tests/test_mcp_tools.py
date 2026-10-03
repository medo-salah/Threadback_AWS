"""
MCP Tool Integration Tests for Threadback M3.

Verifies the 3 read-only MCP tools through the real MCP SDK Client:
  1. discover_unfinished_threads
  2. get_thread_context
  3. find_thread_blockers

Validates:
  - Exact tool discovery (exactly 3 tools, no future tools)
  - Tool docstrings and generated parameter schemas
  - Structured content responses and field presence
  - Filtering by status and limit
  - Blocker detection logic
  - Deterministic unknown-thread error handling (is_error=True, no stack trace)
  - Read-only guarantee: repeated invocations do not mutate data
"""

from __future__ import annotations

import pytest
from app.mcp.server import mcp_server as _mcp_server
from mcp.client.client import Client

# ---------------------------------------------------------------------------
# 1. Tool discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tools_list_contains_exact_m10_tools() -> None:
    """tools/list must advertise exactly the 9 canonical tools after M10."""
    expected_tools = {
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
    async with Client(_mcp_server) as client:
        result = await client.list_tools()
        registered_names = {t.name for t in result.tools}
        assert registered_names == expected_tools, (
            f"Expected {expected_tools}, got {registered_names}"
        )


@pytest.mark.asyncio
async def test_mcp_tools_descriptions_and_schemas() -> None:
    """Tool descriptions must be informative and declare read-only behavior."""
    async with Client(_mcp_server) as client:
        result = await client.list_tools()
        tools_by_name = {t.name: t for t in result.tools}

        for name in (
            "discover_unfinished_threads",
            "get_thread_context",
            "find_thread_blockers",
        ):
            tool = tools_by_name[name]
            assert tool.description, f"Tool {name} must have a description"
            assert "read-only" in tool.description.lower(), (
                f"Tool {name} description must declare that it is read-only"
            )
            assert tool.input_schema is not None, f"Tool {name} must have input_schema"
            assert tool.input_schema.get("type") == "object"


# ---------------------------------------------------------------------------
# 2. Tool 1: discover_unfinished_threads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_unfinished_threads_all() -> None:
    """discover_unfinished_threads returns all unfinished threads and structured content."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool("discover_unfinished_threads", {})

        assert not res.is_error
        assert res.structured_content is not None
        assert "threads" in res.structured_content

        threads = res.structured_content["threads"]
        assert len(threads) == 4  # 4 unfinished demo threads

        statuses = {t["status"] for t in threads}
        assert "COMPLETED" not in statuses
        assert "ABANDONED" not in statuses

        # Verify summary schema on first item
        first = threads[0]
        for field in (
            "id",
            "title",
            "status",
            "priority",
            "confidence",
            "last_activity_at",
            "open_commitments",
            "open_blockers",
        ):
            assert field in first, f"Missing expected field '{field}' in thread summary"


@pytest.mark.asyncio
async def test_discover_unfinished_threads_status_filter() -> None:
    """discover_unfinished_threads filters correctly by status."""
    async with Client(_mcp_server) as client:
        # Filter by BLOCKED
        res = await client.call_tool(
            "discover_unfinished_threads",
            {"status": "BLOCKED"},
        )
        assert not res.is_error
        threads = res.structured_content["threads"]
        assert len(threads) == 1
        assert threads[0]["id"] == "thread-university-application"
        assert threads[0]["status"] == "BLOCKED"

        # Filter by ACTIVE
        res_active = await client.call_tool(
            "discover_unfinished_threads",
            {"status": "ACTIVE"},
        )
        assert not res_active.is_error
        threads_active = res_active.structured_content["threads"]
        assert len(threads_active) == 2
        assert all(t["status"] == "ACTIVE" for t in threads_active)


@pytest.mark.asyncio
async def test_discover_unfinished_threads_limit() -> None:
    """discover_unfinished_threads respects limit parameter."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "discover_unfinished_threads",
            {"limit": 2},
        )
        assert not res.is_error
        threads = res.structured_content["threads"]
        assert len(threads) == 2


@pytest.mark.asyncio
async def test_discover_unfinished_threads_invalid_status() -> None:
    """discover_unfinished_threads with invalid status returns a tool error."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "discover_unfinished_threads",
            {"status": "INVALID_STATUS_XYZ"},
        )
        assert res.is_error is True
        assert len(res.content) > 0
        assert "Invalid status" in res.content[0].text


# ---------------------------------------------------------------------------
# 3. Tool 2: get_thread_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_thread_context_existing() -> None:
    """get_thread_context returns complete structured context for a valid thread."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "get_thread_context",
            {"thread_id": "thread-university-application"},
        )
        assert not res.is_error
        assert res.structured_content is not None
        data = res.structured_content

        # Metadata
        assert data["id"] == "thread-university-application"
        assert data["title"] == "University Application"
        assert data["status"] == "BLOCKED"
        assert data["priority"] == "HIGH"
        assert data["confidence"] == 0.94
        assert "created_at" in data
        assert "updated_at" in data
        assert "last_activity_at" in data

        # Nested collections
        assert len(data["commitments"]) == 1
        assert data["commitments"][0]["id"] == "com-uni-submit"

        assert len(data["evidence"]) >= 1
        assert len(data["dependencies"]) >= 1
        assert len(data["events"]) >= 1

        # Embedded thread object for dual compatibility
        assert "thread" in data
        assert data["thread"]["id"] == "thread-university-application"


@pytest.mark.asyncio
async def test_get_thread_context_unknown_thread() -> None:
    """get_thread_context with unknown ID returns a clear tool-level error."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "get_thread_context",
            {"thread_id": "thread-nonexistent-999"},
        )
        assert res.is_error is True
        assert len(res.content) > 0
        error_text = res.content[0].text
        assert "thread-nonexistent-999" in error_text
        assert "was not found" in error_text


# ---------------------------------------------------------------------------
# 4. Tool 3: find_thread_blockers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_thread_blockers_with_active_blocker() -> None:
    """find_thread_blockers returns active blockers and BLOCKED status."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "find_thread_blockers",
            {"thread_id": "thread-university-application"},
        )
        assert not res.is_error
        data = res.structured_content
        assert data["thread_id"] == "thread-university-application"
        assert data["blocking_status"] == "BLOCKED"
        assert len(data["blockers"]) == 1

        blocker = data["blockers"][0]
        assert blocker["id"] == "dep-uni-rec-letter"
        assert blocker["blocking"] is True
        assert blocker["status"] == "OPEN"


@pytest.mark.asyncio
async def test_find_thread_blockers_unblocked_thread() -> None:
    """find_thread_blockers returns empty list and UNBLOCKED status when no blockers."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "find_thread_blockers",
            {"thread_id": "thread-dentist-appointment"},
        )
        assert not res.is_error
        data = res.structured_content
        assert data["thread_id"] == "thread-dentist-appointment"
        assert data["blocking_status"] == "UNBLOCKED"
        assert data["blockers"] == []


@pytest.mark.asyncio
async def test_find_thread_blockers_unknown_thread() -> None:
    """find_thread_blockers with unknown ID returns a tool error."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "find_thread_blockers",
            {"thread_id": "thread-nonexistent-999"},
        )
        assert res.is_error is True
        assert len(res.content) > 0
        assert "was not found" in res.content[0].text


# ---------------------------------------------------------------------------
# 5. Read-only and idempotence guarantee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tools_are_read_only_and_idempotent() -> None:
    """Calling MCP tools repeatedly produces identical output and does not mutate state."""
    async with Client(_mcp_server) as client:
        res1 = await client.call_tool("discover_unfinished_threads", {})
        res2 = await client.call_tool(
            "get_thread_context",
            {"thread_id": "thread-aws-hackathon"},
        )
        res3 = await client.call_tool(
            "find_thread_blockers",
            {"thread_id": "thread-aws-hackathon"},
        )
        res4 = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-aws-hackathon"},
        )
        res5 = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-aws-hackathon"},
        )
        res6 = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-aws-hackathon"},
        )

        # Call again
        res1_again = await client.call_tool("discover_unfinished_threads", {})
        res2_again = await client.call_tool(
            "get_thread_context",
            {"thread_id": "thread-aws-hackathon"},
        )
        res3_again = await client.call_tool(
            "find_thread_blockers",
            {"thread_id": "thread-aws-hackathon"},
        )
        res4_again = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-aws-hackathon"},
        )
        res5_again = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-aws-hackathon"},
        )
        res6_again = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-aws-hackathon"},
        )

        assert res1.structured_content == res1_again.structured_content
        assert res2.structured_content == res2_again.structured_content
        assert res3.structured_content == res3_again.structured_content
        assert res4.structured_content == res4_again.structured_content
        assert res5.structured_content == res5_again.structured_content
        assert res6.structured_content == res6_again.structured_content


# ---------------------------------------------------------------------------
# 6. Tool 4: analyze_thread (M4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_thread_existing() -> None:
    """analyze_thread returns structured analysis for a known thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-university-application"},
        )
        assert not result.is_error

        data = result.structured_content
        analysis = data["analysis"]
        assert analysis["thread_id"] == "thread-university-application"
        assert analysis["current_status"] == "BLOCKED"
        assert len(analysis["explanation"]) > 0
        assert "OPEN_COMMITMENT" in analysis["unfinished_reasons"]
        assert "ACTIVE_BLOCKER" in analysis["unfinished_reasons"]
        assert len(analysis["open_commitments"]) == 1
        assert len(analysis["active_blockers"]) == 1
        assert analysis["active_blockers"][0]["dependency_id"] == "dep-uni-rec-letter"
        assert analysis["evidence_summary"]["total"] == 2
        assert 0.0 <= analysis["confidence"] <= 1.0
        assert analysis["confidence_band"] in ("STRONG", "GOOD", "UNCERTAIN", "WEAK")
        assert analysis["attention"]["level"] in ("HIGH", "MEDIUM", "LOW")
        assert 0.0 <= analysis["attention"]["score"] <= 1.0


@pytest.mark.asyncio
async def test_analyze_thread_unknown() -> None:
    """analyze_thread returns tool error for an unknown thread ID."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-does-not-exist"},
        )
        assert result.is_error is True


@pytest.mark.asyncio
async def test_analyze_thread_active_no_blockers() -> None:
    """analyze_thread correctly analyzes active thread without blockers."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-aws-hackathon"},
        )
        assert not result.is_error

        data = result.structured_content
        analysis = data["analysis"]
        assert analysis["current_status"] == "ACTIVE"
        assert len(analysis["active_blockers"]) == 0
        assert "ACTIVE_BLOCKER" not in analysis["unfinished_reasons"]
        assert analysis["evidence_summary"]["total"] == 2


@pytest.mark.asyncio
async def test_analyze_thread_waiting_thread() -> None:
    """analyze_thread identifies WAITING state and dependency."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "analyze_thread",
            {"thread_id": "thread-client-report"},
        )
        assert not result.is_error

        data = result.structured_content
        analysis = data["analysis"]
        assert analysis["current_status"] == "WAITING"
        assert "WAITING_ON_DEPENDENCY" in analysis["unfinished_reasons"]


# ---------------------------------------------------------------------------
# 7. Tool 5: suggest_next_action (M5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_next_action_blocked_thread() -> None:
    """suggest_next_action recommends UNBLOCKER_ACTION for blocked thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-university-application"},
        )
        assert not result.is_error

        data = result.structured_content
        suggestion = data["suggestion"]
        assert suggestion["thread_id"] == "thread-university-application"
        assert suggestion["action_type"] == "UNBLOCKER_ACTION"
        assert "dep-uni-rec-letter" in suggestion["supporting_dependency_ids"]
        assert 0.0 <= suggestion["confidence"] <= 1.0
        assert suggestion["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_suggest_next_action_waiting_thread() -> None:
    """suggest_next_action recommends FOLLOW_UP_ACTION for waiting thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-client-report"},
        )
        assert not result.is_error

        data = result.structured_content
        suggestion = data["suggestion"]
        assert suggestion["thread_id"] == "thread-client-report"
        assert suggestion["action_type"] == "FOLLOW_UP_ACTION"
        assert "dep-client-response" in suggestion["supporting_dependency_ids"]
        assert 0.0 <= suggestion["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_suggest_next_action_active_thread() -> None:
    """suggest_next_action recommends DIRECT_NEXT_ACTION for active thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-aws-hackathon"},
        )
        assert not result.is_error

        data = result.structured_content
        suggestion = data["suggestion"]
        assert suggestion["thread_id"] == "thread-aws-hackathon"
        assert suggestion["action_type"] == "DIRECT_NEXT_ACTION"
        assert "com-aws-m3" in suggestion["supporting_commitment_ids"]


@pytest.mark.asyncio
async def test_suggest_next_action_completed_thread() -> None:
    """suggest_next_action returns NO_ACTION for completed thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-tax-filing-2025"},
        )
        assert not result.is_error

        data = result.structured_content
        suggestion = data["suggestion"]
        assert suggestion["thread_id"] == "thread-tax-filing-2025"
        assert suggestion["action_type"] == "NO_ACTION"
        assert suggestion["confidence"] == 1.0


@pytest.mark.asyncio
async def test_suggest_next_action_unknown() -> None:
    """suggest_next_action returns tool error for unknown thread ID."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "suggest_next_action",
            {"thread_id": "thread-nonexistent-xyz"},
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 8. Tool 6: prepare_action (M6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_action_university_application_unblocker() -> None:
    """prepare_action returns CONFIRMATION_REQUIRED proposal for University Application."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-university-application"},
        )
        assert not result.is_error

        data = result.structured_content
        proposal = data["proposal"]
        assert proposal["id"].startswith("proposal-")
        assert proposal["thread_id"] == "thread-university-application"
        assert proposal["action_type"] == "UNBLOCKER_ACTION"
        assert proposal["status"] == "CONFIRMATION_REQUIRED"
        assert proposal["risk_level"] == "MEDIUM"
        assert proposal["requires_confirmation"] is True
        assert proposal["inputs"]["recipient"] == "Ahmed"
        assert "dep-uni-rec-letter" in proposal["supporting_dependency_ids"]


@pytest.mark.asyncio
async def test_prepare_action_client_report_waiting() -> None:
    """prepare_action returns CONFIRMATION_REQUIRED proposal for Client Report."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-client-report"},
        )
        assert not result.is_error

        data = result.structured_content
        proposal = data["proposal"]
        assert proposal["id"].startswith("proposal-")
        assert proposal["thread_id"] == "thread-client-report"
        assert proposal["action_type"] == "FOLLOW_UP_ACTION"
        assert proposal["status"] == "CONFIRMATION_REQUIRED"
        assert proposal["risk_level"] == "MEDIUM"
        assert proposal["requires_confirmation"] is True
        assert proposal["inputs"]["recipient"] == "Acme Corp"


@pytest.mark.asyncio
async def test_prepare_action_aws_hackathon_direct() -> None:
    """prepare_action returns READY, LOW-risk proposal for AWS Hackathon."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-aws-hackathon"},
        )
        assert not result.is_error

        data = result.structured_content
        proposal = data["proposal"]
        assert proposal["id"].startswith("proposal-")
        assert proposal["thread_id"] == "thread-aws-hackathon"
        assert proposal["action_type"] == "DIRECT_NEXT_ACTION"
        assert proposal["status"] == "READY"
        assert proposal["risk_level"] == "LOW"
        assert proposal["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_prepare_action_tax_filing_no_action() -> None:
    """prepare_action returns READY, LOW-risk proposal for completed thread."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-tax-filing-2025"},
        )
        assert not result.is_error

        data = result.structured_content
        proposal = data["proposal"]
        assert proposal["id"].startswith("proposal-")
        assert proposal["thread_id"] == "thread-tax-filing-2025"
        assert proposal["action_type"] == "NO_ACTION"
        assert proposal["status"] == "READY"
        assert proposal["risk_level"] == "LOW"


@pytest.mark.asyncio
async def test_prepare_action_unknown() -> None:
    """prepare_action returns tool error for unknown thread ID."""
    async with Client(_mcp_server) as client:
        result = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-nonexistent-xyz"},
        )
        assert result.is_error is True


# ---------------------------------------------------------------------------
# 8. Tool 7: execute_action (M7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_action_mcp_ready_proposal() -> None:
    """execute_action executes a READY proposal without confirmation."""
    async with Client(_mcp_server) as client:
        # Prepare action first
        prep_res = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-aws-hackathon"},
        )
        assert not prep_res.is_error
        proposal = prep_res.structured_content["proposal"]

        # Execute
        exec_res = await client.call_tool(
            "execute_action",
            {
                "proposal_id": proposal["id"],
                "confirmed": False,
            },
        )
        assert not exec_res.is_error
        data = exec_res.structured_content
        assert data["execution_status"] == "EXECUTED"
        assert data["execution_mode"] == "SIMULATED"
        assert (
            "direct next action was simulated successfully" in data["message"].lower()
        )
        assert data["event_id"] is not None


@pytest.mark.asyncio
async def test_execute_action_mcp_confirmation_required() -> None:
    """execute_action requires confirmed=True for confirmation-required proposals."""
    async with Client(_mcp_server) as client:
        # Prepare action for University Application
        prep_res = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-university-application"},
        )
        assert not prep_res.is_error
        proposal = prep_res.structured_content["proposal"]
        assert proposal["requires_confirmation"] is True

        # Attempt without confirmation -> REJECTED
        exec_unconfirmed = await client.call_tool(
            "execute_action",
            {
                "proposal_id": proposal["id"],
                "confirmed": False,
            },
        )
        assert not exec_unconfirmed.is_error
        data_unconfirmed = exec_unconfirmed.structured_content
        assert data_unconfirmed["execution_status"] == "REJECTED"
        assert "explicit user confirmation" in data_unconfirmed["message"]

        # Now execute with confirmation -> EXECUTED
        exec_confirmed = await client.call_tool(
            "execute_action",
            {
                "proposal_id": proposal["id"],
                "confirmed": True,
            },
        )
        assert not exec_confirmed.is_error
        data_confirmed = exec_confirmed.structured_content
        assert data_confirmed["execution_status"] == "EXECUTED"
        assert data_confirmed["execution_mode"] == "SIMULATED"
        assert (
            "unblocker action was simulated successfully"
            in data_confirmed["message"].lower()
        )


@pytest.mark.asyncio
async def test_execute_action_mcp_idempotency() -> None:
    """execute_action returns ALREADY_EXECUTED upon re-execution."""
    async with Client(_mcp_server) as client:
        prep_res = await client.call_tool(
            "prepare_action",
            {"thread_id": "thread-client-report"},
        )
        assert not prep_res.is_error
        proposal = prep_res.structured_content["proposal"]

        # First execution
        res1 = await client.call_tool(
            "execute_action",
            {"proposal_id": proposal["id"], "confirmed": True},
        )
        assert not res1.is_error
        assert res1.structured_content["execution_status"] == "EXECUTED"

        # Second execution
        res2 = await client.call_tool(
            "execute_action",
            {"proposal_id": proposal["id"], "confirmed": True},
        )
        assert not res2.is_error
        assert res2.structured_content["execution_status"] == "ALREADY_EXECUTED"
        assert "already executed" in res2.structured_content["message"].lower()


@pytest.mark.asyncio
async def test_execute_action_mcp_unknown_proposal() -> None:
    """execute_action returns REJECTED cleanly when proposal is not in registry."""
    async with Client(_mcp_server) as client:
        res = await client.call_tool(
            "execute_action",
            {"proposal_id": "proposal-nonexistent-xyz", "confirmed": True},
        )
        assert not res.is_error
        assert res.structured_content["execution_status"] == "REJECTED"
        assert (
            "was not found in the proposal registry"
            in res.structured_content["message"]
        )
