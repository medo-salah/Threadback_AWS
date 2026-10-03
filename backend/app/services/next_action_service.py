"""
Next Action Engine for Threadback M5.

Provides deterministic next action recommendations for IntentThreads based on
structured domain data and M4 thread analysis.
Planning only — does NOT execute actions.
No LLM, no external APIs, no database, no random values.

Architecture
------------
IntentThread
     ↓
AnalysisService.analyze()
     ↓
ThreadAnalysis
     ↓
NextActionService.suggest_action()
     ↓
NextActionSuggestion

Decision Precedence
-------------------
0. Terminal/closed thread (COMPLETED, ABANDONED) → NO_ACTION
1. Insufficient evidence → GATHER_EVIDENCE_ACTION
2. Active blocking dependency → UNBLOCKER_ACTION
3. Waiting dependency → FOLLOW_UP_ACTION
4. Open actionable commitment → DIRECT_NEXT_ACTION
5. Unfinished thread without commitments or blockers → DIRECT_NEXT_ACTION (review)
6. Fallback → NO_ACTION
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    NextActionType,
    ThreadStatus,
)
from app.domain.models import NextActionSuggestion
from app.services.analysis_service import (
    DEFAULT_ANALYSIS_REFERENCE_TIME,
    AnalysisService,
)

if TYPE_CHECKING:
    from app.domain.models import (
        BlockerDetail,
        Commitment,
        Dependency,
        IntentThread,
        ThreadAnalysis,
    )

# Keywords indicating an action has external side effects (e.g. messaging, booking, submitting)
EXTERNAL_SIDE_EFFECT_KEYWORDS: tuple[str, ...] = (
    "call",
    "send",
    "submit",
    "deliver",
    "email",
    "message",
    "schedule",
    "book",
    "pay",
    "order",
    "contact",
    "request",
    "ask",
    "notify",
)

# Dependency types indicating external parties/systems requiring confirmation
EXTERNAL_DEPENDENCY_TYPES: tuple[str, ...] = (
    "PERSON",
    "CLIENT",
    "EXTERNAL",
    "THIRD_PARTY",
    "VENDOR",
    "ORGANIZATION",
)


def _has_external_side_effect(text: str, dep_type: str | None = None) -> bool:
    """Determine whether an action or dependency would cause external side effects."""
    if dep_type and dep_type.upper() in EXTERNAL_DEPENDENCY_TYPES:
        return True
    lower = text.lower()
    return any(kw in lower for kw in EXTERNAL_SIDE_EFFECT_KEYWORDS)


def _format_unblocker_action(blocker_description: str) -> str:
    """Format a clear user-facing action description for an active blocker."""
    desc = blocker_description.strip()
    lower = desc.lower()
    if lower.startswith(
        (
            "ask ",
            "request ",
            "get ",
            "obtain ",
            "submit ",
            "complete ",
            "call ",
            "contact ",
            "follow up ",
        )
    ):
        return desc
    return f"Resolve blocker: {desc}"


def _format_follow_up_action(dep_description: str) -> str:
    """Format a clear user-facing action description for a waiting dependency."""
    desc = dep_description.strip()
    lower = desc.lower()
    if lower.startswith(("follow up", "check on", "inquire")):
        return desc
    return f"Follow up on pending dependency: {desc}"


class NextActionService:
    """
    Deterministic Next Action Engine for IntentThread planning.

    Transforms structured domain data and M4 ThreadAnalysis into an explainable,
    traceable next-action recommendation.
    Independent of MCP, transport, LLM, and execution layers.
    """

    def __init__(self, analysis_service: AnalysisService | None = None) -> None:
        self._analysis_service = analysis_service or AnalysisService()

    def suggest_action(
        self,
        thread: IntentThread,
        analysis: ThreadAnalysis | None = None,
        reference_time: datetime | None = None,
    ) -> NextActionSuggestion:
        """
        Determine the next recommended action for an IntentThread.

        Follows the strict deterministic decision tree:
            Step 0: Terminal / closed thread → NO_ACTION
            Step 1: Insufficient evidence → GATHER_EVIDENCE_ACTION
            Step 2: Active blocking dependency → UNBLOCKER_ACTION
            Step 3: Waiting dependency → FOLLOW_UP_ACTION
            Step 4: Open actionable commitment → DIRECT_NEXT_ACTION
            Step 5: Thread-level milestone review → DIRECT_NEXT_ACTION
            Step 6: Fallback → NO_ACTION

        Args:
            thread: The IntentThread to plan for.
            analysis: Optional precomputed ThreadAnalysis. If None, computed via AnalysisService.
            reference_time: Optional deterministic reference timestamp.

        Returns:
            NextActionSuggestion with action type, action text, rationale, confidence,
            supporting source IDs, preconditions, and confirmation requirement.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME

        # Re-use or compute M4 analysis
        if analysis is None:
            analysis = self._analysis_service.analyze(thread, reference_time=ref_time)

        # -------------------------------------------------------------------
        # Step 0: Terminal / Closed Thread
        # -------------------------------------------------------------------
        if thread.status in (ThreadStatus.COMPLETED, ThreadStatus.ABANDONED):
            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.NO_ACTION,
                action=f"No action required; thread '{thread.title}' is {thread.status.value.lower()}.",
                rationale=(
                    f"Thread '{thread.title}' has status {thread.status.value}. "
                    "All objectives have been concluded or dismissed; no open loop remains."
                ),
                confidence=1.0,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                preconditions=[],
                requires_confirmation=False,
            )

        # -------------------------------------------------------------------
        # Step 1: Insufficient Evidence Check → GATHER_EVIDENCE_ACTION
        # -------------------------------------------------------------------
        if not analysis.evidence_summary.is_sufficient:
            ev_count = analysis.evidence_summary.total
            avg_conf = analysis.evidence_summary.average_confidence
            action_conf = round(max(0.30, min(0.60, analysis.confidence)), 4)
            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.GATHER_EVIDENCE_ACTION,
                action=f"Gather additional context and documentation for '{thread.title}'.",
                rationale=(
                    f"Available evidence is insufficient (count: {ev_count}, "
                    f"average confidence: {avg_conf:.2f}) to confidently determine a specific action. "
                    "Review latest communications or notes to establish current status."
                ),
                confidence=action_conf,
                supporting_evidence_ids=[e.id for e in thread.evidence],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                preconditions=[
                    "Additional documentation or communication needed to clarify thread status"
                ],
                requires_confirmation=False,
            )

        # -------------------------------------------------------------------
        # Step 2: Active Blocking Dependency → UNBLOCKER_ACTION
        # -------------------------------------------------------------------
        # Active blocker on a blocked thread or active thread with active blockers
        # (For WAITING threads, the thread is paused waiting on an external response, handled in Step 3)
        if thread.status != ThreadStatus.WAITING and len(analysis.active_blockers) > 0:
            blocker = self._select_best_blocker(
                analysis.active_blockers, thread.commitments
            )
            action_text = _format_unblocker_action(blocker.description)

            # Match related open commitments
            blocker_words = {
                w.strip(".,;:!?()[]\"'")
                for w in blocker.description.lower().split()
                if len(w.strip(".,;:!?()[]\"'")) > 2
            }
            related_commitments = [
                c.id
                for c in thread.commitments
                if c.status == CommitmentStatus.OPEN
                and (
                    {w.strip(".,;:!?()[]\"'") for w in c.description.lower().split()}
                    & blocker_words
                )
            ]

            requires_confirm = _has_external_side_effect(action_text, blocker.type)
            confidence = round(
                min(1.0, 0.50 * thread.confidence + 0.50 * analysis.confidence),
                4,
            )

            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.UNBLOCKER_ACTION,
                action=action_text,
                rationale=(
                    f"Progress on '{thread.title}' is blocked by pending dependency "
                    f"'{blocker.description}'. Addressing this blocker is required "
                    "before the thread can proceed."
                ),
                confidence=confidence,
                supporting_evidence_ids=blocker.supporting_evidence_ids,
                supporting_commitment_ids=related_commitments,
                supporting_dependency_ids=[blocker.dependency_id],
                preconditions=[f"Dependency '{blocker.description}' must be resolved"],
                requires_confirmation=requires_confirm,
            )

        # -------------------------------------------------------------------
        # Step 3: Waiting Dependency → FOLLOW_UP_ACTION
        # -------------------------------------------------------------------
        open_dependencies = [
            d for d in thread.dependencies if d.status == DependencyStatus.OPEN
        ]
        if (thread.status == ThreadStatus.WAITING and open_dependencies) or (
            any(not d.blocking for d in open_dependencies)
        ):
            dep = self._select_best_dependency(open_dependencies, thread)
            action_text = _format_follow_up_action(dep.description)

            # Supporting evidence matching dependency words
            dep_words = {
                w.strip(".,;:!?()[]\"'")
                for w in dep.description.lower().split()
                if len(w.strip(".,;:!?()[]\"'")) > 2
            }
            matching_ev_ids = [
                e.id
                for e in thread.evidence
                if {w.strip(".,;:!?()[]\"'") for w in e.description.lower().split()}
                & dep_words
            ]

            requires_confirm = _has_external_side_effect(action_text, dep.type)
            confidence = round(
                min(1.0, 0.50 * thread.confidence + 0.50 * analysis.confidence),
                4,
            )

            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.FOLLOW_UP_ACTION,
                action=action_text,
                rationale=(
                    f"Thread '{thread.title}' is paused in WAITING status awaiting resolution of "
                    f"dependency '{dep.description}'. A follow-up is recommended."
                ),
                confidence=confidence,
                supporting_evidence_ids=matching_ev_ids,
                supporting_commitment_ids=[
                    c.id
                    for c in thread.commitments
                    if c.status == CommitmentStatus.OPEN
                ],
                supporting_dependency_ids=[dep.id],
                preconditions=[f"Awaiting external response for '{dep.description}'"],
                requires_confirmation=requires_confirm,
            )

        # -------------------------------------------------------------------
        # Step 4: Open Actionable Commitment → DIRECT_NEXT_ACTION
        # -------------------------------------------------------------------
        open_commitments = [
            c for c in thread.commitments if c.status == CommitmentStatus.OPEN
        ]
        if open_commitments:
            commitment = self._select_best_commitment(open_commitments)
            action_text = commitment.description

            requires_confirm = _has_external_side_effect(action_text)
            confidence = round(
                min(1.0, 0.50 * thread.confidence + 0.50 * analysis.confidence),
                4,
            )

            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.DIRECT_NEXT_ACTION,
                action=action_text,
                rationale=(
                    f"Thread '{thread.title}' is active and unblocked. Fulfilling open commitment "
                    f"'{commitment.description}' is the immediate direct next step."
                ),
                confidence=confidence,
                supporting_evidence_ids=[e.id for e in thread.evidence],
                supporting_commitment_ids=[commitment.id],
                supporting_dependency_ids=[],
                preconditions=[
                    f"Commitment '{commitment.description}' is open and actionable"
                ],
                requires_confirmation=requires_confirm,
            )

        # -------------------------------------------------------------------
        # Step 5: Thread-Level Action (Unfinished without commitments/blockers)
        # -------------------------------------------------------------------
        if thread.status in (
            ThreadStatus.DISCOVERED,
            ThreadStatus.ACTIVE,
            ThreadStatus.WAITING,
        ):
            return NextActionSuggestion(
                thread_id=thread.id,
                action_type=NextActionType.DIRECT_NEXT_ACTION,
                action=f"Review '{thread.title}' to define next milestone and commitments.",
                rationale=(
                    f"Thread '{thread.title}' is in {thread.status.value} status but has no explicit "
                    "open commitments or active blockers. Establishing concrete milestones is required to advance."
                ),
                confidence=round(thread.confidence * 0.70, 4),
                supporting_evidence_ids=[e.id for e in thread.evidence],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                preconditions=[],
                requires_confirmation=False,
            )

        # -------------------------------------------------------------------
        # Step 6: Fallback → NO_ACTION
        # -------------------------------------------------------------------
        return NextActionSuggestion(
            thread_id=thread.id,
            action_type=NextActionType.NO_ACTION,
            action=f"No action required for thread '{thread.title}'.",
            rationale=(
                f"Thread '{thread.title}' in status {thread.status.value} has no active blockers, "
                "waiting dependencies, or commitments requiring intervention."
            ),
            confidence=1.0,
            supporting_evidence_ids=[],
            supporting_commitment_ids=[],
            supporting_dependency_ids=[],
            preconditions=[],
            requires_confirmation=False,
        )

    # -----------------------------------------------------------------------
    # Deterministic Tie-Breaking Helpers
    # -----------------------------------------------------------------------

    def _select_best_blocker(
        self,
        blockers: list[BlockerDetail],
        commitments: list[Commitment],
    ) -> BlockerDetail:
        """
        Deterministically select the highest priority active blocker.

        Precedence:
            1. Commitment overlap with an open commitment: 1 if blocker words overlap with open commitment words, 0 otherwise (descending)
            2. Supporting evidence count: len(b.supporting_evidence_ids) (descending)
            3. Stable identifier: b.dependency_id ascending
        """
        open_comm_words: set[str] = set()
        for c in commitments:
            if c.status == CommitmentStatus.OPEN:
                words = {
                    w.strip(".,;:!?()[]\"'")
                    for w in c.description.lower().split()
                    if len(w.strip(".,;:!?()[]\"'")) > 2
                }
                open_comm_words.update(words)

        def _sort_key(b: BlockerDetail) -> tuple[int, int, str]:
            blocker_words = {
                w.strip(".,;:!?()[]\"'")
                for w in b.description.lower().split()
                if len(w.strip(".,;:!?()[]\"'")) > 2
            }
            has_comm_overlap = 1 if (blocker_words & open_comm_words) else 0
            evidence_count = len(b.supporting_evidence_ids)
            # Tuple: (-has_comm_overlap, -evidence_count, dependency_id)
            return (-has_comm_overlap, -evidence_count, b.dependency_id)

        return sorted(blockers, key=_sort_key)[0]

    def _select_best_dependency(
        self,
        dependencies: list[Dependency],
        thread: IntentThread,
    ) -> Dependency:
        """
        Deterministically select the highest priority waiting dependency.

        Precedence:
            1. Evidence match count: count of evidence items matching dependency description (descending)
            2. Stable identifier: d.id ascending
        """

        def _sort_key(d: Dependency) -> tuple[int, str]:
            dep_words = {
                w.strip(".,;:!?()[]\"'")
                for w in d.description.lower().split()
                if len(w.strip(".,;:!?()[]\"'")) > 2
            }
            ev_matches = sum(
                1
                for e in thread.evidence
                if {w.strip(".,;:!?()[]\"'") for w in e.description.lower().split()}
                & dep_words
            )
            return (-ev_matches, d.id)

        return sorted(dependencies, key=_sort_key)[0]

    def _select_best_commitment(
        self,
        commitments: list[Commitment],
    ) -> Commitment:
        """
        Deterministically select the highest priority open commitment.

        Precedence:
            1. Due date: earliest due_at first (None placed at end)
            2. Stable identifier: c.id ascending
        """

        def _sort_key(c: Commitment) -> tuple[int, datetime, str]:
            has_due = 0 if c.due_at is not None else 1
            due_val = c.due_at or datetime.max
            return (has_due, due_val, c.id)

        return sorted(commitments, key=_sort_key)[0]
