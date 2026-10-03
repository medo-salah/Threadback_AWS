"""
Integration tests for M10 MCP tools over Streamable HTTP.

Validates:
  - tools/list advertises exactly 9 canonical tools
  - Tool 8: verify_thread_completion execution, responses, and errors
  - Tool 9: close_thread execution, responses, safety invariant, and idempotency
  - Protocol 2025-11-25 compatibility
"""

from __future__ import annotations

import json

import pytest
from app.domain.enums import EvidenceType
from app.domain.models import Evidence
from app.mcp.server import thread_service
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.mark.asyncio
async def test_mcp_m10_tools_list(live_mcp_endpoint: str) -> None:
    """tools/list over Streamable HTTP advertises exactly the 9 canonical tools."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_res = await session.list_tools()
            tool_names = {t.name for t in tools_res.tools}
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
            assert len(tool_names) == 9


@pytest.mark.asyncio
async def test_mcp_m10_verify_thread_completion_failure_and_success(
    live_mcp_endpoint: str,
) -> None:
    """Tool 8: verify_thread_completion over Streamable HTTP."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. Verification fails on unresolved blocker
            fail_res = await session.call_tool(
                "verify_thread_completion",
                {"thread_id": "thread-university-application"},
            )
            assert not fail_res.is_error
            data = fail_res.structured_content or json.loads(fail_res.content[0].text)
            assert data["thread_id"] == "thread-university-application"
            assert data["verified"] is False
            assert "recommendation letter" in data["reason"].lower()

            # 2. Add resolving evidence into thread_service
            thread_service.add_evidence(
                "thread-university-application",
                Evidence(
                    id="evi-uni-test-res",
                    type=EvidenceType.DOCUMENT,
                    description="Recommendation letter received from Ahmed; application submission completed",
                    source="Portal",
                    created_at=thread_service.get_thread(
                        "thread-university-application"
                    ).updated_at,
                    confidence=0.98,
                ),
            )

            # 3. Verification succeeds after evidence is present
            pass_res = await session.call_tool(
                "verify_thread_completion",
                {"thread_id": "thread-university-application"},
            )
            assert not pass_res.is_error
            pass_data = pass_res.structured_content or json.loads(
                pass_res.content[0].text
            )
            assert pass_data["verified"] is True
            assert pass_data["confidence"] >= 0.85
            assert (
                "required completion evidence is present" in pass_data["reason"].lower()
            )


@pytest.mark.asyncio
async def test_mcp_m10_close_thread_safety_and_idempotency(
    live_mcp_endpoint: str,
) -> None:
    """Tool 9: close_thread over Streamable HTTP enforces verification invariant and idempotency."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            thread_id = "thread-client-report"

            # 1. Attempt close without verification -> REJECTED
            close_unverified = await session.call_tool(
                "close_thread",
                {"thread_id": thread_id},
            )
            assert not close_unverified.is_error
            unverified_data = close_unverified.structured_content or json.loads(
                close_unverified.content[0].text
            )
            assert unverified_data["closure_status"] == "REJECTED"

            # 2. Add client sign-off evidence
            thread_service.add_evidence(
                thread_id,
                Evidence(
                    id="evi-client-signoff",
                    type=EvidenceType.DOCUMENT,
                    description="Client response and data sign-off on Q3 deliverables received and approved",
                    source="Client Portal",
                    created_at=thread_service.get_thread(thread_id).updated_at,
                    confidence=0.99,
                ),
            )

            # 3. Run verification -> VERIFIED
            ver_res = await session.call_tool(
                "verify_thread_completion",
                {"thread_id": thread_id},
            )
            assert not ver_res.is_error
            ver_data = ver_res.structured_content or json.loads(ver_res.content[0].text)
            assert ver_data["verified"] is True

            # 4. Close thread -> COMPLETED
            close_verified = await session.call_tool(
                "close_thread",
                {"thread_id": thread_id},
            )
            assert not close_verified.is_error
            close_data = close_verified.structured_content or json.loads(
                close_verified.content[0].text
            )
            assert close_data["closure_status"] == "COMPLETED"
            assert close_data["status"] == "COMPLETED"
            assert close_data["event_id"] is not None

            # 5. Repeat close -> ALREADY_COMPLETED (Idempotency)
            repeat_close = await session.call_tool(
                "close_thread",
                {"thread_id": thread_id},
            )
            assert not repeat_close.is_error
            repeat_data = repeat_close.structured_content or json.loads(
                repeat_close.content[0].text
            )
            assert repeat_data["closure_status"] == "ALREADY_COMPLETED"


@pytest.mark.asyncio
async def test_mcp_m10_tools_unknown_thread_error(live_mcp_endpoint: str) -> None:
    """Tools 8 and 9 return tool errors when invoked with nonexistent thread_id."""
    async with streamable_http_client(live_mcp_endpoint) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            ver_err = await session.call_tool(
                "verify_thread_completion",
                {"thread_id": "thread-phantom-000"},
            )
            assert ver_err.is_error
            assert "not found" in ver_err.content[0].text.lower()

            close_err = await session.call_tool(
                "close_thread",
                {"thread_id": "thread-phantom-000"},
            )
            assert close_err.is_error
            assert "not found" in close_err.content[0].text.lower()
