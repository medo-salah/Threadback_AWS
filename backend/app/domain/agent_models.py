"""
Agent request/response models for M8 Agent Orchestration.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolActivity(BaseModel):
    """Activity indicator for an MCP tool invoked during agent execution."""

    tool_name: str = Field(..., description="Name of the MCP tool called")
    summary: str = Field(
        ..., description="Safe, user-facing summary of the tool activity"
    )


class AgentChatRequest(BaseModel):
    """Incoming user chat message."""

    message: str = Field(
        ..., min_length=1, description="User's natural language request"
    )
    conversation_id: str | None = Field(
        None, description="Optional conversation session ID. Generated if omitted."
    )


class AgentChatResponse(BaseModel):
    """Agent chat response returned to user/frontend."""

    message: str = Field(..., description="Natural language response from the agent")
    conversation_id: str = Field(..., description="Conversation session ID")
    pending_confirmation: bool = Field(
        False,
        description="Whether an action proposal is awaiting explicit confirmation",
    )
    proposal_id: str | None = Field(
        None, description="Exact ID of the pending ActionProposal, if any"
    )
    thread_id: str | None = Field(
        None, description="Thread ID affected by the proposal, if any"
    )
    activities: list[ToolActivity] = Field(
        default_factory=list,
        description="High-level list of tools executed to formulate this response",
    )
    execution_status: str | None = Field(
        None, description="Execution status if an action was executed (e.g. EXECUTED)"
    )
    execution_mode: str | None = Field(
        None, description="Execution mode if an action was executed (e.g. SIMULATED)"
    )
    radar_report: dict[str, Any] | None = Field(
        None, description="Optional Intent Radar summary payload (M13)"
    )
    diff_summary: dict[str, Any] | None = Field(
        None, description="Optional What-Changed differential summary payload (M13)"
    )


class AgentResetRequest(BaseModel):
    """Request to reset a conversation session and optionally demo state."""

    conversation_id: str = Field(..., description="Conversation ID to reset")
    reset_demo_state: bool = Field(
        False, description="Whether to also reset the underlying SQLite demo state"
    )


class AgentResetResponse(BaseModel):
    """Response acknowledging conversation reset."""

    status: str = Field(default="reset", description="Reset status")
    conversation_id: str = Field(..., description="Reset conversation ID")
