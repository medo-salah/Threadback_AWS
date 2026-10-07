"""
Deterministic Resume Eligibility Service for Threadback M14.

Applies the approved M14 decision table to determine whether a deferred intent
thread is eligible for resumption.

Decision Table:
- RESUMABLE:
    * deferred_until passed + no blockers
    * deferred_until passed + blocker resolved / unblocking evidence
    * not passed + new unblocking evidence
    * indefinite defer + no blockers + new evidence
- NOT_RESUMABLE:
    * deferred_until passed + blockers remain + no unblocking evidence
    * not passed + no unblocking evidence
    * indefinite defer + blockers + no evidence
    * any non-DEFERRED thread
- UNKNOWN:
    * where evidence / state is genuinely insufficient.

Invariants:
- Strictly read-only; NEVER automatically mutates thread lifecycle state.
- Resumption requires user confirmation via prepare_action -> confirmation -> execute_action.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.domain.enums import (
    ResumeEligibility,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import IntentThread, ResumableCandidate
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

logger = logging.getLogger(__name__)


class ResumeEligibilityService:
    """Deterministic evaluation of resumption eligibility for deferred threads."""

    def evaluate_thread(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> ResumableCandidate:
        """
        Evaluate an IntentThread according to the M14 resume decision table.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        eval_time = ref_time
        supporting_blocker_ids = [b.id for b in thread.active_blockers]
        supporting_evidence_ids: list[str] = []
        supporting_event_ids: list[str] = []

        # Rule 1: Non-DEFERRED thread is always NOT_RESUMABLE
        if thread.status != ThreadStatus.DEFERRED:
            return ResumableCandidate(
                thread_id=thread.id,
                thread_title=thread.title,
                eligibility=ResumeEligibility.NOT_RESUMABLE,
                reason=f"Thread is not in DEFERRED status (currently {thread.status.value})",
                supporting_blocker_ids=supporting_blocker_ids,
                supporting_evidence_ids=[],
                supporting_event_ids=[],
                deferred_until=thread.deferred_until,
                evaluated_at=eval_time,
            )

        # Find deferral timestamp if recorded in events
        defer_timestamp: datetime | None = None
        for ev in thread.events:
            etype = getattr(ev, "event_type", ev.type)
            if (
                etype == ThreadEventType.THREAD_DEFERRED
                or getattr(etype, "value", str(etype)) == "THREAD_DEFERRED"
                or "DEFER" in str(etype)
            ):
                defer_timestamp = ev.timestamp
                supporting_event_ids.append(ev.id)

        has_blockers = len(thread.active_blockers) > 0

        # Detect new unblocking evidence or blocker resolution events
        has_unblocking_evidence = False
        for ev in thread.evidence:
            ev_ts = ev.created_at
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            # Evidence added after deferral or explicitly high-confidence
            if defer_timestamp is not None:
                d_ts = (
                    defer_timestamp.replace(tzinfo=timezone.utc)
                    if defer_timestamp.tzinfo is None
                    else defer_timestamp
                )
                if ev_ts >= d_ts:
                    has_unblocking_evidence = True
                    supporting_evidence_ids.append(ev.id)
            elif ev.confidence >= 0.75:
                has_unblocking_evidence = True
                supporting_evidence_ids.append(ev.id)

        # Also check for blocker resolved events
        for event in thread.events:
            etype = getattr(event, "event_type", event.type)
            etype_str = getattr(etype, "value", str(etype))
            if "RESOLVED" in etype_str or "UNBLOCKED" in etype_str:
                has_unblocking_evidence = True
                supporting_event_ids.append(event.id)

        deferred_until = thread.deferred_until
        is_indefinite = deferred_until is None

        if not is_indefinite:
            d_until = (
                deferred_until.replace(tzinfo=timezone.utc)
                if deferred_until.tzinfo is None
                else deferred_until
            )
            passed = d_until <= ref_time

            if passed:
                if not has_blockers:
                    # deferred_until passed + no blockers -> RESUMABLE
                    return ResumableCandidate(
                        thread_id=thread.id,
                        thread_title=thread.title,
                        eligibility=ResumeEligibility.RESUMABLE,
                        reason="Deferral period has elapsed and there are no active blockers",
                        supporting_blocker_ids=[],
                        supporting_evidence_ids=supporting_evidence_ids,
                        supporting_event_ids=supporting_event_ids,
                        deferred_until=deferred_until,
                        evaluated_at=eval_time,
                    )
                elif has_unblocking_evidence:
                    # deferred_until passed + blocker resolved/unblocking evidence -> RESUMABLE
                    return ResumableCandidate(
                        thread_id=thread.id,
                        thread_title=thread.title,
                        eligibility=ResumeEligibility.RESUMABLE,
                        reason="Deferral period has elapsed and unblocking evidence has been provided",
                        supporting_blocker_ids=supporting_blocker_ids,
                        supporting_evidence_ids=supporting_evidence_ids,
                        supporting_event_ids=supporting_event_ids,
                        deferred_until=deferred_until,
                        evaluated_at=eval_time,
                    )
                else:
                    # deferred_until passed + blockers remain + no unblocking evidence -> NOT_RESUMABLE
                    return ResumableCandidate(
                        thread_id=thread.id,
                        thread_title=thread.title,
                        eligibility=ResumeEligibility.NOT_RESUMABLE,
                        reason="Deferral period has elapsed but active blockers remain without unblocking evidence",
                        supporting_blocker_ids=supporting_blocker_ids,
                        supporting_evidence_ids=[],
                        supporting_event_ids=supporting_event_ids,
                        deferred_until=deferred_until,
                        evaluated_at=eval_time,
                    )
            else:
                # deferred_until NOT passed
                if has_unblocking_evidence:
                    # not passed + new unblocking evidence -> RESUMABLE
                    return ResumableCandidate(
                        thread_id=thread.id,
                        thread_title=thread.title,
                        eligibility=ResumeEligibility.RESUMABLE,
                        reason="Deferral period has not yet elapsed, but unblocking evidence was provided",
                        supporting_blocker_ids=supporting_blocker_ids,
                        supporting_evidence_ids=supporting_evidence_ids,
                        supporting_event_ids=supporting_event_ids,
                        deferred_until=deferred_until,
                        evaluated_at=eval_time,
                    )
                else:
                    # not passed + no unblocking evidence -> NOT_RESUMABLE
                    return ResumableCandidate(
                        thread_id=thread.id,
                        thread_title=thread.title,
                        eligibility=ResumeEligibility.NOT_RESUMABLE,
                        reason=f"Deferral period active until {d_until.strftime('%b %d, %Y %H:%M UTC')}",
                        supporting_blocker_ids=supporting_blocker_ids,
                        supporting_evidence_ids=[],
                        supporting_event_ids=supporting_event_ids,
                        deferred_until=deferred_until,
                        evaluated_at=eval_time,
                    )
        else:
            # Indefinite defer
            has_evidence = len(thread.evidence) > 0 or has_unblocking_evidence
            if not has_blockers and has_evidence:
                # indefinite defer + no blockers + new evidence -> RESUMABLE
                return ResumableCandidate(
                    thread_id=thread.id,
                    thread_title=thread.title,
                    eligibility=ResumeEligibility.RESUMABLE,
                    reason="Indefinitely deferred thread has no active blockers and relevant evidence exists",
                    supporting_blocker_ids=[],
                    supporting_evidence_ids=[e.id for e in thread.evidence],
                    supporting_event_ids=supporting_event_ids,
                    deferred_until=None,
                    evaluated_at=eval_time,
                )
            elif has_blockers and not has_evidence:
                # indefinite defer + blockers + no evidence -> NOT_RESUMABLE
                return ResumableCandidate(
                    thread_id=thread.id,
                    thread_title=thread.title,
                    eligibility=ResumeEligibility.NOT_RESUMABLE,
                    reason="Indefinitely deferred thread has unresolved blockers and no new evidence",
                    supporting_blocker_ids=supporting_blocker_ids,
                    supporting_evidence_ids=[],
                    supporting_event_ids=supporting_event_ids,
                    deferred_until=None,
                    evaluated_at=eval_time,
                )
            elif not has_blockers and not has_evidence:
                # Genuine insufficient state -> UNKNOWN
                return ResumableCandidate(
                    thread_id=thread.id,
                    thread_title=thread.title,
                    eligibility=ResumeEligibility.UNKNOWN,
                    reason="Indefinitely deferred thread has no blockers but insufficient evidence to confirm readiness",
                    supporting_blocker_ids=[],
                    supporting_evidence_ids=[],
                    supporting_event_ids=supporting_event_ids,
                    deferred_until=None,
                    evaluated_at=eval_time,
                )
            else:
                return ResumableCandidate(
                    thread_id=thread.id,
                    thread_title=thread.title,
                    eligibility=ResumeEligibility.UNKNOWN,
                    reason="Insufficient evidence to evaluate resume eligibility",
                    supporting_blocker_ids=supporting_blocker_ids,
                    supporting_evidence_ids=[],
                    supporting_event_ids=supporting_event_ids,
                    deferred_until=None,
                    evaluated_at=eval_time,
                )

    def evaluate_threads(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[ResumableCandidate]:
        """
        Evaluate multiple threads and return candidates.
        """
        return [self.evaluate_thread(t, reference_time=reference_time) for t in threads]
