"""
Domain models for Threadback.

Defines Pydantic models for IntentThread and its supporting domain entities:
Commitment, Evidence, Dependency, Event, and tool response models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    AttentionLevel,
    ClosureStatus,
    CommitmentStatus,
    ConfidenceBand,
    DependencyStatus,
    EvidenceType,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    Priority,
    ProposalStatus,
    RiskLevel,
    ThreadEventType,
    ThreadStatus,
    UnfinishedReason,
)


class Commitment(BaseModel):
    """An explicit or implicit obligation within an intent thread."""

    id: str
    description: str
    status: CommitmentStatus = CommitmentStatus.OPEN
    due_at: datetime | None = None


class Evidence(BaseModel):
    """An evidentiary item that supports or grounds an intent thread."""

    id: str
    type: EvidenceType
    description: str
    source: str
    created_at: datetime
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 (weakest) and 1.0 (strongest)",
    )


class Dependency(BaseModel):
    """A requirement or dependency that may impede progress on an intent thread."""

    id: str
    description: str
    type: str = "GENERAL"
    status: DependencyStatus = DependencyStatus.OPEN
    blocking: bool = True

    @property
    def is_active_blocker(self) -> bool:
        """True if dependency is currently open and marked as blocking."""
        return self.blocking and self.status == DependencyStatus.OPEN


class Event(BaseModel):
    """A historical or state change event on an intent thread."""

    id: str
    type: str
    description: str
    timestamp: datetime


class ThreadEvent(Event):
    """
    Persistent lifecycle history event for an IntentThread (M10).

    Captures the auditable history of changes to an intention across time,
    including thread discovery, evidence additions, blocker detections,
    action preparations, simulated executions, verification outcomes, and completion.
    """

    thread_id: str
    event_type: ThreadEventType | str
    actor: str = "system"
    source: str = "deterministic_engine"
    payload: dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data: Any) -> None:
        if "event_id" in data and "id" not in data:
            data["id"] = data["event_id"]
        if "event_type" in data and "type" not in data:
            et = data["event_type"]
            data["type"] = et.value if hasattr(et, "value") else str(et)
        super().__init__(**data)

    @property
    def event_id(self) -> str:
        """Alias for id providing explicit M10 event identity naming."""
        return self.id


class ThreadSummary(BaseModel):
    """Compact summary of an intent thread for discovery and indexing."""

    id: str
    title: str
    status: ThreadStatus
    priority: Priority
    confidence: float = Field(..., ge=0.0, le=1.0)
    last_activity_at: datetime
    open_commitments: int
    open_blockers: int


class IntentThread(BaseModel):
    """
    Core domain entity representing an open or completed intent thread.

    An IntentThread captures an ongoing objective or unresolved situation,
    grounded by evidence, shaped by commitments and dependencies, and traced
    through historical events.
    """

    id: str
    title: str
    description: str
    status: ThreadStatus
    priority: Priority
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in thread validity, between 0.0 and 1.0",
    )
    commitments: list[Commitment] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    events: list[ThreadEvent | Event] = Field(default_factory=list)

    @property
    def active_blockers(self) -> list[Dependency]:
        """Return list of active blockers (blocking=True and status=OPEN)."""
        return [d for d in self.dependencies if d.is_active_blocker]

    @property
    def open_commitments_count(self) -> int:
        """Count commitments with OPEN status."""
        return sum(1 for c in self.commitments if c.status == CommitmentStatus.OPEN)

    def to_summary(self) -> ThreadSummary:
        """Project this thread into a compact ThreadSummary."""
        return ThreadSummary(
            id=self.id,
            title=self.title,
            status=self.status,
            priority=self.priority,
            confidence=self.confidence,
            last_activity_at=self.last_activity_at,
            open_commitments=self.open_commitments_count,
            open_blockers=len(self.active_blockers),
        )


# ---------------------------------------------------------------------------
# MCP Tool Response Models (M3)
# ---------------------------------------------------------------------------


class DiscoverThreadsResponse(BaseModel):
    """Response payload for discover_unfinished_threads MCP tool."""

    threads: list[ThreadSummary]


class ThreadContextResponse(BaseModel):
    """
    Response payload for get_thread_context MCP tool.

    Exposes all thread fields at the top level and as an embedded `thread`
    object to provide full compatibility with different client access patterns.
    """

    id: str
    title: str
    description: str
    status: ThreadStatus
    priority: Priority
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    confidence: float = Field(..., ge=0.0, le=1.0)
    commitments: list[Commitment] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    thread: IntentThread

    @classmethod
    def from_thread(cls, thread: IntentThread) -> ThreadContextResponse:
        """Build response from an IntentThread domain instance."""
        return cls(
            id=thread.id,
            title=thread.title,
            description=thread.description,
            status=thread.status,
            priority=thread.priority,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            last_activity_at=thread.last_activity_at,
            confidence=thread.confidence,
            commitments=thread.commitments,
            evidence=thread.evidence,
            dependencies=thread.dependencies,
            events=thread.events,
            thread=thread,
        )


class ThreadBlockersResponse(BaseModel):
    """Response payload for find_thread_blockers MCP tool."""

    thread_id: str
    blockers: list[Dependency]
    blocking_status: str


# ---------------------------------------------------------------------------
# M4 Analysis Models
# ---------------------------------------------------------------------------


class EvidenceSummary(BaseModel):
    """Aggregated evidence statistics for a thread analysis."""

    total: int
    by_type: dict[str, int]
    strongest_evidence_ids: list[str]
    weakest_evidence_ids: list[str]
    average_confidence: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate evidence confidence (weighted by recency and strength)",
    )
    confidence_band: ConfidenceBand
    is_sufficient: bool
    is_weak: bool
    is_stale: bool = Field(
        ...,
        description="True if the entire evidence set is stale (all items > 30 days old) or empty",
    )
    has_stale_evidence: bool = Field(
        default=False,
        description="True if the evidence set contains at least one stale evidence item (> 30 days old)",
    )
    stale_evidence_ids: list[str] = Field(
        default_factory=list,
        description="List of IDs for individual evidence items older than 30 days",
    )
    most_recent_evidence_id: str | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class BlockerDetail(BaseModel):
    """Structured blocker detail for analysis output."""

    dependency_id: str
    description: str
    type: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class AttentionSignal(BaseModel):
    """Deterministic attention signal for a thread."""

    level: AttentionLevel
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized attention score between 0.0 and 1.0",
    )
    factors: list[str]


class ThreadAnalysis(BaseModel):
    """
    Structured deterministic analysis of an IntentThread.

    Produced by the analysis engine (M4), this model represents a complete
    explanation of the current state of a thread using only structured data.
    No LLM is involved in producing this analysis.
    """

    thread_id: str
    current_status: ThreadStatus
    explanation: str
    unfinished_reasons: list[UnfinishedReason]
    open_commitments: list[str]
    active_blockers: list[BlockerDetail]
    evidence_summary: EvidenceSummary
    attention: AttentionSignal
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall analysis confidence",
    )
    confidence_band: ConfidenceBand


class ThreadAnalysisResponse(BaseModel):
    """Response payload for analyze_thread MCP tool."""

    analysis: ThreadAnalysis


# ---------------------------------------------------------------------------
# M5 Next Action Models
# ---------------------------------------------------------------------------


class NextActionSuggestion(BaseModel):
    """
    Deterministic next action recommendation for an IntentThread.

    Produced by the Next Action Engine (M5) using structured domain data
    and M4 thread analysis.
    Planning only — does not execute actions.
    """

    thread_id: str
    action_type: NextActionType
    action: str = Field(
        ...,
        description="Concise, actionable user-facing description of the recommended next step",
    )
    rationale: str = Field(
        ...,
        description="Structured explanation of why this action was selected",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Deterministic confidence in this recommendation",
    )
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_commitment_ids: list[str] = Field(default_factory=list)
    supporting_dependency_ids: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    requires_confirmation: bool = Field(
        default=False,
        description="True if this action would eventually cause an external side effect (e.g. messaging, scheduling)",
    )


class NextActionResponse(BaseModel):
    """Response payload for suggest_next_action MCP tool."""

    suggestion: NextActionSuggestion


# ---------------------------------------------------------------------------
# M6 Action Preparation Models
# ---------------------------------------------------------------------------


class ActionProposal(BaseModel):
    """
    Prepared action ready for human review (M6).

    Pre-execution planning artifact. Does NOT execute actions or mutate state.
    Provides complete transparency into what action would occur, why, what inputs
    would be used, what side effects would occur, and whether confirmation is required.
    """

    id: str = Field(
        ...,
        description="Deterministic proposal identity derived from stable inputs (proposal-<hash>)",
    )
    thread_id: str
    action_type: NextActionType
    title: str = Field(..., description="User-facing summary of the prepared action")
    description: str = Field(
        ..., description="Detailed explanation of the action to be prepared"
    )
    rationale: str = Field(
        ..., description="Structured justification derived from M4/M5"
    )
    status: ProposalStatus = Field(
        ...,
        description="Review status: READY, CONFIRMATION_REQUIRED, or BLOCKED",
    )
    requires_confirmation: bool = Field(
        ...,
        description="True if this action would create external side effects requiring confirmation",
    )
    confirmation_reason: str | None = Field(
        default=None,
        description="Explanation of why confirmation is required or why preparation is blocked",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured data parameters required to perform the action (never fabricated)",
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="Prerequisites that must be satisfied before execution",
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence IDs grounding this proposal",
    )
    supporting_commitment_ids: list[str] = Field(
        default_factory=list,
        description="Commitment IDs grounding this proposal",
    )
    supporting_dependency_ids: list[str] = Field(
        default_factory=list,
        description="Dependency IDs grounding this proposal",
    )
    risk_level: RiskLevel = Field(
        ...,
        description="Deterministic risk classification: LOW, MEDIUM, or HIGH",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the proposal was prepared (deterministic anchor)",
    )


class ActionProposalResponse(BaseModel):
    """Response payload for prepare_action MCP tool."""

    proposal: ActionProposal


# ---------------------------------------------------------------------------
# M7 Execution Models
# ---------------------------------------------------------------------------


class ExecuteActionRequest(BaseModel):
    """Request payload for execute_action MCP tool."""

    proposal_id: str = Field(
        ..., description="Deterministic proposal identity to execute"
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation. Required if requires_confirmation is True.",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SIMULATED,
        description="Execution mode. M7 supports only SIMULATED mode.",
    )


class ExecutionResult(BaseModel):
    """Structured result of an action execution attempt (M7)."""

    proposal_id: str = Field(..., description="ID of the executed proposal")
    thread_id: str = Field(..., description="ID of the affected thread")
    action_type: NextActionType = Field(..., description="Type of action executed")
    execution_status: ExecutionStatus = Field(
        ...,
        description="Execution status: EXECUTED, REJECTED, BLOCKED, or ALREADY_EXECUTED",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SIMULATED,
        description="Execution mode (M7 is always SIMULATED)",
    )
    message: str = Field(..., description="Human-readable outcome description")
    event_id: str | None = Field(
        default=None,
        description="Audit event ID recorded on the thread if execution succeeded",
    )


class ExecutionResultResponse(BaseModel):
    """Response payload for execute_action MCP tool.

    Provides direct top-level fields matching the M7 example shape and
    an embedded result object for dual-pattern client compatibility.
    """

    proposal_id: str
    thread_id: str
    action_type: NextActionType
    execution_status: ExecutionStatus
    execution_mode: ExecutionMode
    message: str
    event_id: str | None = None
    result: ExecutionResult

    @classmethod
    def from_result(cls, res: ExecutionResult) -> ExecutionResultResponse:
        """Construct response wrapping ExecutionResult."""
        return cls(
            proposal_id=res.proposal_id,
            thread_id=res.thread_id,
            action_type=res.action_type,
            execution_status=res.execution_status,
            execution_mode=res.execution_mode,
            message=res.message,
            event_id=res.event_id,
            result=res,
        )


# ---------------------------------------------------------------------------
# M10 Lifecycle & Verification Models
# ---------------------------------------------------------------------------


class ThreadVerification(BaseModel):
    """
    Structured deterministic verification result of an IntentThread's completion (M10).

    Records whether an intention has sufficient factual evidence to be considered
    fulfilled, separating action execution from actual completion.
    """

    thread_id: str
    verified: bool
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Deterministic verification confidence score between 0.0 and 1.0",
    )
    reason: str = Field(
        ...,
        description="Structured explanation of the verification outcome",
    )
    required_evidence: list[str] = Field(
        default_factory=list,
        description="Categories or items of evidence required to verify completion",
    )
    matched_evidence: list[str] = Field(
        default_factory=list,
        description="IDs or descriptions of evidence satisfying completion criteria",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Unsatisfied completion evidence or unresolved blockers",
    )
    verified_at: datetime = Field(
        ...,
        description="Timestamp when the deterministic verification was evaluated",
    )


class ThreadVerificationResponse(BaseModel):
    """Response payload for verify_thread_completion MCP tool (M10)."""

    thread_id: str
    verified: bool
    confidence: float
    reason: str
    required_evidence: list[str] = Field(default_factory=list)
    matched_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    verified_at: datetime
    verification: ThreadVerification

    @classmethod
    def from_verification(
        cls, verification: ThreadVerification
    ) -> ThreadVerificationResponse:
        """Construct response wrapping ThreadVerification."""
        return cls(
            thread_id=verification.thread_id,
            verified=verification.verified,
            confidence=verification.confidence,
            reason=verification.reason,
            required_evidence=verification.required_evidence,
            matched_evidence=verification.matched_evidence,
            missing_evidence=verification.missing_evidence,
            verified_at=verification.verified_at,
            verification=verification,
        )


class CloseThreadResponse(BaseModel):
    """Response payload for close_thread MCP tool (M10)."""

    thread_id: str
    status: ThreadStatus
    closure_status: ClosureStatus | str
    message: str
    verification_id: str | None = None
    event_id: str | None = None
