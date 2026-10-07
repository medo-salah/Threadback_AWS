"""
Deterministic Change Analysis Service for Threadback M14.

Computes AttentionDelta using the approved M13 4-tier comparison anchor:
  1. Explicit user timestamp range (since_timestamp)
  2. Checkpoint for conversation_id from repository
  3. Target thread's last_interaction_at
  4. DEFAULT_ANALYSIS_REFERENCE_TIME

Invariants:
- Grounded strictly in actual persisted state/events.
- Zero NLP guessing or fabricated statements.
- Deterministic significance scoring and level mapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    AttentionReasonCode,
    ChangeCategory,
    SignificanceLevel,
)
from app.domain.models import AttentionDelta, IntentThread, StateChangeItem
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.repositories.base import BaseThreadRepository

logger = logging.getLogger(__name__)

# Significance scores for state changes
SCORE_GOAL_EVOLVED: float = 0.85
SCORE_BLOCKER_RESOLVED: float = 0.75
SCORE_STATUS_CHANGE: float = 0.70
SCORE_COMMITMENT_CHANGE: float = 0.55
SCORE_EVIDENCE_ADDED: float = 0.40
SCORE_ACTION_EVENT: float = 0.25


class ChangeAnalysisService:
    """Deterministic domain service analyzing state transitions over time."""

    def __init__(self, repository: BaseThreadRepository | None = None) -> None:
        self._repository = repository

    def determine_anchor(
        self,
        thread: IntentThread,
        since_timestamp: datetime | None = None,
        conversation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> datetime:
        """
        Resolve the factual comparison anchor using the 4-tier priority.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME

        # Tier 1: Explicit user timestamp
        if since_timestamp is not None:
            anchor = since_timestamp
        # Tier 2: Conversation checkpoint
        elif conversation_id is not None and self._repository is not None:
            ckpt = self._repository.get_conversation_checkpoint(conversation_id)
            if ckpt is not None:
                anchor = ckpt
            else:
                anchor = None
        else:
            anchor = None

        # Tier 3: Target thread's last_interaction_at
        if anchor is None and thread.last_interaction_at is not None:
            anchor = thread.last_interaction_at

        # Tier 4: System default analysis reference time
        if anchor is None:
            anchor = ref_time

        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return anchor

    def analyze_changes(
        self,
        thread: IntentThread,
        since_timestamp: datetime | None = None,
        conversation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> AttentionDelta:
        """
        Detect factual state changes occurring after the resolved anchor.
        """
        anchor = self.determine_anchor(
            thread,
            since_timestamp=since_timestamp,
            conversation_id=conversation_id,
            reference_time=reference_time,
        )

        changes: list[StateChangeItem] = []
        source_event_ids: list[str] = []
        score_components: list[float] = []
        reason_codes: list[AttentionReasonCode] = []

        # 1. Evidence items created after anchor
        for ev in thread.evidence:
            ev_ts = ev.created_at
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            if ev_ts > anchor:
                changes.append(
                    StateChangeItem(
                        category=ChangeCategory.EVIDENCE_CHANGE,
                        description=f"Evidence added: {ev.description}",
                        timestamp=ev_ts,
                        after_value=ev.description,
                    )
                )
                source_event_ids.append(ev.id)
                score_components.append(SCORE_EVIDENCE_ADDED)
                if AttentionReasonCode.NEW_EVIDENCE not in reason_codes:
                    reason_codes.append(AttentionReasonCode.NEW_EVIDENCE)

        # 2. Intent evolutions after anchor
        if getattr(thread, "evolutions", None):
            for evo in thread.evolutions:
                evo_ts = evo.timestamp
                if evo_ts.tzinfo is None:
                    evo_ts = evo_ts.replace(tzinfo=timezone.utc)
                if evo_ts > anchor:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.GOAL_CHANGE,
                            description=f"Goal updated: '{evo.previous_goal}' → '{evo.revised_goal}'",
                            timestamp=evo_ts,
                            before_value=evo.previous_goal,
                            after_value=evo.revised_goal,
                        )
                    )
                    source_event_ids.append(evo.id)
                    score_components.append(SCORE_GOAL_EVOLVED)
                    if AttentionReasonCode.GOAL_EVOLVED not in reason_codes:
                        reason_codes.append(AttentionReasonCode.GOAL_EVOLVED)

        # 3. Thread events & lifecycle after anchor
        for event in thread.events:
            e_ts = event.timestamp
            if e_ts.tzinfo is None:
                e_ts = e_ts.replace(tzinfo=timezone.utc)
            if e_ts > anchor:
                etype = getattr(event, "event_type", event.type)
                if hasattr(etype, "value"):
                    etype = etype.value
                etype_str = str(etype)

                if "EVOLVE" in etype_str:
                    # Already handled in evolutions if present, or add if not duplicated
                    if not any(
                        c.category == ChangeCategory.GOAL_CHANGE and c.timestamp == e_ts
                        for c in changes
                    ):
                        changes.append(
                            StateChangeItem(
                                category=ChangeCategory.GOAL_CHANGE,
                                description=f"Goal evolved: {event.description}",
                                timestamp=e_ts,
                                after_value=event.description,
                            )
                        )
                        score_components.append(SCORE_GOAL_EVOLVED)
                        if AttentionReasonCode.GOAL_EVOLVED not in reason_codes:
                            reason_codes.append(AttentionReasonCode.GOAL_EVOLVED)
                elif "RESOLVED" in etype_str or "UNBLOCKED" in etype_str:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.BLOCKER_CHANGE,
                            description=f"Blocker resolved: {event.description}",
                            timestamp=e_ts,
                            after_value=event.description,
                        )
                    )
                    score_components.append(SCORE_BLOCKER_RESOLVED)
                    if AttentionReasonCode.IMPORTANT_CHANGE not in reason_codes:
                        reason_codes.append(AttentionReasonCode.IMPORTANT_CHANGE)
                elif (
                    "DEFER" in etype_str
                    or "RESUME" in etype_str
                    or "COMPLETE" in etype_str
                    or "ABANDON" in etype_str
                ):
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.STATUS_CHANGE,
                            description=f"Lifecycle transition: {event.description}",
                            timestamp=e_ts,
                            after_value=event.description,
                        )
                    )
                    score_components.append(SCORE_STATUS_CHANGE)
                elif "COMMITMENT" in etype_str:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.ACTION_CHANGE,
                            description=f"Commitment updated: {event.description}",
                            timestamp=e_ts,
                        )
                    )
                    score_components.append(SCORE_COMMITMENT_CHANGE)
                else:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.ACTION_CHANGE,
                            description=f"Event: {event.description}",
                            timestamp=e_ts,
                        )
                    )
                    score_components.append(SCORE_ACTION_EVENT)

                source_event_ids.append(event.id)

        # Sort changes chronologically
        changes.sort(key=lambda c: c.timestamp)

        # Compute significance score
        if not score_components:
            significance_score = 0.0
            significance_level = SignificanceLevel.NONE
        else:
            # Maximum individual change significance, with slight boost for multiple changes
            base_score = max(score_components)
            boost = min(0.15, 0.05 * (len(score_components) - 1))
            significance_score = min(1.0, base_score + boost)

            if significance_score >= 0.70:
                significance_level = SignificanceLevel.HIGH
                if AttentionReasonCode.IMPORTANT_CHANGE not in reason_codes:
                    reason_codes.append(AttentionReasonCode.IMPORTANT_CHANGE)
            elif significance_score >= 0.40:
                significance_level = SignificanceLevel.MEDIUM
            else:
                significance_level = SignificanceLevel.LOW

        eval_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if eval_time.tzinfo is None:
            eval_time = eval_time.replace(tzinfo=timezone.utc)

        return AttentionDelta(
            thread_id=thread.id,
            thread_title=thread.title,
            changes=changes,
            significance_score=round(significance_score, 4),
            significance_level=significance_level,
            reason_codes=reason_codes,
            source_event_ids=list(dict.fromkeys(source_event_ids)),
            evaluated_at=eval_time,
        )
