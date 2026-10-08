"""
FastAPI router for Threadback Agent (M8).
Exposes /api/agent/chat and /api/agent/reset.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.agent.service import agent_service
from app.config import settings
from app.domain.agent_models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentResetRequest,
    AgentResetResponse,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
) -> AgentChatResponse:
    """
    Send a natural language message to the Threadback Agent.
    Orchestrates MCP tools to discover threads, reconstruct context, prepare actions,
    and safely simulate execution after explicit confirmation.
    """
    return await agent_service.chat(
        message=request.message,
        conversation_id=request.conversation_id,
    )


@router.post("/reset", response_model=AgentResetResponse)
async def agent_reset(
    request: AgentResetRequest,
) -> AgentResetResponse:
    """
    Reset conversation session state and optionally restore canonical demo data.
    """
    agent_service.reset_conversation(request.conversation_id)
    if request.reset_demo_state:
        from app.mcp.server import execution_service, proposal_registry, thread_service

        thread_service.reset(seed=True)
        proposal_registry.clear()
        execution_service._ledger.clear()

    return AgentResetResponse(
        status="reset",
        conversation_id=request.conversation_id,
    )


@router.post("/demo-reset", response_model=AgentResetResponse)
async def agent_demo_reset(
    request: AgentResetRequest,
) -> AgentResetResponse:
    """
    Deterministic development/demo-only reset: resets conversation session and restores
    canonical demo dataset in persistent SQLite storage.
    """
    from app.mcp.server import execution_service, proposal_registry, thread_service

    agent_service.reset_conversation(request.conversation_id)
    thread_service.reset(seed=True)
    proposal_registry.clear()
    execution_service._ledger.clear()
    return AgentResetResponse(
        status="demo_state_reset",
        conversation_id=request.conversation_id,
    )


@router.get("/info")
async def agent_info() -> dict[str, str]:
    """
    Return basic agent configuration metadata (provider, mcp url).
    """
    return {
        "provider": settings.threadback_agent_provider,
        "mcp_url": settings.client_mcp_url,
        "model_id": settings.bedrock_model_id
        if settings.threadback_agent_provider == "bedrock"
        else "mock",
    }
