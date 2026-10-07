"""
Deterministic Why-Now Service for Threadback M14.

Explains why a thread deserves attention at this specific moment based exclusively
on structured Threadback state (commitments, deadlines, decay, blockers, changes,
resume eligibility, conflicts).

Invariants:
- Never invents reasons or fabricates urgency.
- If no meaningful reason exists, returns an empty/neutral explanation.
- Identifies strongest contributing factors, formatted concisely for Alexa+ voice output.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.domain.enums import (
    AttentionReasonCode,
    CommitmentStatus,
    ResumeEligibility,
    ThreadStatus,
)
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.domain.models import IntentConflict, IntentThread, ResumableCandidate

logger = logging.getLogger(__name__)


class WhyNowExplanation(BaseModel):
    """Structured, deterministic explanation of why an intention deserves attention now."""

    thread_id: str
    has_reason: bool
    primary_reason: str = ""
    reason_codes: list[AttentionReasonCode] = Field(default_factory=list)
    contributing_factors: list[str] = Field(default_factory=list)
    supporting_blocker_ids: list[str] = Field(default_factory=list)
    supporting_commitment_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    concise_alexa_text: str = ""


class WhyNowService:
    """
    Deterministic domain service explaining the temporal necessity of attention.

    Strictly read-only; grounded exclusively in structured thread state.
    """

    def explain(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
        resumable_info: ResumableCandidate | None = None,
        conflicts: list[IntentConflict] | None = None,
        recent_change_count: int = 0,
    ) -> WhyNowExplanation:
        """
        Produce a deterministic WhyNowExplanation for a thread at reference_time.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        reason_codes: list[AttentionReasonCode] = []
        factors: list[str] = []
        blocker_ids: list[str] = []
        commitment_ids: list[str] = []
        evidence_ids: list[str] = [e.id for e in thread.evidence]

        # 1. Commitment and deadline evaluation
        open_commitments = [
            c for c in thread.commitments if c.status == CommitmentStatus.OPEN
        ]
        has_overdue = False
        has_approaching = False

        for c in open_commitments:
            if c.due_at is not None:
                due = c.due_at
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                diff_sec = (due - ref_time).total_seconds()
                if diff_sec < 0:
                    has_overdue = True
                    commitment_ids.append(c.id)
                elif diff_sec <= 72.0 * 3600.0:
                    has_approaching = True
                    commitment_ids.append(c.id)

        if has_overdue:
            reason_codes.append(AttentionReasonCode.DEADLINE_OVERDUE)
            reason_codes.append(AttentionReasonCode.COMMITMENT_OVERDUE)
            factors.append("Has overdue commitment requiring immediate resolution")
        elif has_approaching:
            reason_codes.append(AttentionReasonCode.DEADLINE_APPROACHING)
            reason_codes.append(AttentionReasonCode.COMMITMENT_DUE)
            factors.append("Commitment deadline approaching within 72 hours")

        # 2. Blocker evaluation
        active_blockers = thread.active_blockers
        if active_blockers:
            reason_codes.append(AttentionReasonCode.BLOCKER_PRESENT)
            blocker_ids.extend([d.id for d in active_blockers])
            b_desc = active_blockers[0].description
            factors.append(f"Unresolved blocker: {b_desc}")
        elif thread.status == ThreadStatus.WAITING:
            factors.append("Waiting on external response")

        # 3. Decay and inactivity evaluation
        act_time = thread.last_activity_at
        if act_time.tzinfo is None:
            act_time = act_time.replace(tzinfo=timezone.utc)
        inactive_days = max(0.0, (ref_time - act_time).total_seconds() / 86400.0)

        if inactive_days >= 14.0:
            reason_codes.append(AttentionReasonCode.INTENT_STALE)
            reason_codes.append(AttentionReasonCode.LONG_INACTIVITY)
            factors.append(
                f"Intent has become stale after {int(inactive_days)} days of inactivity"
            )
        elif inactive_days >= 7.0:
            reason_codes.append(AttentionReasonCode.INTENT_DECAYING)
            reason_codes.append(AttentionReasonCode.LONG_INACTIVITY)
            factors.append(
                f"Intent is decaying after {int(inactive_days)} days without activity"
            )

        # 4. Resume eligibility
        if resumable_info and resumable_info.eligibility == ResumeEligibility.RESUMABLE:
            reason_codes.append(AttentionReasonCode.THREAD_RESUMABLE)
            factors.append(
                f"Deferred thread is ready to resume: {resumable_info.reason}"
            )

        # 5. Goal evolution
        if getattr(thread, "evolutions", None):
            reason_codes.append(AttentionReasonCode.GOAL_EVOLVED)
            latest_evo = thread.evolutions[-1]
            factors.append(
                f"Goal evolved: '{latest_evo.previous_goal}' → '{latest_evo.revised_goal}'"
            )

        # 6. Recent changes / new evidence
        if recent_change_count > 0:
            reason_codes.append(AttentionReasonCode.IMPORTANT_CHANGE)
            factors.append(f"{recent_change_count} recent state changes recorded")
        if thread.evidence:
            reason_codes.append(AttentionReasonCode.NEW_EVIDENCE)

        # 7. Conflicts
        if conflicts:
            matching_conflicts = [
                c
                for c in conflicts
                if c.thread_a_id == thread.id or c.thread_b_id == thread.id
            ]
            if matching_conflicts:
                reason_codes.append(AttentionReasonCode.CONFLICTING_INTENT)
                factors.append(f"Conflicts with: {matching_conflicts[0].explanation}")

        # Construct primary reason and concise voice text
        if not factors or (len(factors) == 1 and factors[0].startswith("Waiting")):
            # No meaningful reason to invent urgency
            return WhyNowExplanation(
                thread_id=thread.id,
                has_reason=False,
                primary_reason="No urgent factors requiring immediate attention",
                reason_codes=reason_codes,
                contributing_factors=factors,
                supporting_blocker_ids=blocker_ids,
                supporting_commitment_ids=commitment_ids,
                supporting_evidence_ids=evidence_ids,
                concise_alexa_text=f"{thread.title} currently has no pressing deadlines or blockers.",
            )

        primary_reason = factors[0]
        # Concise Alexa+ phrasing
        alexa_summary = f"{thread.title}: {primary_reason}."
        if len(factors) > 1:
            alexa_summary += f" Also, {factors[1].lower()}."

        return WhyNowExplanation(
            thread_id=thread.id,
            has_reason=True,
            primary_reason=primary_reason,
            reason_codes=reason_codes,
            contributing_factors=factors,
            supporting_blocker_ids=blocker_ids,
            supporting_commitment_ids=commitment_ids,
            supporting_evidence_ids=evidence_ids,
            concise_alexa_text=alexa_summary,
        )
