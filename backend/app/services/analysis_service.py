"""
Analysis service for Threadback M4.

Provides deterministic thread analysis using only structured domain data.
No LLM, no external APIs, no database, no random values.

Architecture
------------
IntentThread
    ↓
Evidence aggregation
    ↓
Commitment analysis
    ↓
Blocker analysis
    ↓
Attention calculation
    ↓
Confidence calculation
    ↓
ThreadAnalysis

Formulas & Rules
----------------
See docs/analysis-engine.md for full specification.

Deterministic Reference Time:
    DEFAULT_ANALYSIS_REFERENCE_TIME = 2026-09-28T15:00:00Z.
    Analysis does not rely directly on datetime.now().
    RECENT_ACTIVITY is true only when the most recent event is <= 7 days before
    the reference time.

Evidence Staleness:
    - Individual evidence age: age_days = (reference_time - created_at) in days.
      An item is individually stale if age_days > 30.0 days.
    - has_stale_evidence: True if at least one evidence item is stale.
    - is_stale: True if all evidence items are stale (entire set is stale) or empty.

Evidence Confidence (aggregate):
    If no evidence: 0.0
    Otherwise: weighted_mean(evidence_confidence, recency_weight)
    recency_weight = 0.5 + 0.5 * recency_factor
    recency_factor = max(0.0, 1.0 - age_days / 90.0)
    Result is clamped to [0.0, 1.0].

Confidence Bands (M0):
    0.90 – 1.00  →  STRONG
    0.75 – 0.89  →  GOOD
    0.50 – 0.74  →  UNCERTAIN
    < 0.50       →  WEAK

Attention Score:
    P = 0.30 * priority_score
      + 0.25 * blocker_score
      + 0.20 * commitment_score
      + 0.15 * recency_score
      + 0.10 * evidence_score
    Clamped to [0.0, 1.0].

    Attention Level:
        >= 0.65  →  HIGH
        >= 0.35  →  MEDIUM
        < 0.35   →  LOW

Domain Terminology Note:
    M3 thread status is ThreadStatus.WAITING (not WAITING_ON_DEPENDENCY).
    WAITING_ON_DEPENDENCY is an unfinished-reason classification (UnfinishedReason).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    AttentionLevel,
    CommitmentStatus,
    ConfidenceBand,
    DependencyStatus,
    Priority,
    ThreadStatus,
    UnfinishedReason,
)
from app.domain.models import (
    AttentionSignal,
    BlockerDetail,
    EvidenceSummary,
    ThreadAnalysis,
)

if TYPE_CHECKING:
    from app.domain.models import Evidence, IntentThread

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Deterministic analysis reference time anchor (fixed UTC timestamp matching demo dataset anchor)
DEFAULT_ANALYSIS_REFERENCE_TIME: datetime = datetime(
    2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc
)

# Evidence staleness threshold (days)
STALE_THRESHOLD_DAYS: float = 30.0

# Evidence sufficiency thresholds
MIN_EVIDENCE_COUNT: int = 2
MIN_AVERAGE_CONFIDENCE: float = 0.50

# Recency decay window (days) — evidence older than this has zero recency bonus
RECENCY_DECAY_DAYS: float = 90.0

# Attention weights — documented and explainable
# P = w_d * D + w_b * B + w_c * C + w_r * R + w_e * E
ATTENTION_WEIGHT_PRIORITY: float = 0.30
ATTENTION_WEIGHT_BLOCKER: float = 0.25
ATTENTION_WEIGHT_COMMITMENT: float = 0.20
ATTENTION_WEIGHT_RECENCY: float = 0.15
ATTENTION_WEIGHT_EVIDENCE: float = 0.10

# Attention level thresholds
ATTENTION_HIGH_THRESHOLD: float = 0.65
ATTENTION_MEDIUM_THRESHOLD: float = 0.35

# Priority numeric mapping
PRIORITY_SCORES: dict[Priority, float] = {
    Priority.HIGH: 1.0,
    Priority.MEDIUM: 0.5,
    Priority.LOW: 0.2,
}


# ---------------------------------------------------------------------------
# Confidence Band Classification
# ---------------------------------------------------------------------------


def classify_confidence(confidence: float) -> ConfidenceBand:
    """
    Classify a confidence value into its M0-defined band.

    Args:
        confidence: Value between 0.0 and 1.0.

    Returns:
        ConfidenceBand enum value.
    """
    if confidence >= 0.90:
        return ConfidenceBand.STRONG
    if confidence >= 0.75:
        return ConfidenceBand.GOOD
    if confidence >= 0.50:
        return ConfidenceBand.UNCERTAIN
    return ConfidenceBand.WEAK


# ---------------------------------------------------------------------------
# Evidence Aggregation
# ---------------------------------------------------------------------------


def _compute_recency_factor(
    evidence_created_at: datetime, reference_time: datetime
) -> float:
    """
    Compute recency factor for a piece of evidence.

    Returns a value between 0.0 (very old) and 1.0 (very recent).
    Evidence at or after the reference time gets 1.0.
    Evidence older than RECENCY_DECAY_DAYS gets 0.0.
    """
    if evidence_created_at >= reference_time:
        return 1.0
    age_days = (reference_time - evidence_created_at).total_seconds() / 86400.0
    return max(0.0, 1.0 - age_days / RECENCY_DECAY_DAYS)


def aggregate_evidence(
    evidence_items: list[Evidence],
    reference_time: datetime | None = None,
) -> EvidenceSummary:
    """
    Aggregate evidence statistics for a thread.

    Distinguishes:
        - age of individual evidence: age_days = (ref_time - e.created_at) in days.
          An item is individually stale if age_days > STALE_THRESHOLD_DAYS (30 days).
        - contains stale evidence: has_stale_evidence = True if at least one item is stale.
        - entire set is stale: is_stale = True if all items are stale (or if total == 0).

    Evidence confidence formula:
        weighted_mean(confidence_i * recency_weight_i)
        where recency_weight_i = 0.5 + 0.5 * recency_factor_i
        and recency_factor_i = max(0.0, 1.0 - age_days / 90.0)

    This weights recent evidence more heavily while ensuring that old
    evidence still contributes (minimum weight = 0.5).

    Args:
        evidence_items: List of Evidence domain objects.
        reference_time: The reference timestamp for recency and staleness calculations.
                        Defaults to DEFAULT_ANALYSIS_REFERENCE_TIME.

    Returns:
        EvidenceSummary with all aggregated statistics.
    """
    ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
    total = len(evidence_items)

    if total == 0:
        return EvidenceSummary(
            total=0,
            by_type={},
            strongest_evidence_ids=[],
            weakest_evidence_ids=[],
            average_confidence=0.0,
            confidence=0.0,
            confidence_band=ConfidenceBand.WEAK,
            is_sufficient=False,
            is_weak=True,
            is_stale=True,
            has_stale_evidence=False,
            stale_evidence_ids=[],
            most_recent_evidence_id=None,
            supporting_evidence_ids=[],
        )

    # Count by type
    by_type: dict[str, int] = {}
    for e in evidence_items:
        by_type[e.type.value] = by_type.get(e.type.value, 0) + 1

    # Sort by confidence for strongest/weakest
    sorted_by_confidence = sorted(
        evidence_items, key=lambda e: e.confidence, reverse=True
    )
    strongest_ids = [e.id for e in sorted_by_confidence[:3]]
    weakest_ids = [e.id for e in sorted_by_confidence[-3:] if e.confidence < 0.75]

    # Simple average confidence
    average_confidence = sum(e.confidence for e in evidence_items) / total

    # Weighted aggregate confidence (recency-weighted)
    weighted_sum = 0.0
    weight_total = 0.0
    for e in evidence_items:
        recency_factor = _compute_recency_factor(e.created_at, ref_time)
        weight = 0.5 + 0.5 * recency_factor
        weighted_sum += e.confidence * weight
        weight_total += weight

    aggregate_confidence = weighted_sum / weight_total if weight_total > 0 else 0.0
    aggregate_confidence = max(0.0, min(1.0, aggregate_confidence))

    # Most recent evidence
    most_recent = max(evidence_items, key=lambda e: e.created_at)

    # Staleness evaluation:
    # 1. Individual evidence item age and identification
    stale_items = [
        e
        for e in evidence_items
        if (ref_time - e.created_at).total_seconds() / 86400.0 > STALE_THRESHOLD_DAYS
    ]
    stale_evidence_ids = [e.id for e in stale_items]

    # 2. Whether evidence set contains any stale evidence
    has_stale_evidence = len(stale_items) > 0

    # 3. Whether the entire evidence set is stale (all items older than 30 days)
    is_stale = len(stale_items) == total

    # Sufficiency
    is_sufficient = (
        total >= MIN_EVIDENCE_COUNT and average_confidence >= MIN_AVERAGE_CONFIDENCE
    )

    # Weakness
    is_weak = aggregate_confidence < 0.50

    # Supporting evidence IDs (all evidence that supports the current interpretation)
    supporting_ids = [e.id for e in evidence_items]

    return EvidenceSummary(
        total=total,
        by_type=by_type,
        strongest_evidence_ids=strongest_ids,
        weakest_evidence_ids=weakest_ids,
        average_confidence=round(average_confidence, 4),
        confidence=round(aggregate_confidence, 4),
        confidence_band=classify_confidence(aggregate_confidence),
        is_sufficient=is_sufficient,
        is_weak=is_weak,
        is_stale=is_stale,
        has_stale_evidence=has_stale_evidence,
        stale_evidence_ids=stale_evidence_ids,
        most_recent_evidence_id=most_recent.id,
        supporting_evidence_ids=supporting_ids,
    )


# ---------------------------------------------------------------------------
# Unfinished Reason Classification
# ---------------------------------------------------------------------------


def classify_unfinished_reasons(
    thread: IntentThread,
    reference_time: datetime | None = None,
) -> list[UnfinishedReason]:
    """
    Determine why a thread remains unfinished using deterministic domain signals.

    Only returns reasons supported by actual structured thread data.
    A thread may have multiple simultaneous reasons.

    Rules:
        OPEN_COMMITMENT: Thread has at least one commitment with status=OPEN.
        ACTIVE_BLOCKER: Thread has at least one dependency with blocking=True and status=OPEN.
        WAITING_ON_DEPENDENCY: Thread lifecycle status is WAITING (from ThreadStatus.WAITING)
                               and has open dependencies.
        RECENT_ACTIVITY: Most recent event is <= 7 days before the explicit reference_time.
        MISSING_REQUIRED_EVIDENCE: Thread has fewer than MIN_EVIDENCE_COUNT evidence items.

    Args:
        thread: The IntentThread to classify.
        reference_time: Reference timestamp for recency evaluation.
                        Defaults to DEFAULT_ANALYSIS_REFERENCE_TIME.
    """
    ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
    reasons: list[UnfinishedReason] = []

    # OPEN_COMMITMENT
    open_commitments = [
        c for c in thread.commitments if c.status == CommitmentStatus.OPEN
    ]
    if open_commitments:
        reasons.append(UnfinishedReason.OPEN_COMMITMENT)

    # ACTIVE_BLOCKER
    active_blockers = thread.active_blockers
    if active_blockers:
        reasons.append(UnfinishedReason.ACTIVE_BLOCKER)

    # WAITING_ON_DEPENDENCY (Unfinished Reason concept; thread lifecycle status is ThreadStatus.WAITING)
    if thread.status == ThreadStatus.WAITING:
        open_deps = [
            d for d in thread.dependencies if d.status == DependencyStatus.OPEN
        ]
        if open_deps:
            reasons.append(UnfinishedReason.WAITING_ON_DEPENDENCY)

    # RECENT_ACTIVITY: true only when most recent event is <= 7 days before reference_time
    if thread.events:
        most_recent_event = max(thread.events, key=lambda e: e.timestamp)
        event_age_days = (
            ref_time - most_recent_event.timestamp
        ).total_seconds() / 86400.0
        if 0.0 <= event_age_days <= 7.0:
            reasons.append(UnfinishedReason.RECENT_ACTIVITY)

    # MISSING_REQUIRED_EVIDENCE
    if len(thread.evidence) < MIN_EVIDENCE_COUNT:
        reasons.append(UnfinishedReason.MISSING_REQUIRED_EVIDENCE)

    return reasons


# ---------------------------------------------------------------------------
# Blocker Detail Extraction
# ---------------------------------------------------------------------------


def extract_blocker_details(thread: IntentThread) -> list[BlockerDetail]:
    """
    Extract structured blocker details with supporting evidence IDs.

    Links each active blocker to evidence items whose descriptions
    contain keywords from the blocker's description (case-insensitive).
    """
    active_blockers = thread.active_blockers
    if not active_blockers:
        return []

    details: list[BlockerDetail] = []
    for blocker in active_blockers:
        # Find supporting evidence by keyword overlap
        blocker_keywords = set(blocker.description.lower().split())
        supporting_ids: list[str] = []
        for e in thread.evidence:
            evidence_words = set(e.description.lower().split())
            if blocker_keywords & evidence_words:
                supporting_ids.append(e.id)

        details.append(
            BlockerDetail(
                dependency_id=blocker.id,
                description=blocker.description,
                type=blocker.type,
                supporting_evidence_ids=supporting_ids,
            )
        )
    return details


# ---------------------------------------------------------------------------
# Attention Signal Calculation
# ---------------------------------------------------------------------------


def compute_attention(
    thread: IntentThread,
    evidence_summary: EvidenceSummary,
    reference_time: datetime | None = None,
) -> AttentionSignal:
    """
    Compute deterministic attention signal for a thread.

    Formula:
        P = 0.30 * priority_score
          + 0.25 * blocker_score
          + 0.20 * commitment_score
          + 0.15 * recency_score
          + 0.10 * evidence_score

    Dimension scores:
        priority_score: HIGH=1.0, MEDIUM=0.5, LOW=0.2
        blocker_score: 1.0 if active blockers exist, else 0.0
        commitment_score: min(1.0, open_commitments / max(1, total_commitments))
        recency_score: recency_factor of most recent event relative to reference_time
                       (decays over 90 days)
        evidence_score: evidence_summary.confidence (already [0, 1])

    Level classification:
        >= 0.65  →  HIGH
        >= 0.35  →  MEDIUM
        < 0.35   →  LOW
    """
    ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
    factors: list[str] = []

    # Priority
    priority_score = PRIORITY_SCORES.get(thread.priority, 0.2)
    if thread.priority == Priority.HIGH:
        factors.append("HIGH priority")
    elif thread.priority == Priority.MEDIUM:
        factors.append("MEDIUM priority")

    # Blocker
    has_blockers = len(thread.active_blockers) > 0
    blocker_score = 1.0 if has_blockers else 0.0
    if has_blockers:
        factors.append("ACTIVE blocker")

    # Commitment
    total_commitments = len(thread.commitments)
    open_count = thread.open_commitments_count
    commitment_score = min(1.0, open_count / max(1, total_commitments))
    if open_count > 0:
        factors.append("OPEN commitment")

    # Recency: based on most recent event relative to reference_time
    if thread.events:
        most_recent_event = max(thread.events, key=lambda e: e.timestamp)
        event_age_days = (
            ref_time - most_recent_event.timestamp
        ).total_seconds() / 86400.0
        recency_score = max(0.0, 1.0 - event_age_days / RECENCY_DECAY_DAYS)
    else:
        recency_score = 0.0
    if recency_score >= 0.8:
        factors.append("Recent activity")

    # Evidence strength
    evidence_score = evidence_summary.confidence
    if evidence_summary.confidence_band == ConfidenceBand.STRONG:
        factors.append("STRONG evidence")
    elif evidence_summary.is_weak:
        factors.append("WEAK evidence")

    # Weighted sum
    raw_score = (
        ATTENTION_WEIGHT_PRIORITY * priority_score
        + ATTENTION_WEIGHT_BLOCKER * blocker_score
        + ATTENTION_WEIGHT_COMMITMENT * commitment_score
        + ATTENTION_WEIGHT_RECENCY * recency_score
        + ATTENTION_WEIGHT_EVIDENCE * evidence_score
    )
    score = max(0.0, min(1.0, round(raw_score, 4)))

    # Level classification
    if score >= ATTENTION_HIGH_THRESHOLD:
        level = AttentionLevel.HIGH
    elif score >= ATTENTION_MEDIUM_THRESHOLD:
        level = AttentionLevel.MEDIUM
    else:
        level = AttentionLevel.LOW

    return AttentionSignal(level=level, score=score, factors=factors)


# ---------------------------------------------------------------------------
# Explanation Generation
# ---------------------------------------------------------------------------


def generate_explanation(thread: IntentThread) -> str:
    """
    Generate a deterministic textual explanation of the thread's current state.

    Uses only structured data. No LLM involvement.
    """
    parts: list[str] = []

    # Status description
    status_descriptions = {
        ThreadStatus.DISCOVERED: f"'{thread.title}' was discovered as an unresolved intention.",
        ThreadStatus.ACTIVE: f"'{thread.title}' is actively being pursued.",
        ThreadStatus.BLOCKED: f"'{thread.title}' is blocked by an unresolved dependency.",
        ThreadStatus.WAITING: f"'{thread.title}' is waiting on external input.",
        ThreadStatus.COMPLETED: f"'{thread.title}' has been completed.",
        ThreadStatus.ABANDONED: f"'{thread.title}' has been abandoned.",
    }
    parts.append(
        status_descriptions.get(
            thread.status, f"'{thread.title}' is in {thread.status.value} state."
        )
    )

    # Open commitments
    open_commitments = [
        c for c in thread.commitments if c.status == CommitmentStatus.OPEN
    ]
    if open_commitments:
        commitment_desc = ", ".join(f'"{c.description}"' for c in open_commitments)
        parts.append(
            f"Open commitment{'s' if len(open_commitments) > 1 else ''}: {commitment_desc}."
        )

    # Active blockers
    active_blockers = thread.active_blockers
    if active_blockers:
        blocker_desc = ", ".join(f'"{b.description}"' for b in active_blockers)
        parts.append(f"Blocked by: {blocker_desc}.")

    # Evidence count
    if thread.evidence:
        parts.append(
            f"Supported by {len(thread.evidence)} evidence item{'s' if len(thread.evidence) > 1 else ''}."
        )
    else:
        parts.append("No supporting evidence found.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main Analysis Function
# ---------------------------------------------------------------------------


class AnalysisService:
    """
    Deterministic analysis engine for IntentThread evaluation.

    Produces structured ThreadAnalysis objects using only domain data.
    Independent of MCP, transport, LLM, and database layers.
    """

    def analyze(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> ThreadAnalysis:
        """
        Analyze an IntentThread and produce a structured ThreadAnalysis.

        Pipeline:
            1. Evidence aggregation
            2. Commitment analysis
            3. Blocker analysis
            4. Unfinished reason classification
            5. Attention calculation
            6. Confidence calculation
            7. Explanation generation

        Args:
            thread: The IntentThread to analyze.
            reference_time: Explicit deterministic reference time for analysis.
                            Defaults to DEFAULT_ANALYSIS_REFERENCE_TIME.

        Returns:
            ThreadAnalysis with complete deterministic analysis.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME

        # 1. Evidence aggregation
        evidence_summary = aggregate_evidence(thread.evidence, ref_time)

        # 2. Open commitments
        open_commitments = [
            c.description
            for c in thread.commitments
            if c.status == CommitmentStatus.OPEN
        ]

        # 3. Blocker analysis
        blocker_details = extract_blocker_details(thread)

        # 4. Unfinished reasons
        unfinished_reasons = classify_unfinished_reasons(thread, ref_time)

        # 5. Attention signal
        attention = compute_attention(thread, evidence_summary, ref_time)

        # 6. Overall confidence
        # Combine thread confidence and evidence confidence:
        # overall = 0.6 * thread.confidence + 0.4 * evidence_summary.confidence
        # This anchors on the thread's declared confidence while incorporating
        # evidence strength.
        if evidence_summary.total > 0:
            overall_confidence = (
                0.6 * thread.confidence + 0.4 * evidence_summary.confidence
            )
        else:
            # No evidence: degrade confidence significantly
            overall_confidence = thread.confidence * 0.5
        overall_confidence = max(0.0, min(1.0, round(overall_confidence, 4)))

        confidence_band = classify_confidence(overall_confidence)

        # 7. Explanation
        explanation = generate_explanation(thread)

        return ThreadAnalysis(
            thread_id=thread.id,
            current_status=thread.status,
            explanation=explanation,
            unfinished_reasons=unfinished_reasons,
            open_commitments=open_commitments,
            active_blockers=blocker_details,
            evidence_summary=evidence_summary,
            attention=attention,
            confidence=overall_confidence,
            confidence_band=confidence_band,
        )
