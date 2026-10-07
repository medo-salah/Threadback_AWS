"""
Amazon Bedrock Model Provider using Strands Agents and MCPClient (M8).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.prompts import THREADBACK_SYSTEM_PROMPT
from app.agent.providers.base import ModelProvider
from app.agent.state import (
    ConversationSession,
    is_ambiguous_confirmation,
    is_explicit_confirmation,
)
from app.config import settings
from app.domain.agent_models import AgentChatResponse, ToolActivity

logger = logging.getLogger(__name__)


class BedrockConfigurationError(RuntimeError):
    """Raised when Amazon Bedrock configuration or AWS credentials are missing or invalid."""


class BedrockRuntimeError(RuntimeError):
    """Raised when Amazon Bedrock invocation fails."""


class BedrockModelProvider(ModelProvider):
    """
    Strands Agent provider running on Amazon Bedrock.
    Connects to Threadback MCP Server over Streamable HTTP via Strands MCPClient.
    """

    def __init__(
        self,
        model_id: str | None = None,
        region_name: str | None = None,
        mcp_url: str | None = None,
    ) -> None:
        self.model_id = model_id if model_id is not None else settings.bedrock_model_id
        self.region_name = (
            region_name
            if region_name is not None
            else (settings.aws_region or os.getenv("AWS_DEFAULT_REGION", ""))
        )
        self.mcp_url = mcp_url if mcp_url is not None else settings.threadback_mcp_url

        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate required Bedrock settings and credentials."""
        if not self.region_name:
            raise BedrockConfigurationError(
                "Amazon Bedrock configuration error: AWS_REGION is required but not set."
            )
        if not self.model_id:
            raise BedrockConfigurationError(
                "Amazon Bedrock configuration error: BEDROCK_MODEL_ID is required but not set."
            )

        # Validate that boto3 can locate AWS credentials
        try:
            import boto3

            session = boto3.Session(region_name=self.region_name)
            credentials = session.get_credentials()
            if credentials is None:
                raise BedrockConfigurationError(
                    "Amazon Bedrock configuration error: No AWS credentials found. "
                    "Please configure AWS credentials via environment variables, IAM role, or ~/.aws/credentials."
                )
        except BedrockConfigurationError:
            raise
        except Exception as exc:
            raise BedrockConfigurationError(
                f"Amazon Bedrock initialization failed: {exc}"
            ) from exc

    def _get_strands_agent(self) -> Any:
        """Instantiate a Strands Agent wired to BedrockModel and MCPClient."""
        from strands import Agent
        from strands.models import BedrockModel
        from strands.tools.mcp import MCPClient

        bedrock_model = BedrockModel(
            model_id=self.model_id,
            region_name=self.region_name,
        )
        mcp_tool_client = MCPClient(url=self.mcp_url)

        return Agent(
            model=bedrock_model,
            tools=[mcp_tool_client],
            system_prompt=THREADBACK_SYSTEM_PROMPT,
        )

    async def process_message(
        self,
        user_message: str,
        session: ConversationSession,
        mcp_client: ThreadbackMCPClient,
    ) -> AgentChatResponse:
        """
        Process user message using the Bedrock Strands Agent with MCP tool integration.
        Enforces confirmation gates and safety boundaries deterministically.
        """
        activities: list[ToolActivity] = []

        # -------------------------------------------------------------------
        # 1. Check for Pending Confirmation Flow
        # -------------------------------------------------------------------
        if session.pending_confirmation and session.pending_proposal_id:
            if is_explicit_confirmation(user_message):
                proposal_id = session.pending_proposal_id
                activities.append(
                    ToolActivity(
                        tool_name="execute_action",
                        summary=f"Executing simulation for proposal {proposal_id}...",
                    )
                )

                exec_result = await mcp_client.execute_action(
                    proposal_id=proposal_id,
                    confirmed=True,
                    execution_mode="SIMULATED",
                )

                exec_status = exec_result.get("execution_status", "EXECUTED")
                exec_mode = exec_result.get("execution_mode", "SIMULATED")
                event_id = exec_result.get("event_id", "evt-simulated")
                result_msg = exec_result.get(
                    "message", "Action simulated successfully."
                )

                session.clear_pending()

                if exec_mode == "PERSISTENT_MUTATION":
                    explanation = (
                        f"I have applied this persistent Threadback state mutation.\n\n"
                        f"• Status: {exec_status}\n"
                        f"• Execution Mode: {exec_mode} (Durable internal Threadback state mutated)\n"
                        f"• Proposal ID: {proposal_id}\n"
                        f"• Audit Event ID: {event_id}\n"
                        f"• Details: {result_msg}\n\n"
                        f"Your thread state, database record, and lifecycle event ledger have been permanently updated."
                    )
                else:
                    explanation = (
                        f"I executed the action in SIMULATION mode.\n\n"
                        f"• Status: {exec_status}\n"
                        f"• Execution Mode: {exec_mode} (No real external messages, emails, or calls were made)\n"
                        f"• Proposal ID: {proposal_id}\n"
                        f"• Audit Event ID: {event_id}\n"
                        f"• Details: {result_msg}\n\n"
                        f"Your thread state and audit log have been updated with this simulated event."
                    )

                return AgentChatResponse(
                    message=explanation,
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                    execution_status=exec_status,
                    execution_mode=exec_mode,
                )

            if is_ambiguous_confirmation(user_message):
                return AgentChatResponse(
                    message=(
                        f"Action execution requires explicit authorization before proceeding.\n\n"
                        f"I have prepared proposal `{session.pending_proposal_id}` on standby. "
                        f"Please note that execution will be strictly SIMULATED — no actual email or external communication will be sent.\n\n"
                        f"Would you like me to proceed with the simulation? Please answer 'Yes' or 'Go ahead' to authorize."
                    ),
                    conversation_id=session.conversation_id,
                    pending_confirmation=True,
                    proposal_id=session.pending_proposal_id,
                    thread_id=session.pending_thread_id,
                    activities=activities,
                )

        if is_explicit_confirmation(user_message) and not session.pending_confirmation:
            return AgentChatResponse(
                message="There is no action proposal currently awaiting confirmation. What intention or thread would you like me to help you with?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 2. Invoke Strands Agent on Bedrock
        # -------------------------------------------------------------------
        try:
            agent = self._get_strands_agent()
            result = agent(user_message)

            raw_text = ""
            msg = result.message
            if isinstance(msg, dict):
                content = msg.get("content", [])
                if isinstance(content, str):
                    raw_text = content
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            parts.append(block["text"])
                        elif hasattr(block, "text"):
                            parts.append(block.text)
                        elif isinstance(block, str):
                            parts.append(block)
                    raw_text = "\n".join(parts)
            else:
                raw_text = str(result)

            # Inspect if a proposal ID was prepared in the text
            proposal_match = re.search(r"proposal-[a-f0-9]{16}", raw_text)
            pending_confirm = False
            proposal_id = None
            if proposal_match and (
                "confirm" in raw_text.lower()
                or "requires confirmation" in raw_text.lower()
            ):
                proposal_id = proposal_match.group(0)
                pending_confirm = True
                session.set_pending_proposal(proposal_id)

            return AgentChatResponse(
                message=raw_text,
                conversation_id=session.conversation_id,
                pending_confirmation=pending_confirm,
                proposal_id=proposal_id,
                activities=activities,
            )
        except BedrockConfigurationError:
            raise
        except Exception as exc:
            logger.error("Bedrock Strands Agent invocation error: %s", exc)
            raise BedrockRuntimeError(f"Bedrock Agent execution error: {exc}") from exc
