"""
Abstract Base Class for Threadback Model Providers (M8).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.state import ConversationSession
from app.domain.agent_models import AgentChatResponse


class ModelProvider(ABC):
    """
    Abstract interface for model providers in Threadback.
    Ensures provider swapability (e.g. mock vs bedrock) without changing the agent service.
    """

    @abstractmethod
    async def process_message(
        self,
        user_message: str,
        session: ConversationSession,
        mcp_client: ThreadbackMCPClient,
    ) -> AgentChatResponse:
        """
        Process a user's natural language message using MCP tools and return a structured response.
        """
