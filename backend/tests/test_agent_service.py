"""
Unit tests for Threadback M8 Agent Service, Confirmation State, and Providers.
"""

from __future__ import annotations

import pytest
from app.agent.mcp_connector import (
    MCPConnectionError,
    MCPToolError,
    ThreadbackMCPClient,
)
from app.agent.providers.bedrock_provider import (
    BedrockConfigurationError,
    BedrockModelProvider,
)
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.agent.state import (
    ConversationManager,
    is_ambiguous_confirmation,
    is_explicit_confirmation,
)

# ---------------------------------------------------------------------------
# 1. State & Confirmation Detection Tests
# ---------------------------------------------------------------------------


def test_conversation_manager_lifecycle() -> None:
    mgr = ConversationManager()
    session = mgr.get_or_create("conv-test-1")
    assert session.conversation_id == "conv-test-1"
    assert session.pending_confirmation is False
    assert session.pending_proposal_id is None

    session.add_message("user", "Hello")
    session.set_pending_proposal("proposal-123", "thread-abc")
    assert session.pending_confirmation is True
    assert session.pending_proposal_id == "proposal-123"
    assert session.pending_thread_id == "thread-abc"

    session.clear_pending()
    assert session.pending_confirmation is False
    assert session.pending_proposal_id is None

    # Reset
    assert mgr.reset("conv-test-1") is True
    assert mgr.get("conv-test-1") is None
    assert mgr.reset("conv-test-1") is False


def test_explicit_confirmation_matching() -> None:
    valid_confirmations = [
        "Yes",
        "yes",
        "YES",
        "Yes, do it",
        "Yes, proceed",
        "Go ahead",
        "go ahead",
        "Execute it",
        "execute",
        "Proceed",
        "Confirm",
        "Do it",
        "Sure, go ahead",
        "Please execute",
        "I confirm",
    ]
    for text in valid_confirmations:
        assert is_explicit_confirmation(text) is True, f"Failed for '{text}'"


def test_ambiguous_confirmation_matching() -> None:
    ambiguous_inputs = [
        "maybe",
        "that sounds interesting",
        "sounds good",
        "what would happen?",
        "tell me more",
        "okay, what exactly?",
        "what does that do?",
        "why?",
        "not sure",
        "can you clarify?",
    ]
    for text in ambiguous_inputs:
        assert is_ambiguous_confirmation(text) is True, f"Failed for '{text}'"
        assert is_explicit_confirmation(text) is False, (
            f"Should not be explicit: '{text}'"
        )


# ---------------------------------------------------------------------------
# 2. Bedrock Provider Configuration Tests
# ---------------------------------------------------------------------------


def test_bedrock_provider_missing_region() -> None:
    with pytest.raises(BedrockConfigurationError, match="AWS_REGION is required"):
        BedrockModelProvider(
            model_id="anthropic.claude-3-5-sonnet",
            region_name="",
            mcp_url="http://localhost:8000/mcp",
        )


def test_bedrock_provider_missing_model_id() -> None:
    with pytest.raises(BedrockConfigurationError, match="BEDROCK_MODEL_ID is required"):
        BedrockModelProvider(
            model_id="",
            region_name="us-east-1",
            mcp_url="http://localhost:8000/mcp",
        )


def test_bedrock_provider_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Clear AWS environment variables
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("AWS_CONFIG_FILE", raising=False)

    import boto3

    # Patch boto3 session to return no credentials
    class DummySession:
        def __init__(self, region_name: str | None = None) -> None:
            pass

        def get_credentials(self) -> None:
            return None

    monkeypatch.setattr(boto3, "Session", DummySession)

    with pytest.raises(BedrockConfigurationError, match="No AWS credentials found"):
        BedrockModelProvider(
            model_id="anthropic.claude-3-5-sonnet",
            region_name="us-east-1",
            mcp_url="http://localhost:8000/mcp",
        )


# ---------------------------------------------------------------------------
# 3. AgentService Error Handling & Edge Cases
# ---------------------------------------------------------------------------


class ErrorMCPClient(ThreadbackMCPClient):
    """Fake MCP client that raises errors for resilience testing."""

    def __init__(self, error_to_raise: Exception) -> None:
        super().__init__("http://localhost:9999/mcp")
        self.error_to_raise = error_to_raise

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        raise self.error_to_raise


@pytest.mark.asyncio
async def test_agent_service_mcp_unavailable() -> None:
    err_client = ErrorMCPClient(MCPConnectionError("Connection refused to 9999"))
    svc = AgentService(provider=MockModelProvider(), mcp_client=err_client)

    res = await svc.chat("What am I forgetting?")
    assert "currently unavailable" in res.message
    assert res.pending_confirmation is False


@pytest.mark.asyncio
async def test_agent_service_mcp_tool_error() -> None:
    err_client = ErrorMCPClient(MCPToolError("Thread not found"))
    svc = AgentService(provider=MockModelProvider(), mcp_client=err_client)

    res = await svc.chat("What am I forgetting?")
    assert "Threadback MCP error" in res.message


@pytest.mark.asyncio
async def test_agent_service_explicit_confirmation_without_pending() -> None:
    # A client that should not be called since there is no pending proposal
    err_client = ErrorMCPClient(MCPConnectionError("Should not connect"))
    svc = AgentService(provider=MockModelProvider(), mcp_client=err_client)

    res = await svc.chat("Yes, go ahead!")
    assert "no action proposal currently awaiting confirmation" in res.message.lower()
    assert res.pending_confirmation is False
