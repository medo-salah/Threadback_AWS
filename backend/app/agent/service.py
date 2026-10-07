"""
Threadback Agent Service orchestrator for M8.
"""

from __future__ import annotations

import logging

from app.agent.mcp_connector import (
    MCPConnectionError,
    MCPToolError,
    ThreadbackMCPClient,
)
from app.agent.providers.base import ModelProvider
from app.agent.providers.bedrock_provider import (
    BedrockConfigurationError,
    BedrockModelProvider,
    BedrockRuntimeError,
)
from app.agent.providers.mock_provider import MockModelProvider
from app.agent.state import ConversationManager, ConversationSession
from app.config import settings
from app.domain.agent_models import AgentChatResponse

logger = logging.getLogger(__name__)


class AgentService:
    """
    High-level agent orchestration service.
    Orchestrates conversation state, provider selection, and MCP communication.
    """

    def __init__(
        self,
        provider: ModelProvider | None = None,
        mcp_client: ThreadbackMCPClient | None = None,
        conversation_manager: ConversationManager | None = None,
    ) -> None:
        self.mcp_client = mcp_client or ThreadbackMCPClient(settings.threadback_mcp_url)
        self.conversation_manager = conversation_manager or ConversationManager()

        if provider is not None:
            self.provider = provider
        else:
            self.provider = self._create_provider(settings.threadback_agent_provider)

    def _create_provider(self, provider_name: str) -> ModelProvider:
        """Factory method for creating configured ModelProvider."""
        normalized = provider_name.strip().lower()
        if normalized == "mock":
            return MockModelProvider()
        elif normalized == "bedrock":
            return BedrockModelProvider()
        else:
            raise ValueError(
                f"Unknown THREADBACK_AGENT_PROVIDER: '{provider_name}'. Must be 'mock' or 'bedrock'."
            )

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> AgentChatResponse:
        """
        Process a user's natural language chat message through the agent.
        """
        session: ConversationSession = self.conversation_manager.get_or_create(
            conversation_id
        )
        session.add_message(role="user", content=message)

        try:
            response = await self.provider.process_message(
                user_message=message,
                session=session,
                mcp_client=self.mcp_client,
            )
            session.add_message(
                role="assistant",
                content=response.message,
                pending_confirmation=response.pending_confirmation,
                proposal_id=response.proposal_id,
            )

            # Persist M13 conversation checkpoint
            if session.active_thread_id:
                try:
                    from datetime import datetime, timezone

                    from app.services.thread_service import ThreadService

                    ThreadService().set_conversation_checkpoint(
                        conversation_id=session.conversation_id,
                        last_seen_at=datetime.now(timezone.utc),
                    )
                except Exception as ckpt_err:
                    logger.debug("Checkpoint persistence notice: %s", ckpt_err)

            return response

        except MCPConnectionError as exc:
            logger.error("MCP connection error during agent chat: %s", exc)
            err_msg = (
                "The Threadback MCP service is currently unavailable. "
                f"Please ensure the MCP server is running at {self.mcp_client.endpoint_url}."
            )
            session.add_message(role="assistant", content=err_msg, error=True)
            return AgentChatResponse(
                message=err_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
            )

        except MCPToolError as exc:
            logger.error("MCP tool error during agent chat: %s", exc)
            err_msg = f"Threadback MCP error: {exc}"
            session.add_message(role="assistant", content=err_msg, error=True)
            return AgentChatResponse(
                message=err_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
            )

        except BedrockConfigurationError as exc:
            logger.error("Bedrock configuration error: %s", exc)
            err_msg = f"Bedrock Configuration Error: {exc}"
            session.add_message(role="assistant", content=err_msg, error=True)
            return AgentChatResponse(
                message=err_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
            )

        except BedrockRuntimeError as exc:
            logger.error("Bedrock runtime error: %s", exc)
            err_msg = f"Bedrock Invocation Error: {exc}"
            session.add_message(role="assistant", content=err_msg, error=True)
            return AgentChatResponse(
                message=err_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
            )

        except Exception as exc:
            logger.exception("Unexpected error during agent chat: %s", exc)
            err_msg = (
                f"An unexpected error occurred while processing your request: {exc}"
            )
            session.add_message(role="assistant", content=err_msg, error=True)
            return AgentChatResponse(
                message=err_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
            )

    def reset_conversation(self, conversation_id: str) -> bool:
        """Reset conversation session state."""
        return self.conversation_manager.reset(conversation_id)


# Global singleton instance for FastAPI dependency injection
agent_service = AgentService()
