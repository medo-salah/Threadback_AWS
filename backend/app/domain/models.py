"""
Domain models for Threadback.

Defines Pydantic models for IntentThread and its supporting domain entities:
Commitment, Evidence, Dependency, Event, and tool response models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    AttentionLevel,
    AttentionReasonCode,
    ChangeCategory,
    ClosureStatus,
    CommitmentStatus,
    ConfidenceBand,
    ConflictType,
    DecayState,
    DecisionCardType,
    DependencyStatus,
    EvidenceType,
    ExecutionMode,
    ExecutionStatus,
    NextActionType,
    Priority,
    ProactiveTriggerType,
    ProposalStatus,
    ResumeEligibility,
    RiskLevel,
    SignificanceLevel,
    ThreadEventType,
    ThreadStatus,
    UnfinishedReason,
    WhatIfScenarioType,
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


class IntentEvolution(BaseModel):
    """Auditable record of how an intention transformed over time (M13)."""

    id: str
    thread_id: str
    previous_goal: str
    revised_goal: str
    reason: str
    timestamp: datetime
    trigger_event_id: str | None = None


class IntentDecaySignal(BaseModel):
    """Deterministic intent decay signal based on inactivity and deadlines (M13)."""

    decay_state: DecayState
    inactive_days: float
    days_until_deadline: float | None = None
    decay_score: float = Field(..., ge=0.0, le=1.0)
    decay_factors: list[str]
    explanation: str


class StateChangeItem(BaseModel):
    """Individual state transition detected between two points in time (M13)."""

    category: ChangeCategory
    description: str
    timestamp: datetime
    before_value: str | None = None
    after_value: str | None = None


class ThreadStateDiff(BaseModel):
    """Differential comparison of thread state over time (M13)."""

    thread_id: str
    since_timestamp: datetime
    has_changes: bool
    changes: list[StateChangeItem]
    summary: str


class IntentRadarItem(BaseModel):
    """Structured radar item for proactive intent monitoring (M13)."""

    thread_id: str
    title: str
    current_goal: str
    status: ThreadStatus
    priority: Priority
    attention_level: AttentionLevel
    decay_state: DecayState
    urgency_score: float = Field(..., ge=0.0, le=1.0)
    primary_signal: str
    explanation: str
    recommended_action: str

    @property
    def radar_score(self) -> int:
        return int(round(self.urgency_score * 100))


class IntentRadarReport(BaseModel):
    """Comprehensive radar scan across all open intentions (M13)."""

    generated_at: datetime
    active_threads_count: int
    items: list[IntentRadarItem]
    top_focus_thread_id: str | None = None
    top_focus_reason: str | None = None


class IntentSummary(BaseModel):
    """Structured holistic overview of an intent thread (M13)."""

    thread_id: str
    title: str
    original_goal: str
    current_goal: str
    status: ThreadStatus
    progress_percentage: int = Field(..., ge=0, le=100)
    active_blockers: list[str]
    completed_commitments: list[str]
    remaining_commitments: list[str]
    last_activity_at: datetime
    decay_state: DecayState
    recommended_next_step: str


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

    # M13 Additive fields (optional with safe defaults)
    current_goal: str | None = None
    radar_score: float | None = None
    decay_state: DecayState | None = None
    attention_level: AttentionLevel | None = None
    radar_explanation: str | None = None
    recommended_focus: bool = False


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

    # M13 Persistent Intent Memory fields
    original_goal: str | None = None
    current_goal: str | None = None
    last_interaction_at: datetime | None = None
    deferred_until: datetime | None = None
    abandoned_reason: str | None = None
    evolutions: list[IntentEvolution] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # Ensure non-null goal fields anchored to description by default
        if self.original_goal is None:
            self.original_goal = self.description
        if self.current_goal is None:
            self.current_goal = self.description
        if self.last_interaction_at is None:
            self.last_interaction_at = self.last_activity_at

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
            current_goal=self.current_goal or self.description,
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
        description=(
            "Execution mode: SIMULATED for external operational actions, "
            "or PERSISTENT_MUTATION for Threadback internal state mutations."
        ),
    )


class ExecutionResult(BaseModel):
    """Structured result of an action execution attempt (M7 / M13)."""

    proposal_id: str = Field(..., description="ID of the executed proposal")
    thread_id: str = Field(..., description="ID of the affected thread")
    action_type: NextActionType = Field(..., description="Type of action executed")
    execution_status: ExecutionStatus = Field(
        ...,
        description="Execution status: EXECUTED, REJECTED, BLOCKED, or ALREADY_EXECUTED",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SIMULATED,
        description=(
            "Execution mode: SIMULATED for external operational actions, "
            "PERSISTENT_MUTATION for internal Threadback state mutations."
        ),
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


# ---------------------------------------------------------------------------
# M14 Proactive Intent Intelligence Domain Models
# ---------------------------------------------------------------------------


class AttentionCandidate(BaseModel):
    """Deterministic attention candidate representing an intention requiring review (M14)."""

    thread_id: str
    thread_title: str
    attention_level: AttentionLevel
    attention_score: float = Field(..., ge=0.0, le=1.0)
    urgency_score: float = Field(..., ge=0.0, le=1.0)
    reason_codes: list[AttentionReasonCode] = Field(default_factory=list)
    human_readable_explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_commitment_ids: list[str] = Field(default_factory=list)
    blocker_ids: list[str] = Field(default_factory=list)
    recommended_action_summary: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AttentionDelta(BaseModel):
    """Deterministic differential change analysis since last checkpoint or anchor (M14)."""

    thread_id: str
    thread_title: str
    changes: list[StateChangeItem] = Field(default_factory=list)
    significance_score: float = Field(..., ge=0.0, le=1.0)
    significance_level: SignificanceLevel
    reason_codes: list[AttentionReasonCode] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntentConflict(BaseModel):
    """Conservative deterministic cross-thread conflict representation (M14)."""

    conflict_id: str
    thread_a_id: str
    thread_a_title: str
    thread_b_id: str
    thread_b_title: str
    conflict_type: ConflictType
    severity: Priority
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResumableCandidate(BaseModel):
    """Deterministic resume evaluation for a deferred intent thread (M14)."""

    thread_id: str
    thread_title: str
    eligibility: ResumeEligibility
    reason: str
    supporting_blocker_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_event_ids: list[str] = Field(default_factory=list)
    deferred_until: datetime | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntentHealthSummary(BaseModel):
    """Deterministic aggregate landscape metrics across all user intent threads (M14)."""

    total_active_threads: int
    healthy_threads: int
    attention_threads: int
    decaying_threads: int
    stale_threads: int
    blocked_threads: int
    deferred_threads: int = 0
    resumable_threads: int
    conflicts_count: int
    top_attention_candidates: list[AttentionCandidate] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProactiveBriefing(BaseModel):
    """Deterministic executive briefing summarizing the proactive intent landscape (M14)."""

    top_attention: list[AttentionCandidate] = Field(default_factory=list)
    top_changes: list[AttentionDelta] = Field(default_factory=list)
    top_resumable: list[ResumableCandidate] = Field(default_factory=list)
    top_conflicts: list[IntentConflict] = Field(default_factory=list)
    health_summary: IntentHealthSummary
    briefing_text: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProactiveTrigger(BaseModel):
    """Deterministic proactive trigger condition for internal evaluation (M14)."""

    trigger_id: str
    trigger_type: ProactiveTriggerType
    thread_id: str | None = None
    reason: str
    candidate_id: str | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProactiveInsightRecord(BaseModel):
    """Durable deduplication record preventing repetitive insight alerts (M14)."""

    insight_id: str
    thread_id: str
    insight_type: str
    state_fingerprint: str
    source_event_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# M15 Intent Copilot Models
# ---------------------------------------------------------------------------


class WhatIfSimulationResult(BaseModel):
    """Read-only deterministic simulation of scenario consequences (M15)."""

    scenario_type: WhatIfScenarioType
    thread_id: str
    thread_title: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    original_urgency: float
    simulated_urgency: float
    original_attention: float
    simulated_attention: float
    original_decay_state: str
    simulated_decay_state: str
    deadline_impact_description: str
    blocker_impact_description: str
    resumability_impact_description: str
    affected_related_thread_ids: list[str] = Field(default_factory=list)
    relationship_evidence: list[str] = Field(
        default_factory=list,
        description="Explicit structured relationships identifying why each thread is affected",
    )
    simulation_summary: str
    label: str = "SIMULATION — NO STATE CHANGED"
    simulated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TimeBudgetRecommendation(BaseModel):
    """Deterministic recommendation fitting structured work within available time (M15)."""

    available_minutes: int
    selected_thread_id: str
    selected_thread_title: str
    reason: str
    expected_next_action: str
    fits_budget: bool
    is_blocked: bool
    estimated_duration_minutes: int | None = None
    confidence: float = 0.90


class SafeClosureCandidate(BaseModel):
    """Read-only assessment of closure safety for an intent thread (M15)."""

    thread_id: str
    thread_title: str
    is_safe_to_close: bool
    completion_evidence_count: int
    active_blockers_count: int
    open_commitments_count: int
    verification_status: str
    closure_readiness_reason: str
    next_step: str


class IntentDecisionCard(BaseModel):
    """Structured conversational recommendation card for frontend and copilot (M15)."""

    card_id: str
    card_type: DecisionCardType
    thread_id: str | None = None
    thread_title: str | None = None
    title: str
    summary: str
    evidence_snippets: list[str] = Field(default_factory=list)
    recommended_action: str | None = None
    attention_level: AttentionLevel | None = None
    urgency_score: float | None = None
    attention_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PrioritizedThreadSummary(BaseModel):
    """Shortlist item for 'What should I do first?' distinguishing Urgency vs Attention (M15)."""

    rank: int
    thread_id: str
    thread_title: str
    priority: Priority
    attention_level: AttentionLevel
    urgency_score: float
    attention_score: float
    blocker_pressure: float
    deadline_pressure: float
    why_it_ranks_high: str
    recommended_next_step: str


class IntentCopilotOverview(BaseModel):
    """Comprehensive Copilot synthesis response (M15)."""

    primary_recommendation: str
    ranked_priorities: list[PrioritizedThreadSummary] = Field(default_factory=list)
    decision_cards: list[IntentDecisionCard] = Field(default_factory=list)
    resumable_candidates: list[ResumableCandidate] = Field(default_factory=list)
    safe_closure_candidates: list[SafeClosureCandidate] = Field(default_factory=list)
    alexa_voice_text: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
