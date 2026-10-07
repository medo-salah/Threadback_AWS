"""
Intent Radar and Decay Detection Service for Threadback M13.

Authoritative deterministic domain service providing:
1. Intent Decay Detection (HEALTHY, ATTENTION, DECAYING, STALE).
2. Intent Radar Urgency Scoring & Proactive Monitoring.
3. Cross-Thread Prioritization with explainable factors.
4. "What Changed?" State Differential Engine with 4-tier comparison anchor.

All calculations are strictly grounded in structured data — zero LLM hallucinations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    AttentionLevel,
    ChangeCategory,
    CommitmentStatus,
    DecayState,
    Priority,
    ThreadStatus,
)
from app.domain.models import (
    IntentDecaySignal,
    IntentRadarItem,
    IntentRadarReport,
    IntentThread,
    StateChangeItem,
    ThreadStateDiff,
)
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.services.thread_service import ThreadService

logger = logging.getLogger(__name__)

# Numerical Priority Mapping
PRIORITY_SCORES: dict[Priority, float] = {
    Priority.HIGH: 1.0,
    Priority.MEDIUM: 0.6,
    Priority.LOW: 0.2,
}

# Decay State Numerical Weights
DECAY_SCORES: dict[DecayState, float] = {
    DecayState.STALE: 1.0,
    DecayState.DECAYING: 0.8,
    DecayState.ATTENTION: 0.5,
    DecayState.HEALTHY: 0.1,
}


class IntentRadarService:
    """Authoritative deterministic service for radar scans, decay detection, and state diffing."""

    def __init__(self, thread_service: ThreadService | None = None) -> None:
        self._thread_service = thread_service

    def compute_decay_signal(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> IntentDecaySignal:
        """
        Deterministically evaluate intent decay state based on inactivity and deadlines.

        Thresholds:
          - STALE: Inactive >= 14 days OR (inactive >= 7 days and deadline overdue)
          - DECAYING: Inactive 7-14 days OR (inactive >= 4 days and blocked)
          - ATTENTION: Inactive 3-7 days OR deadline approaching within 72 hours
          - HEALTHY: Inactive < 3 days and no deadline pressure
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        last_act = thread.last_activity_at
        if last_act.tzinfo is None:
            last_act = last_act.replace(tzinfo=timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        inactive_days = max(0.0, (ref_time - last_act).total_seconds() / 86400.0)

        # Check earliest open commitment due date
        open_due_dates = [
            c.due_at.replace(tzinfo=timezone.utc)
            if c.due_at.tzinfo is None
            else c.due_at
            for c in thread.commitments
            if c.due_at and c.status == CommitmentStatus.OPEN
        ]
        deadline_days: float | None = None
        if open_due_dates:
            earliest_due = min(open_due_dates)
            deadline_days = (earliest_due - ref_time).total_seconds() / 86400.0

        factors: list[str] = []

        # Classification logic
        if inactive_days >= 14.0:
            state = DecayState.STALE
            factors.append(
                f"Inactive for {inactive_days:.0f} days (exceeds 14-day threshold)"
            )
        elif deadline_days is not None and deadline_days < 0 and inactive_days >= 7.0:
            state = DecayState.STALE
            factors.append(
                f"Commitment overdue by {abs(deadline_days):.0f} days and inactive for {inactive_days:.0f} days"
            )
        elif 7.0 <= inactive_days < 14.0:
            state = DecayState.DECAYING
            factors.append(f"No recent activity for {inactive_days:.0f} days")
        elif thread.status == ThreadStatus.BLOCKED and inactive_days >= 4.0:
            state = DecayState.DECAYING
            factors.append(
                f"Blocked without forward progress for {inactive_days:.0f} days"
            )
        elif 3.0 <= inactive_days < 7.0:
            state = DecayState.ATTENTION
            factors.append(
                f"Moderate inactivity ({inactive_days:.0f} days since last event)"
            )
        elif deadline_days is not None and 0.0 <= deadline_days <= 3.0:
            state = DecayState.ATTENTION
            factors.append(f"Approaching deadline in {deadline_days:.1f} days")
        else:
            state = DecayState.HEALTHY
            factors.append("Active recently and on track")

        decay_score = DECAY_SCORES[state]
        explanation = "; ".join(factors)

        return IntentDecaySignal(
            decay_state=state,
            inactive_days=round(inactive_days, 1),
            days_until_deadline=round(deadline_days, 1)
            if deadline_days is not None
            else None,
            decay_score=decay_score,
            decay_factors=factors,
            explanation=explanation,
        )

    def compute_radar_item(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> IntentRadarItem:
        """Calculate composite urgency score and structured radar item for a single thread."""
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        decay_signal = self.compute_decay_signal(thread, reference_time=ref_time)

        # Component scores
        s_priority = PRIORITY_SCORES.get(thread.priority, 0.5)

        s_deadline = 0.2
        if decay_signal.days_until_deadline is not None:
            dd = decay_signal.days_until_deadline
            if dd < 0:
                s_deadline = 1.0  # Overdue
            elif dd <= 3.0:
                s_deadline = 0.9  # Imminent
            elif dd <= 7.0:
                s_deadline = 0.6  # Approaching
            else:
                s_deadline = 0.3

        s_decay = decay_signal.decay_score

        s_blocker = 0.3
        if thread.status == ThreadStatus.BLOCKED or len(thread.active_blockers) > 0:
            s_blocker = 0.9
        elif thread.status == ThreadStatus.WAITING:
            s_blocker = 0.6

        open_comms = thread.open_commitments_count
        total_comms = max(1, len(thread.commitments))
        s_comms = min(1.0, open_comms / total_comms)

        # Composite Urgency Formula
        # U = 0.30*priority + 0.25*deadline + 0.20*decay + 0.15*blocker + 0.10*commitments
        urgency = (
            0.30 * s_priority
            + 0.25 * s_deadline
            + 0.20 * s_decay
            + 0.15 * s_blocker
            + 0.10 * s_comms
        )
        urgency = min(1.0, max(0.0, urgency))

        # Determine attention level
        if urgency >= 0.70:
            att_level = AttentionLevel.HIGH
        elif urgency >= 0.40:
            att_level = AttentionLevel.MEDIUM
        else:
            att_level = AttentionLevel.LOW

        # Generate explainable primary signal
        signal_reasons: list[str] = []
        if s_deadline >= 0.9:
            signal_reasons.append("Deadline critical")
        if s_priority >= 0.9:
            signal_reasons.append("High priority commitment")
        if s_blocker >= 0.8:
            signal_reasons.append("Active blocker needs resolution")
        if decay_signal.decay_state in (DecayState.STALE, DecayState.DECAYING):
            signal_reasons.append(
                f"Decaying ({decay_signal.decay_state.value.lower()})"
            )

        primary_signal = signal_reasons[0] if signal_reasons else "Normal monitoring"
        explanation = f"{primary_signal}: {decay_signal.explanation}"

        # Determine recommended action
        rec_action = "Review intention context"
        if thread.active_blockers:
            rec_action = f"Unblock: {thread.active_blockers[0].description}"
        elif thread.open_commitments_count > 0:
            for c in thread.commitments:
                if c.status == CommitmentStatus.OPEN:
                    rec_action = f"Complete: {c.description}"
                    break

        return IntentRadarItem(
            thread_id=thread.id,
            title=thread.title,
            current_goal=thread.current_goal or thread.description,
            status=thread.status,
            priority=thread.priority,
            attention_level=att_level,
            decay_state=decay_signal.decay_state,
            urgency_score=round(urgency, 2),
            primary_signal=primary_signal,
            explanation=explanation,
            recommended_action=rec_action,
        )

    def prioritize_threads(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[IntentRadarItem]:
        """Rank open intent threads by deterministic urgency score in descending order."""
        items = [
            self.compute_radar_item(t, reference_time=reference_time)
            for t in threads
            if t.status not in (ThreadStatus.COMPLETED, ThreadStatus.ABANDONED)
        ]
        items.sort(key=lambda x: x.urgency_score, reverse=True)
        return items

    def compute_radar_report(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> IntentRadarReport:
        """Scan all open threads and synthesize a complete Intent Radar report."""
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        ranked_items = self.prioritize_threads(threads, reference_time=ref_time)

        top_id: str | None = None
        top_reason: str | None = None
        if ranked_items:
            top_item = ranked_items[0]
            top_id = top_item.thread_id
            top_reason = (
                f"{top_item.title} requires focus first ({top_item.explanation})"
            )

        return IntentRadarReport(
            generated_at=ref_time,
            active_threads_count=len(ranked_items),
            items=ranked_items,
            top_focus_thread_id=top_id,
            top_focus_reason=top_reason,
        )

    def diff_thread_state(
        self,
        thread: IntentThread,
        since_timestamp: datetime | None = None,
        conversation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> ThreadStateDiff:
        """
        Compute factual differential comparison using the 4-tier anchor priority:
          1. Explicit user timestamp range
          2. Checkpoint for conversation_id from repository
          3. thread.last_interaction_at
          4. DEFAULT_ANALYSIS_REFERENCE_TIME
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        anchor: datetime | None = None

        # Priority 1: User explicitly provided timestamp
        if since_timestamp is not None:
            anchor = since_timestamp
        # Priority 2: Checkpoint for conversation_id
        elif conversation_id is not None and self._thread_service is not None:
            ckpt = self._thread_service.repository.get_conversation_checkpoint(
                conversation_id
            )
            if ckpt is not None:
                anchor = ckpt
        # Priority 3: Target thread's last_interaction_at
        if anchor is None and thread.last_interaction_at is not None:
            anchor = thread.last_interaction_at
        # Priority 4: System reference default
        if anchor is None:
            anchor = ref_time

        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)

        changes: list[StateChangeItem] = []

        # 1. Evidence changes
        for ev in thread.evidence:
            ev_ts = (
                ev.created_at.replace(tzinfo=timezone.utc)
                if ev.created_at.tzinfo is None
                else ev.created_at
            )
            if ev_ts > anchor:
                changes.append(
                    StateChangeItem(
                        category=ChangeCategory.EVIDENCE_CHANGE,
                        description=f"Evidence added: {ev.description}",
                        timestamp=ev_ts,
                        after_value=ev.description,
                    )
                )

        # 2. Lifecycle & historical events after anchor
        for event in thread.events:
            e_ts = (
                event.timestamp.replace(tzinfo=timezone.utc)
                if event.timestamp.tzinfo is None
                else event.timestamp
            )
            if e_ts > anchor:
                etype = getattr(event, "event_type", event.type)
                if hasattr(etype, "value"):
                    etype = etype.value
                etype_str = str(etype)

                if "EVOLVE" in etype_str:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.GOAL_CHANGE,
                            description=f"Goal updated: {event.description}",
                            timestamp=e_ts,
                            after_value=event.description,
                        )
                    )
                elif "BLOCKER" in etype_str or "RESOLVED" in etype_str:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.BLOCKER_CHANGE,
                            description=f"Blocker status updated: {event.description}",
                            timestamp=e_ts,
                        )
                    )
                elif (
                    "DEFER" in etype_str
                    or "RESUME" in etype_str
                    or "COMPLETE" in etype_str
                    or "ABANDON" in etype_str
                ):
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.STATUS_CHANGE,
                            description=f"Thread lifecycle changed: {event.description}",
                            timestamp=e_ts,
                        )
                    )
                elif "ACTION" in etype_str:
                    changes.append(
                        StateChangeItem(
                            category=ChangeCategory.ACTION_CHANGE,
                            description=f"Action event: {event.description}",
                            timestamp=e_ts,
                        )
                    )

        changes.sort(key=lambda x: x.timestamp)
        has_changes = len(changes) > 0

        if has_changes:
            summary = (
                f"Detected {len(changes)} factual change(s) since {anchor.strftime('%b %d, %Y %H:%M UTC')}: "
                + "; ".join(c.description for c in changes[:3])
            )
        else:
            summary = f"No state changes detected since {anchor.strftime('%b %d, %Y %H:%M UTC')}."

        return ThreadStateDiff(
            thread_id=thread.id,
            since_timestamp=anchor,
            has_changes=has_changes,
            changes=changes,
            summary=summary,
        )
