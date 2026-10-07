"""
Streamable HTTP MCP Client connector for Threadback (M8).

Connects to the canonical Threadback MCP Server at http://localhost:8000/mcp
using the official Model Context Protocol (MCP) Python SDK.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class MCPConnectionError(RuntimeError):
    """Raised when the MCP server cannot be reached."""


class MCPToolError(RuntimeError):
    """Raised when an MCP tool returns an error."""


class ThreadbackMCPClient:
    """
    Client connector for invoking Threadback MCP tools over Streamable HTTP.
    Maintains tool boundary without importing domain services directly.
    """

    def __init__(self, endpoint_url: str = "http://localhost:8000/mcp") -> None:
        self.endpoint_url = endpoint_url

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Execute an MCP tool via Streamable HTTP and return its structured payload.
        """
        args = arguments or {}
        try:
            async with streamable_http_client(self.endpoint_url) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, args)

                    if result.is_error:
                        err_msg = (
                            result.content[0].text
                            if result.content and hasattr(result.content[0], "text")
                            else f"MCP tool {tool_name} returned an error"
                        )
                        raise MCPToolError(err_msg)

                    if result.structured_content is not None:
                        return result.structured_content

                    # Fallback to parsing text content as JSON
                    if result.content and hasattr(result.content[0], "text"):
                        text = result.content[0].text
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {"text": text}

                    return {}
        except (MCPToolError, MCPConnectionError):
            raise
        except Exception as exc:
            logger.error(
                "Failed to communicate with MCP server at %s: %s",
                self.endpoint_url,
                exc,
            )
            raise MCPConnectionError(
                f"Threadback MCP server is unavailable at {self.endpoint_url}: {exc}"
            ) from exc

    async def discover_unfinished_threads(
        self,
        query: str | None = None,
        min_priority: str | None = None,
        min_attention: str | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {}
        if query:
            args["query"] = query
        if min_priority:
            args["min_priority"] = min_priority
        if min_attention:
            args["min_attention"] = min_attention
        return await self.call_tool("discover_unfinished_threads", args)

    async def get_thread_context(self, thread_id: str) -> dict[str, Any]:
        return await self.call_tool("get_thread_context", {"thread_id": thread_id})

    async def find_thread_blockers(self, thread_id: str) -> dict[str, Any]:
        return await self.call_tool("find_thread_blockers", {"thread_id": thread_id})

    async def analyze_thread(self, thread_id: str) -> dict[str, Any]:
        return await self.call_tool("analyze_thread", {"thread_id": thread_id})

    async def suggest_next_action(self, thread_id: str) -> dict[str, Any]:
        return await self.call_tool("suggest_next_action", {"thread_id": thread_id})

    async def prepare_action(
        self,
        thread_id: str,
        action_type: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"thread_id": thread_id}
        if action_type:
            args["action_type"] = action_type
        if parameters:
            args["parameters"] = parameters
        return await self.call_tool("prepare_action", args)

    async def execute_action(
        self,
        proposal_id: str,
        confirmed: bool = True,
        execution_mode: str = "SIMULATED",
    ) -> dict[str, Any]:
        return await self.call_tool(
            "execute_action",
            {
                "proposal_id": proposal_id,
                "confirmed": confirmed,
                "execution_mode": execution_mode,
            },
        )

    async def verify_thread_completion(self, thread_id: str) -> dict[str, Any]:
        """Call verify_thread_completion MCP tool (M10)."""
        return await self.call_tool(
            "verify_thread_completion", {"thread_id": thread_id}
        )

    async def close_thread(self, thread_id: str) -> dict[str, Any]:
        """Call close_thread MCP tool (M10)."""
        return await self.call_tool("close_thread", {"thread_id": thread_id})
