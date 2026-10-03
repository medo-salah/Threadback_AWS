"""
Tests for FastAPI agent API endpoints (/api/agent/chat, /api/agent/reset, /api/agent/info).
"""

from __future__ import annotations

import httpx
import pytest
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.service import AgentService
from app.main import _fastapi_app


class FakeMCPClient(ThreadbackMCPClient):
    """Fake MCP client providing structured mock data for API testing."""

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        args = arguments or {}
        if tool_name == "discover_unfinished_threads":
            return {
                "threads": [
                    {
                        "id": "thread-university-application",
                        "title": "University Application",
                        "status": "BLOCKED",
                        "priority": "HIGH",
                        "attention_level": "HIGH",
                    },
                    {
                        "id": "thread-client-report",
                        "title": "Client Report",
                        "status": "WAITING",
                        "priority": "MEDIUM",
                        "attention_level": "HIGH",
                    },
                ]
            }
        if tool_name == "get_thread_context":
            return {
                "id": args.get("thread_id", "thread-university-application"),
                "title": "University Application",
                "status": "BLOCKED",
                "priority": "HIGH",
                "commitments": [
                    {"title": "Submit application", "due_date": "2026-10-15"}
                ],
                "dependencies": [{"title": "Recommendation Letter", "blocking": True}],
                "evidence": [
                    {
                        "type": "EMAIL",
                        "description": "Ahmed agreed to write recommendation",
                    }
                ],
            }
        if tool_name == "analyze_thread":
            return {
                "analysis": {
                    "thread_id": args.get("thread_id"),
                    "current_status": "BLOCKED",
                    "attention": {"level": "HIGH", "score": 0.85},
                    "confidence": 0.85,
                    "unfinished_reasons": ["ACTIVE_BLOCKER", "OPEN_COMMITMENT"],
                }
            }
        if tool_name == "find_thread_blockers":
            return {
                "thread_id": args.get("thread_id"),
                "blocking_status": "BLOCKED",
                "blockers": [
                    {
                        "id": "dep-uni-rec-letter",
                        "title": "Recommendation letter from Ahmed",
                    }
                ],
            }
        if tool_name == "suggest_next_action":
            return {
                "suggestion": {
                    "thread_id": args.get("thread_id"),
                    "action_type": "UNBLOCKER_ACTION",
                    "reason": "Request recommendation letter from Ahmed",
                    "requires_confirmation": True,
                }
            }
        if tool_name == "prepare_action":
            return {
                "proposal": {
                    "id": "proposal-uni-test-1234",
                    "thread_id": args.get("thread_id"),
                    "action_type": "UNBLOCKER_ACTION",
                    "status": "CONFIRMATION_REQUIRED",
                    "risk_level": "MEDIUM",
                    "requires_confirmation": True,
                    "description": "Send follow-up request to Ahmed regarding recommendation letter",
                }
            }
        if tool_name == "execute_action":
            return {
                "execution_status": "EXECUTED",
                "execution_mode": args.get("execution_mode", "SIMULATED"),
                "proposal_id": args.get("proposal_id"),
                "thread_id": "thread-university-application",
                "event_id": "evt-test-123",
                "message": "Action simulated successfully.",
            }
        return {}


@pytest.fixture
def test_agent_svc() -> AgentService:
    client = FakeMCPClient("http://localhost:8000/mcp")
    provider = MockModelProvider()
    return AgentService(provider=provider, mcp_client=client)


@pytest.mark.asyncio
async def test_api_agent_info() -> None:
    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/agent/info")
        assert res.status_code == 200
        data = res.json()
        assert "provider" in data
        assert "mcp_url" in data


@pytest.mark.asyncio
async def test_api_agent_chat_discovery(
    test_agent_svc: AgentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Inject test agent service into the FastAPI dependency
    monkeypatch.setattr("app.routers.agent.agent_service", test_agent_svc)

    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/agent/chat", json={"message": "What am I forgetting?"}
        )
        assert res.status_code == 200
        data = res.json()
        assert "University Application" in data["message"]
        assert data["pending_confirmation"] is False
        assert len(data["activities"]) > 0


@pytest.mark.asyncio
async def test_api_agent_chat_controlled_action_and_confirmation_flow(
    test_agent_svc: AgentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routers.agent.agent_service", test_agent_svc)

    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # Step 1: Request help with finishing application
        res1 = await ac.post(
            "/api/agent/chat",
            json={
                "message": "Help me finish the application",
                "conversation_id": "conv-flow-1",
            },
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["pending_confirmation"] is True
        assert data1["proposal_id"] == "proposal-uni-test-1234"
        assert "SIMULATED" in data1["message"]

        # Step 2: Ambiguous response should NOT confirm
        res2 = await ac.post(
            "/api/agent/chat",
            json={"message": "What would happen?", "conversation_id": "conv-flow-1"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["pending_confirmation"] is True
        assert "explicit authorization" in data2["message"].lower()

        # Step 3: Explicit confirmation
        res3 = await ac.post(
            "/api/agent/chat",
            json={"message": "Yes, go ahead", "conversation_id": "conv-flow-1"},
        )
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["pending_confirmation"] is False
        assert data3["execution_status"] == "EXECUTED"
        assert data3["execution_mode"] == "SIMULATED"
        assert "No real external messages" in data3["message"]

        # Step 4: Reset conversation
        res4 = await ac.post(
            "/api/agent/reset",
            json={"conversation_id": "conv-flow-1"},
        )
        assert res4.status_code == 200
        assert res4.json()["status"] == "reset"


@pytest.mark.asyncio
async def test_conversational_greeting_clean_response(
    test_agent_svc: AgentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1: Conversational greeting ('hello') produces clean, friendly response without asterisks or tools."""
    monkeypatch.setattr("app.routers.agent.agent_service", test_agent_svc)

    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/agent/chat", json={"message": "hello"})
        assert res.status_code == 200
        data = res.json()
        assert "Threadback" in data["message"]
        assert "**" not in data["message"]
        assert "\\*" not in data["message"]
        assert "MCP Tools Orchestrated" not in data["message"]
        # Greeting should not trigger unnecessary MCP discovery calls
        assert len(data.get("activities", [])) == 0


@pytest.mark.asyncio
async def test_clean_response_and_tool_activity_separation(
    test_agent_svc: AgentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 2: Tool execution produces clean assistant response and separates tool activities."""
    monkeypatch.setattr("app.routers.agent.agent_service", test_agent_svc)

    transport = httpx.ASGITransport(app=_fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/agent/chat", json={"message": "What am I forgetting?"}
        )
        assert res.status_code == 200
        data = res.json()
        msg = data["message"]

        # 1. No raw markdown asterisks or escapes
        assert "**" not in msg
        assert "\\*" not in msg
        assert "`" not in msg

        # 2. Expected natural-language content is present
        assert "University Application" in msg
        assert "Client Report" in msg

        # 3. Tool activity is separated: NOT in assistant message, but in activities list
        assert "MCP Tools Orchestrated" not in msg
        assert "discover_unfinished_threads" not in msg
        assert len(data["activities"]) > 0
        assert any(
            act["tool_name"] == "discover_unfinished_threads"
            for act in data["activities"]
        )
