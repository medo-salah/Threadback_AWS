"""
Deterministic Attention Engine Core for Threadback M14.

Calculates multi-dimensional AttentionScore, normalizes contributing domain signals,
applies the explicit CRITICAL override, and constructs AttentionCandidate models.

Formulas & Invariants:
1. M13 Urgency is consumed as authoritative input (unaltered):
   U = 0.30*priority + 0.25*deadline + 0.20*decay + 0.15*blocker + 0.10*commitments
2. M14 AttentionScore:
   AttentionScore = 0.30*Urgency
                  + 0.20*change
                  + 0.15*commitment_pressure
                  + 0.15*blocker_pressure
                  + 0.10*inactivity
                  + 0.10*evidence_confidence
   Bounded deterministically to [0.0, 1.0].
3. Classification & CRITICAL Override:
   CRITICAL if AttentionScore >= 0.80 OR (Urgency >= 0.85 AND (has_active_blocker OR has_overdue_commitment))
   HIGH: AttentionScore >= 0.65
   MEDIUM: AttentionScore >= 0.40
   LOW: AttentionScore >= 0.20
   NONE: AttentionScore < 0.20
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    AttentionLevel,
    AttentionReasonCode,
    CommitmentStatus,
    ProactiveTriggerType,
    ResumeEligibility,
    SignificanceLevel,
    ThreadStatus,
)
from app.domain.models import (
    AttentionCandidate,
    AttentionDelta,
    IntentConflict,
    IntentHealthSummary,
    IntentThread,
    ProactiveBriefing,
    ProactiveInsightRecord,
    ProactiveTrigger,
    ResumableCandidate,
)
from app.services.analysis_service import (
    DEFAULT_ANALYSIS_REFERENCE_TIME,
    aggregate_evidence,
)
from app.services.change_analysis_service import ChangeAnalysisService
from app.services.conflict_service import ConflictDetectionService
from app.services.intent_radar_service import IntentRadarService
from app.services.resume_service import ResumeEligibilityService
from app.services.why_now_service import WhyNowService

if TYPE_CHECKING:
    from app.domain.models import Commitment, Dependency
    from app.repositories.base import BaseThreadRepository

logger = logging.getLogger(__name__)

# Weight coefficients for M14 AttentionScore
WEIGHT_URGENCY: float = 0.30
WEIGHT_CHANGE: float = 0.20
WEIGHT_COMMITMENT_PRESSURE: float = 0.15
WEIGHT_BLOCKER_PRESSURE: float = 0.15
WEIGHT_INACTIVITY: float = 0.10
WEIGHT_EVIDENCE_CONFIDENCE: float = 0.10

# Threshold constants for AttentionLevel
THRESHOLD_CRITICAL_SCORE: float = 0.80
THRESHOLD_CRITICAL_OVERRIDE_URGENCY: float = 0.85
THRESHOLD_HIGH: float = 0.65
THRESHOLD_MEDIUM: float = 0.40
THRESHOLD_LOW: float = 0.20


def compute_thread_state_fingerprint(
    thread: IntentThread,
    insight_type: str,
) -> str:
    """
    Compute a deterministic SHA-256 hash representing canonical thread state for deduplication (M14).
    Includes:
      - thread ID
      - status
      - priority
      - current goal
      - blockers
      - commitments
      - evidence
      - deferred_until
      - last activity
      - insight type
    """
    blockers_repr = sorted(
        [
            (
                d.id,
                (d.type or "").strip().upper(),
                d.description,
                d.status.value,
                bool(d.blocking),
            )
            for d in thread.active_blockers
        ]
    )
    commitments_repr = sorted(
        [
            (
                c.id,
                c.status.value,
                c.description,
                c.due_at.isoformat() if c.due_at else "",
            )
            for c in thread.commitments
        ]
    )
    evidence_repr = sorted(
        [
            (
                e.id,
                getattr(e.type, "value", str(e.type)),
                e.description,
                round(e.confidence, 4),
            )
            for e in thread.evidence
        ]
    )
    payload = {
        "thread_id": thread.id,
        "status": thread.status.value,
        "priority": thread.priority.value,
        "current_goal": thread.current_goal or "",
        "deferred_until": (
            thread.deferred_until.isoformat() if thread.deferred_until else None
        ),
        "last_activity_at": (
            thread.last_activity_at.isoformat() if thread.last_activity_at else None
        ),
        "insight_type": str(insight_type),
        "blockers": blockers_repr,
        "commitments": commitments_repr,
        "evidence": evidence_repr,
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical_bytes).hexdigest()


class AttentionEngine:
    """
    Deterministic analytical engine for intent attention scoring and candidate ranking (M14).

    Strictly read-only; performs zero mutations, zero external calls, and zero LLM inferences.
    """

    def __init__(
        self,
        radar_service: IntentRadarService | None = None,
        repository: BaseThreadRepository | None = None,
        why_now_service: WhyNowService | None = None,
        change_service: ChangeAnalysisService | None = None,
        resume_service: ResumeEligibilityService | None = None,
        conflict_service: ConflictDetectionService | None = None,
    ) -> None:
        self._radar_service = radar_service or IntentRadarService()
        self._repository = repository
        self._why_now_service = why_now_service or WhyNowService()
        self._change_service = change_service or ChangeAnalysisService(
            repository=repository
        )
        self._resume_service = resume_service or ResumeEligibilityService()
        self._conflict_service = conflict_service or ConflictDetectionService()

    def compute_commitment_pressure(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> tuple[float, list[str], bool]:
        """
        Evaluate commitment pressure based on open commitments and due date proximity.

        Normalization:
          - Overdue open commitment -> 1.0
          - Due within 72 hours -> 0.85
          - Due within 7 days -> 0.60
          - Open commitment with distant / no due date -> 0.30
          - Zero open commitments -> 0.00

        Aggregation Rule:
          Maximum applicable pressure across all open commitments. One severe commitment
          is not diluted by unrelated commitments.

        Returns:
          tuple of (commitment_pressure, supporting_commitment_ids, has_overdue_commitment)
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        open_commitments: list[Commitment] = [
            c for c in thread.commitments if c.status == CommitmentStatus.OPEN
        ]
        if not open_commitments:
            return 0.0, [], False

        has_overdue = False
        scored_commitments: list[tuple[float, str]] = []

        for c in open_commitments:
            if c.due_at is None:
                scored_commitments.append((0.30, c.id))
            else:
                due = c.due_at
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                diff_sec = (due - ref_time).total_seconds()

                if diff_sec < 0:
                    has_overdue = True
                    scored_commitments.append((1.0, c.id))
                elif diff_sec <= 72.0 * 3600.0:
                    scored_commitments.append((0.85, c.id))
                elif diff_sec <= 7.0 * 86400.0:
                    scored_commitments.append((0.60, c.id))
                else:
                    scored_commitments.append((0.30, c.id))

        max_pressure = max(score for score, _ in scored_commitments)
        contributing_ids = [
            c_id for score, c_id in scored_commitments if score == max_pressure
        ]

        return max_pressure, contributing_ids, has_overdue

    def compute_blocker_pressure(
        self,
        thread: IntentThread,
    ) -> tuple[float, list[str], bool]:
        """
        Evaluate blocker pressure based on structured dependency records and waiting state.

        Normalization:
          - Active blocker on named external person (type == 'PERSON') -> 1.0
          - Missing required document (type == 'DOCUMENT') -> 0.8
          - WAITING / passive system-client wait -> 0.4
          - No active blocker and not WAITING -> 0.0

        Aggregation Rule:
          Maximum applicable pressure across all active blockers (or thread WAITING state).
          Preserves all contributing blocker IDs.

        Returns:
          tuple of (blocker_pressure, blocker_ids, has_active_blocker)
        """
        active_blockers: list[Dependency] = thread.active_blockers
        has_active_blocker = len(active_blockers) > 0
        blocker_ids = [d.id for d in active_blockers]

        if not has_active_blocker:
            if thread.status == ThreadStatus.WAITING:
                return 0.4, [], False
            return 0.0, [], False

        scores: list[float] = []
        for d in active_blockers:
            b_type = (d.type or "GENERAL").strip().upper()
            if b_type == "PERSON":
                scores.append(1.0)
            elif b_type == "DOCUMENT":
                scores.append(0.8)
            elif (
                b_type in ("CLIENT", "SYSTEM", "WAITING", "EXTERNAL")
                or thread.status == ThreadStatus.WAITING
            ):
                scores.append(0.4)
            else:
                scores.append(0.4)

        if thread.status == ThreadStatus.WAITING:
            scores.append(0.4)

        max_pressure = max(scores) if scores else 0.0
        return max_pressure, blocker_ids, has_active_blocker

    def compute_inactivity_signal(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> float:
        """
        Evaluate inactivity signal based on elapsed days since thread.last_activity_at.

        Normalization:
          - >= 14 days -> 1.0
          - 7 to <14 days -> 0.75
          - 3 to <7 days -> 0.40
          - < 3 days -> 0.10
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        act_time = thread.last_activity_at
        if act_time.tzinfo is None:
            act_time = act_time.replace(tzinfo=timezone.utc)

        inactive_days = max(0.0, (ref_time - act_time).total_seconds() / 86400.0)

        if inactive_days >= 14.0:
            return 1.0
        elif inactive_days >= 7.0:
            return 0.75
        elif inactive_days >= 3.0:
            return 0.40
        else:
            return 0.10

    def compute_evidence_confidence(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> tuple[float, list[str]]:
        """
        Evaluate evidence confidence using authoritative M4 evidence analysis.

        Normalization:
          - 0.0 if no evidence items exist.
          - [0.0, 1.0] recency-weighted mean from analyze_evidence.
        """
        if not thread.evidence:
            return 0.0, []

        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        evidence_summary = aggregate_evidence(thread.evidence, reference_time=ref_time)
        supporting_ids = [e.id for e in thread.evidence]
        return evidence_summary.confidence, supporting_ids

    def calculate_attention_score(
        self,
        urgency: float,
        change: float,
        commitment_pressure: float,
        blocker_pressure: float,
        inactivity: float,
        evidence_confidence: float,
    ) -> float:
        """
        Compute composite AttentionScore using exact authorized weights:
          0.30 * Urgency
          + 0.20 * change
          + 0.15 * commitment_pressure
          + 0.15 * blocker_pressure
          + 0.10 * inactivity
          + 0.10 * evidence_confidence

        Returns float deterministically clamped to [0.0, 1.0].
        """
        raw_score = (
            WEIGHT_URGENCY * urgency
            + WEIGHT_CHANGE * change
            + WEIGHT_COMMITMENT_PRESSURE * commitment_pressure
            + WEIGHT_BLOCKER_PRESSURE * blocker_pressure
            + WEIGHT_INACTIVITY * inactivity
            + WEIGHT_EVIDENCE_CONFIDENCE * evidence_confidence
        )
        return min(1.0, max(0.0, raw_score))

    def classify_attention_level(
        self,
        attention_score: float,
        urgency_score: float,
        has_active_blocker: bool,
        has_overdue_commitment: bool,
    ) -> AttentionLevel:
        """
        Deterministically assign AttentionLevel with the explicit CRITICAL override.

        CRITICAL if:
          AttentionScore >= 0.80
          OR
          (Urgency >= 0.85 AND (has_active_blocker OR has_overdue_commitment))

        HIGH:    AttentionScore >= 0.65
        MEDIUM:  AttentionScore >= 0.40
        LOW:     AttentionScore >= 0.20
        NONE:    AttentionScore < 0.20
        """
        is_score_critical = attention_score >= THRESHOLD_CRITICAL_SCORE
        is_override_critical = (
            urgency_score >= THRESHOLD_CRITICAL_OVERRIDE_URGENCY
            and (has_active_blocker or has_overdue_commitment)
        )

        if is_score_critical or is_override_critical:
            return AttentionLevel.CRITICAL
        elif attention_score >= THRESHOLD_HIGH:
            return AttentionLevel.HIGH
        elif attention_score >= THRESHOLD_MEDIUM:
            return AttentionLevel.MEDIUM
        elif attention_score >= THRESHOLD_LOW:
            return AttentionLevel.LOW
        else:
            return AttentionLevel.NONE

    def evaluate_thread(
        self,
        thread: IntentThread,
        change_signal: float = 0.0,
        reference_time: datetime | None = None,
    ) -> AttentionCandidate:
        """
        Evaluate a single IntentThread into an AttentionCandidate.

        Consumes authoritative M13 urgency and computes all normalized M14 signals.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # 1. Authoritative M13 Urgency consumption
        radar_item = self._radar_service.compute_radar_item(
            thread, reference_time=ref_time
        )
        urgency = radar_item.urgency_score

        # 2. Normalized M14 signals
        norm_change = min(1.0, max(0.0, change_signal))
        com_pressure, com_ids, has_overdue = self.compute_commitment_pressure(
            thread, reference_time=ref_time
        )
        blk_pressure, blk_ids, has_blocker = self.compute_blocker_pressure(thread)
        inact_signal = self.compute_inactivity_signal(thread, reference_time=ref_time)
        evi_confidence, evi_ids = self.compute_evidence_confidence(
            thread, reference_time=ref_time
        )

        # 3. Calculate AttentionScore
        attention_score = self.calculate_attention_score(
            urgency=urgency,
            change=norm_change,
            commitment_pressure=com_pressure,
            blocker_pressure=blk_pressure,
            inactivity=inact_signal,
            evidence_confidence=evi_confidence,
        )

        # 4. Classify AttentionLevel (with CRITICAL override)
        attention_level = self.classify_attention_level(
            attention_score=attention_score,
            urgency_score=urgency,
            has_active_blocker=has_blocker,
            has_overdue_commitment=has_overdue,
        )

        # 5. Extract deterministic reason codes
        reason_codes: list[AttentionReasonCode] = []
        explanation_parts: list[str] = []

        if has_overdue:
            reason_codes.append(AttentionReasonCode.DEADLINE_OVERDUE)
            reason_codes.append(AttentionReasonCode.COMMITMENT_OVERDUE)
            explanation_parts.append("Has overdue commitment")
        elif com_pressure == 0.85:
            reason_codes.append(AttentionReasonCode.DEADLINE_APPROACHING)
            explanation_parts.append("Commitment deadline approaching within 72 hours")

        if com_pressure > 0.0:
            reason_codes.append(AttentionReasonCode.COMMITMENT_DUE)

        if has_blocker:
            reason_codes.append(AttentionReasonCode.BLOCKER_PRESENT)
            explanation_parts.append(f"Blocked by {len(blk_ids)} active blocker(s)")
        elif thread.status == ThreadStatus.WAITING:
            explanation_parts.append("In waiting status")

        if inact_signal == 1.0:
            reason_codes.append(AttentionReasonCode.INTENT_STALE)
            reason_codes.append(AttentionReasonCode.LONG_INACTIVITY)
            explanation_parts.append("Inactive for 14+ days (stale)")
        elif inact_signal == 0.75:
            reason_codes.append(AttentionReasonCode.INTENT_DECAYING)
            reason_codes.append(AttentionReasonCode.LONG_INACTIVITY)
            explanation_parts.append("Inactive for 7-14 days (decaying)")

        if norm_change >= 0.50:
            reason_codes.append(AttentionReasonCode.IMPORTANT_CHANGE)
            explanation_parts.append("Significant recent state change")

        if getattr(thread, "evolutions", None):
            reason_codes.append(AttentionReasonCode.GOAL_EVOLVED)

        if thread.evidence:
            reason_codes.append(AttentionReasonCode.NEW_EVIDENCE)

        if not explanation_parts:
            explanation_parts.append(
                f"Urgency score {round(urgency, 2)}, status {thread.status.value}"
            )

        explanation = "; ".join(explanation_parts)

        # 6. Action summary recommendation
        rec_summary: str | None = None
        if has_blocker and thread.active_blockers:
            rec_summary = (
                f"Review active blocker: {thread.active_blockers[0].description}"
            )
        elif has_overdue and com_ids:
            rec_summary = "Address overdue commitment"
        elif thread.commitments:
            rec_summary = f"Review commitments for {thread.title}"

        return AttentionCandidate(
            thread_id=thread.id,
            thread_title=thread.title,
            attention_level=attention_level,
            attention_score=round(attention_score, 4),
            urgency_score=round(urgency, 4),
            reason_codes=reason_codes,
            human_readable_explanation=explanation,
            supporting_evidence_ids=evi_ids,
            supporting_commitment_ids=com_ids,
            blocker_ids=blk_ids,
            recommended_action_summary=rec_summary,
            generated_at=ref_time,
        )

    def evaluate_threads(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[AttentionCandidate]:
        """
        Evaluate multiple IntentThreads into ranked AttentionCandidates.

        Ranks deterministically by:
          1. attention_score DESC
          2. urgency_score DESC
          3. thread_id ASC (tie-breaker)
        """
        candidates = [
            self.evaluate_thread(t, reference_time=reference_time) for t in threads
        ]
        candidates.sort(
            key=lambda c: (-c.attention_score, -c.urgency_score, c.thread_id)
        )
        return candidates

    def compute_fingerprint(self, thread: IntentThread, insight_type: str) -> str:
        """Compute state fingerprint for a thread and insight type."""
        return compute_thread_state_fingerprint(thread, insight_type)

    def is_insight_duplicate(
        self, thread_id: str, insight_type: str, state_fingerprint: str
    ) -> bool:
        """Check if an insight for this thread, type, and state fingerprint already exists."""
        if self._repository is None:
            return False
        return self._repository.is_insight_duplicate(
            thread_id=thread_id,
            insight_type=insight_type,
            state_fingerprint=state_fingerprint,
        )

    def record_insight(self, record: ProactiveInsightRecord) -> None:
        """Persist a proactive insight record for deduplication."""
        if self._repository is not None:
            self._repository.record_proactive_insight(record)

    def analyze_thread_changes(
        self,
        thread: IntentThread,
        since_timestamp: datetime | None = None,
        conversation_id: str | None = None,
        reference_time: datetime | None = None,
    ) -> AttentionDelta:
        """Compute AttentionDelta using the 4-tier anchor comparison."""
        return self._change_service.analyze_changes(
            thread,
            since_timestamp=since_timestamp,
            conversation_id=conversation_id,
            reference_time=reference_time,
        )

    def evaluate_thread_resume(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> ResumableCandidate:
        """Evaluate resume eligibility using the M14 decision table."""
        return self._resume_service.evaluate_thread(
            thread, reference_time=reference_time
        )

    def detect_cross_thread_conflicts(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[IntentConflict]:
        """Detect conservative cross-thread conflicts."""
        return self._conflict_service.detect_conflicts(
            threads, reference_time=reference_time
        )

    def generate_health_summary(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> IntentHealthSummary:
        """
        Aggregate deterministic landscape metrics across all active intent threads.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Active threads are those not COMPLETED or ABANDONED
        active_statuses = {
            ThreadStatus.DISCOVERED,
            ThreadStatus.ACTIVE,
            ThreadStatus.BLOCKED,
            ThreadStatus.WAITING,
            ThreadStatus.DEFERRED,
        }
        active_threads = [t for t in threads if t.status in active_statuses]
        candidates = self.evaluate_threads(active_threads, reference_time=ref_time)
        resumable_candidates = [
            self.evaluate_thread_resume(t, reference_time=ref_time)
            for t in active_threads
            if t.status == ThreadStatus.DEFERRED
        ]
        conflicts = self.detect_cross_thread_conflicts(
            active_threads, reference_time=ref_time
        )

        healthy_count = sum(
            1
            for c in candidates
            if c.attention_level in (AttentionLevel.NONE, AttentionLevel.LOW)
        )
        attention_count = sum(
            1
            for c in candidates
            if c.attention_level
            in (AttentionLevel.MEDIUM, AttentionLevel.HIGH, AttentionLevel.CRITICAL)
        )
        decaying_count = sum(
            1
            for c in candidates
            if AttentionReasonCode.INTENT_DECAYING in c.reason_codes
        )
        stale_count = sum(
            1 for c in candidates if AttentionReasonCode.INTENT_STALE in c.reason_codes
        )
        blocked_count = sum(
            1
            for c in candidates
            if AttentionReasonCode.BLOCKER_PRESENT in c.reason_codes
        )
        deferred_count = sum(
            1 for t in active_threads if t.status == ThreadStatus.DEFERRED
        )
        resumable_count = sum(
            1
            for r in resumable_candidates
            if r.eligibility == ResumeEligibility.RESUMABLE
        )

        return IntentHealthSummary(
            total_active_threads=len(active_threads),
            healthy_threads=healthy_count,
            attention_threads=attention_count,
            decaying_threads=decaying_count,
            stale_threads=stale_count,
            blocked_threads=blocked_count,
            deferred_threads=deferred_count,
            resumable_threads=resumable_count,
            conflicts_count=len(conflicts),
            top_attention_candidates=candidates[:5],
            generated_at=ref_time,
        )

    def generate_briefing(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
        conversation_id: str | None = None,
    ) -> ProactiveBriefing:
        """
        Synthesize the proactive executive briefing prioritized by attention and risk.

        Prioritizes:
          1. CRITICAL attention
          2. HIGH attention
          3. Important changes
          4. Blockers requiring attention
          5. Overdue commitments
          6. Resumable threads
          7. Meaningful conflicts
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        active_statuses = {
            ThreadStatus.DISCOVERED,
            ThreadStatus.ACTIVE,
            ThreadStatus.BLOCKED,
            ThreadStatus.WAITING,
            ThreadStatus.DEFERRED,
        }
        active_threads = [t for t in threads if t.status in active_statuses]

        candidates = self.evaluate_threads(active_threads, reference_time=ref_time)
        health_summary = self.generate_health_summary(threads, reference_time=ref_time)

        # Changes
        deltas = [
            self.analyze_thread_changes(
                t,
                conversation_id=conversation_id,
                reference_time=ref_time,
            )
            for t in active_threads
        ]
        # Filter changes with significance > 0, sort by significance_score DESC
        meaningful_deltas = [d for d in deltas if d.significance_score > 0.0]
        meaningful_deltas.sort(key=lambda d: (-d.significance_score, d.thread_id))

        # Resumables
        resumable_candidates = [
            self.evaluate_thread_resume(t, reference_time=ref_time)
            for t in active_threads
            if t.status == ThreadStatus.DEFERRED
        ]
        eligible_resumables = [
            r
            for r in resumable_candidates
            if r.eligibility == ResumeEligibility.RESUMABLE
        ]

        # Conflicts
        conflicts = self.detect_cross_thread_conflicts(
            active_threads, reference_time=ref_time
        )

        # Top attention candidates (CRITICAL and HIGH prioritized, top 3)
        top_candidates = [
            c
            for c in candidates
            if c.attention_level in (AttentionLevel.CRITICAL, AttentionLevel.HIGH)
        ][:3]
        if not top_candidates and candidates:
            # If no high/critical, include highest scoring candidate
            top_candidates = candidates[:1]

        # Natural language synthesis for Alexa+ conversational output
        briefing_sentences: list[str] = []

        # Count primary noteworthy items
        noteworthy_count = (
            len(top_candidates)
            + (1 if eligible_resumables else 0)
            + (1 if conflicts else 0)
        )

        if noteworthy_count == 0:
            briefing_text = (
                "You have no urgent items requiring attention right now. "
                "All your active intentions are healthy."
            )
        else:
            briefing_sentences.append(
                f"You have {noteworthy_count} things worth attention."
            )

            # Top candidates description
            for c in top_candidates:
                briefing_sentences.append(
                    f"Your {c.thread_title} thread {c.human_readable_explanation.lower()}."
                )

            # Resumable description
            if eligible_resumables:
                top_res = eligible_resumables[0]
                briefing_sentences.append(
                    f"Your {top_res.thread_title} thread is now resumable: {top_res.reason}."
                )

            # Conflict description
            if conflicts:
                top_conf = conflicts[0]
                briefing_sentences.append(
                    f"You also have a {top_conf.conflict_type.value.lower().replace('_', ' ')}: {top_conf.explanation}"
                )

            briefing_text = " ".join(briefing_sentences)

        return ProactiveBriefing(
            top_attention=top_candidates,
            top_changes=meaningful_deltas[:3],
            top_resumable=eligible_resumables[:2],
            top_conflicts=conflicts[:2],
            health_summary=health_summary,
            briefing_text=briefing_text,
            generated_at=ref_time,
        )

    def detect_triggers(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
        conversation_id: str | None = None,
    ) -> list[ProactiveTrigger]:
        """
        Evaluate and return internal detection records for triggered proactive conditions.

        Does not send notifications or mutate lifecycle state.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        triggers: list[ProactiveTrigger] = []

        # 1. Attention candidates triggers
        candidates = self.evaluate_threads(threads, reference_time=ref_time)
        for c in candidates:
            if c.attention_level in (
                AttentionLevel.CRITICAL,
                AttentionLevel.HIGH,
                AttentionLevel.MEDIUM,
            ):
                triggers.append(
                    ProactiveTrigger(
                        trigger_id=f"trig-att-{c.thread_id}-{int(ref_time.timestamp())}",
                        trigger_type=ProactiveTriggerType.ATTENTION_THRESHOLD_CROSSED,
                        thread_id=c.thread_id,
                        reason=f"Attention level reached {c.attention_level.value} with score {c.attention_score}",
                        candidate_id=c.thread_id,
                        evaluated_at=ref_time,
                    )
                )
            if AttentionReasonCode.DEADLINE_APPROACHING in c.reason_codes:
                triggers.append(
                    ProactiveTrigger(
                        trigger_id=f"trig-dl-{c.thread_id}-{int(ref_time.timestamp())}",
                        trigger_type=ProactiveTriggerType.DEADLINE_APPROACHING,
                        thread_id=c.thread_id,
                        reason="Commitment deadline is approaching within 72 hours",
                        candidate_id=c.thread_id,
                        evaluated_at=ref_time,
                    )
                )
            if (
                AttentionReasonCode.INTENT_DECAYING in c.reason_codes
                or AttentionReasonCode.INTENT_STALE in c.reason_codes
            ):
                triggers.append(
                    ProactiveTrigger(
                        trigger_id=f"trig-decay-{c.thread_id}-{int(ref_time.timestamp())}",
                        trigger_type=ProactiveTriggerType.INTENT_DECAYED,
                        thread_id=c.thread_id,
                        reason="Intent is becoming stale or decaying due to inactivity",
                        candidate_id=c.thread_id,
                        evaluated_at=ref_time,
                    )
                )

        # 2. Resumables triggers
        for t in threads:
            if t.status == ThreadStatus.DEFERRED:
                res = self.evaluate_thread_resume(t, reference_time=ref_time)
                if res.eligibility == ResumeEligibility.RESUMABLE:
                    triggers.append(
                        ProactiveTrigger(
                            trigger_id=f"trig-resume-{t.id}-{int(ref_time.timestamp())}",
                            trigger_type=ProactiveTriggerType.THREAD_BECAME_RESUMABLE,
                            thread_id=t.id,
                            reason=f"Deferred thread is eligible to resume: {res.reason}",
                            candidate_id=t.id,
                            evaluated_at=ref_time,
                        )
                    )

        # 3. Change triggers
        for t in threads:
            delta = self.analyze_thread_changes(
                t, conversation_id=conversation_id, reference_time=ref_time
            )
            if delta.significance_level == SignificanceLevel.HIGH:
                triggers.append(
                    ProactiveTrigger(
                        trigger_id=f"trig-change-{t.id}-{int(ref_time.timestamp())}",
                        trigger_type=ProactiveTriggerType.SIGNIFICANT_CHANGE,
                        thread_id=t.id,
                        reason=f"High significance changes detected ({len(delta.changes)} change items)",
                        candidate_id=t.id,
                        evaluated_at=ref_time,
                    )
                )
            # Check blocker resolved change
            for ch in delta.changes:
                if "blocker resolved" in ch.description.lower():
                    triggers.append(
                        ProactiveTrigger(
                            trigger_id=f"trig-unblk-{t.id}-{int(ref_time.timestamp())}",
                            trigger_type=ProactiveTriggerType.BLOCKER_RESOLVED,
                            thread_id=t.id,
                            reason=f"Blocker was resolved: {ch.description}",
                            candidate_id=t.id,
                            evaluated_at=ref_time,
                        )
                    )

        # 4. Conflict triggers
        conflicts = self.detect_cross_thread_conflicts(threads, reference_time=ref_time)
        for conf in conflicts:
            triggers.append(
                ProactiveTrigger(
                    trigger_id=f"trig-conf-{conf.conflict_id}",
                    trigger_type=ProactiveTriggerType.CONFLICT_DETECTED,
                    thread_id=conf.thread_a_id,
                    reason=conf.explanation,
                    candidate_id=conf.conflict_id,
                    evaluated_at=ref_time,
                )
            )

        return triggers
