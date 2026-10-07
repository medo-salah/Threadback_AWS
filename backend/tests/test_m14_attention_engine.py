"""
Unit tests for Threadback M14.2 Attention Engine Core.

Validates:
1. Exact weighted formula calculation and score bounds [0.0, 1.0].
2. Commitment pressure normalization and deterministic maximum aggregation.
3. Blocker pressure normalization and deterministic maximum aggregation.
4. Inactivity signal exact interval boundaries (<3d, 3d, 7d, 14d, >14d).
5. Evidence confidence calculation and consistency with M4/M13.
6. Explicit CRITICAL override precedence and boundary values.
7. Exact AttentionLevel classification thresholds.
8. Complete determinism (same input + reference time = identical candidate).
9. Thread evaluation, reason codes, and multi-thread ranking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.domain.enums import (
    AttentionLevel,
    AttentionReasonCode,
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    Priority,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Evidence,
    IntentThread,
)
from app.services.attention_engine import (
    WEIGHT_BLOCKER_PRESSURE,
    WEIGHT_CHANGE,
    WEIGHT_COMMITMENT_PRESSURE,
    WEIGHT_EVIDENCE_CONFIDENCE,
    WEIGHT_INACTIVITY,
    WEIGHT_URGENCY,
    AttentionEngine,
)


@pytest.fixture
def engine() -> AttentionEngine:
    return AttentionEngine()


@pytest.fixture
def ref_time() -> datetime:
    return datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)


def _build_minimal_thread(
    thread_id: str = "t-1",
    title: str = "Test Thread",
    status: ThreadStatus = ThreadStatus.ACTIVE,
    priority: Priority = Priority.MEDIUM,
    last_act: datetime | None = None,
    commitments: list[Commitment] | None = None,
    dependencies: list[Dependency] | None = None,
    evidence: list[Evidence] | None = None,
) -> IntentThread:
    now = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
    return IntentThread(
        id=thread_id,
        title=title,
        description="Test description",
        status=status,
        priority=priority,
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=1),
        last_activity_at=last_act or now,
        last_interaction_at=last_act or now,
        confidence=0.90,
        commitments=commitments or [],
        dependencies=dependencies or [],
        evidence=evidence or [],
    )


# ---------------------------------------------------------------------------
# 1. Formula & Score Bounds
# ---------------------------------------------------------------------------


def test_formula_weights_sum_to_one() -> None:
    total = (
        WEIGHT_URGENCY
        + WEIGHT_CHANGE
        + WEIGHT_COMMITMENT_PRESSURE
        + WEIGHT_BLOCKER_PRESSURE
        + WEIGHT_INACTIVITY
        + WEIGHT_EVIDENCE_CONFIDENCE
    )
    assert pytest.approx(total, abs=1e-6) == 1.0


def test_calculate_attention_score_all_zero(engine: AttentionEngine) -> None:
    score = engine.calculate_attention_score(
        urgency=0.0,
        change=0.0,
        commitment_pressure=0.0,
        blocker_pressure=0.0,
        inactivity=0.0,
        evidence_confidence=0.0,
    )
    assert score == 0.0


def test_calculate_attention_score_all_one(engine: AttentionEngine) -> None:
    score = engine.calculate_attention_score(
        urgency=1.0,
        change=1.0,
        commitment_pressure=1.0,
        blocker_pressure=1.0,
        inactivity=1.0,
        evidence_confidence=1.0,
    )
    assert pytest.approx(score, abs=1e-6) == 1.0


def test_calculate_attention_score_exact_weights(engine: AttentionEngine) -> None:
    # 0.30(0.8) + 0.20(0.5) + 0.15(1.0) + 0.15(0.8) + 0.10(0.75) + 0.10(0.9)
    # = 0.24 + 0.10 + 0.15 + 0.12 + 0.075 + 0.09 = 0.775
    score = engine.calculate_attention_score(
        urgency=0.8,
        change=0.5,
        commitment_pressure=1.0,
        blocker_pressure=0.8,
        inactivity=0.75,
        evidence_confidence=0.9,
    )
    assert pytest.approx(score, abs=1e-5) == 0.775


def test_calculate_attention_score_bounds_clamping(engine: AttentionEngine) -> None:
    score_low = engine.calculate_attention_score(-0.5, -0.2, 0.0, 0.0, 0.0, 0.0)
    assert score_low == 0.0

    score_high = engine.calculate_attention_score(1.5, 1.2, 1.0, 1.0, 1.0, 1.0)
    assert score_high == 1.0


# ---------------------------------------------------------------------------
# 2. Commitment Pressure
# ---------------------------------------------------------------------------


def test_commitment_pressure_no_commitments(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    thread = _build_minimal_thread()
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 0.0
    assert ids == []
    assert has_overdue is False


def test_commitment_pressure_distant_or_no_due_date(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    # No due date -> 0.30
    c1 = Commitment(
        id="c1", description="No due date", status=CommitmentStatus.OPEN, due_at=None
    )
    thread = _build_minimal_thread(commitments=[c1])
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 0.30
    assert ids == ["c1"]
    assert has_overdue is False

    # Distant due date (> 7 days, e.g. 10 days) -> 0.30
    c2 = Commitment(
        id="c2",
        description="Distant",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(days=10),
    )
    thread2 = _build_minimal_thread(commitments=[c2])
    pressure2, ids2, has_overdue2 = engine.compute_commitment_pressure(
        thread2, ref_time
    )
    assert pressure2 == 0.30
    assert ids2 == ["c2"]
    assert has_overdue2 is False


def test_commitment_pressure_within_7_days(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    c = Commitment(
        id="c-7d",
        description="Within a week",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(days=5),
    )
    thread = _build_minimal_thread(commitments=[c])
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 0.60
    assert ids == ["c-7d"]
    assert has_overdue is False


def test_commitment_pressure_within_72_hours(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    c = Commitment(
        id="c-72h",
        description="Imminent",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(hours=48),
    )
    thread = _build_minimal_thread(commitments=[c])
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 0.85
    assert ids == ["c-72h"]
    assert has_overdue is False


def test_commitment_pressure_overdue(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    c = Commitment(
        id="c-od",
        description="Past due",
        status=CommitmentStatus.OPEN,
        due_at=ref_time - timedelta(hours=1),
    )
    thread = _build_minimal_thread(commitments=[c])
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 1.0
    assert ids == ["c-od"]
    assert has_overdue is True


def test_commitment_pressure_multiple_maximum_rule(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    # 3 commitments: distant (0.3), imminent (0.85), overdue (1.0)
    c1 = Commitment(
        id="c1",
        description="Distant",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(days=14),
    )
    c2 = Commitment(
        id="c2",
        description="72h",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(hours=24),
    )
    c3 = Commitment(
        id="c3",
        description="Overdue",
        status=CommitmentStatus.OPEN,
        due_at=ref_time - timedelta(days=1),
    )
    # Closed commitment should be ignored
    c4 = Commitment(
        id="c4",
        description="Closed",
        status=CommitmentStatus.COMPLETED,
        due_at=ref_time - timedelta(days=5),
    )

    thread = _build_minimal_thread(commitments=[c1, c2, c3, c4])
    pressure, ids, has_overdue = engine.compute_commitment_pressure(thread, ref_time)
    assert pressure == 1.0
    assert ids == ["c3"]
    assert has_overdue is True


# ---------------------------------------------------------------------------
# 3. Blocker Pressure
# ---------------------------------------------------------------------------


def test_blocker_pressure_no_blockers(engine: AttentionEngine) -> None:
    thread = _build_minimal_thread()
    pressure, ids, has_blocker = engine.compute_blocker_pressure(thread)
    assert pressure == 0.0
    assert ids == []
    assert has_blocker is False


def test_blocker_pressure_waiting_status_or_blocker(engine: AttentionEngine) -> None:
    # Thread in WAITING status with no active blockers
    thread_waiting = _build_minimal_thread(status=ThreadStatus.WAITING)
    pressure_w, ids_w, has_w = engine.compute_blocker_pressure(thread_waiting)
    assert pressure_w == 0.4
    assert has_w is False

    # Thread with CLIENT waiting blocker
    d = Dependency(
        id="d-wait",
        description="Client review",
        type="CLIENT",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    thread_dep = _build_minimal_thread(dependencies=[d])
    pressure_d, ids_d, has_d = engine.compute_blocker_pressure(thread_dep)
    assert pressure_d == 0.4
    assert ids_d == ["d-wait"]
    assert has_d is True


def test_blocker_pressure_missing_document(engine: AttentionEngine) -> None:
    d = Dependency(
        id="d-doc",
        description="Official transcript",
        type="DOCUMENT",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    thread = _build_minimal_thread(dependencies=[d])
    pressure, ids, has_blocker = engine.compute_blocker_pressure(thread)
    assert pressure == 0.8
    assert ids == ["d-doc"]
    assert has_blocker is True


def test_blocker_pressure_named_person(engine: AttentionEngine) -> None:
    d = Dependency(
        id="d-person",
        description="Recommendation from Ahmed",
        type="PERSON",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    thread = _build_minimal_thread(dependencies=[d])
    pressure, ids, has_blocker = engine.compute_blocker_pressure(thread)
    assert pressure == 1.0
    assert ids == ["d-person"]
    assert has_blocker is True


def test_blocker_pressure_multiple_maximum_rule(engine: AttentionEngine) -> None:
    d1 = Dependency(
        id="d-doc",
        description="Transcript",
        type="DOCUMENT",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    d2 = Dependency(
        id="d-person",
        description="Letter",
        type="PERSON",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    d3 = Dependency(
        id="d-resolved",
        description="Fee",
        type="PERSON",
        status=DependencyStatus.RESOLVED,
        blocking=False,
    )

    thread = _build_minimal_thread(dependencies=[d1, d2, d3])
    pressure, ids, has_blocker = engine.compute_blocker_pressure(thread)
    # Maximum of 0.8 and 1.0 is 1.0
    assert pressure == 1.0
    assert "d-doc" in ids
    assert "d-person" in ids
    assert "d-resolved" not in ids
    assert has_blocker is True


# ---------------------------------------------------------------------------
# 4. Inactivity
# ---------------------------------------------------------------------------


def test_inactivity_exact_intervals(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    # < 3 days: 2.9 days
    t_recent = _build_minimal_thread(last_act=ref_time - timedelta(days=2, hours=22))
    assert engine.compute_inactivity_signal(t_recent, ref_time) == 0.10

    # Exactly 3.0 days -> 0.40
    t_3d = _build_minimal_thread(last_act=ref_time - timedelta(days=3))
    assert engine.compute_inactivity_signal(t_3d, ref_time) == 0.40

    # 5.0 days -> 0.40
    t_5d = _build_minimal_thread(last_act=ref_time - timedelta(days=5))
    assert engine.compute_inactivity_signal(t_5d, ref_time) == 0.40

    # Exactly 7.0 days -> 0.75
    t_7d = _build_minimal_thread(last_act=ref_time - timedelta(days=7))
    assert engine.compute_inactivity_signal(t_7d, ref_time) == 0.75

    # 10.0 days -> 0.75
    t_10d = _build_minimal_thread(last_act=ref_time - timedelta(days=10))
    assert engine.compute_inactivity_signal(t_10d, ref_time) == 0.75

    # Exactly 14.0 days -> 1.0
    t_14d = _build_minimal_thread(last_act=ref_time - timedelta(days=14))
    assert engine.compute_inactivity_signal(t_14d, ref_time) == 1.0

    # Beyond 14 days (20 days) -> 1.0
    t_20d = _build_minimal_thread(last_act=ref_time - timedelta(days=20))
    assert engine.compute_inactivity_signal(t_20d, ref_time) == 1.0


# ---------------------------------------------------------------------------
# 5. Evidence Confidence
# ---------------------------------------------------------------------------


def test_evidence_confidence_empty(engine: AttentionEngine, ref_time: datetime) -> None:
    thread = _build_minimal_thread()
    conf, ids = engine.compute_evidence_confidence(thread, ref_time)
    assert conf == 0.0
    assert ids == []


def test_evidence_confidence_with_items(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    e1 = Evidence(
        id="e1",
        type=EvidenceType.CONVERSATION,
        description="Slack chat",
        source="Slack",
        created_at=ref_time - timedelta(days=1),
        confidence=0.95,
    )
    e2 = Evidence(
        id="e2",
        type=EvidenceType.DOCUMENT,
        description="Draft document",
        source="Drive",
        created_at=ref_time - timedelta(days=2),
        confidence=0.85,
    )
    thread = _build_minimal_thread(evidence=[e1, e2])
    conf, ids = engine.compute_evidence_confidence(thread, ref_time)
    assert conf > 0.80
    assert ids == ["e1", "e2"]


# ---------------------------------------------------------------------------
# 6. CRITICAL Override Precedence & Exact Boundaries
# ---------------------------------------------------------------------------


def test_classify_attention_level_score_based_critical(engine: AttentionEngine) -> None:
    # Score 0.80 -> CRITICAL regardless of urgency or blocker
    level = engine.classify_attention_level(
        attention_score=0.80,
        urgency_score=0.50,
        has_active_blocker=False,
        has_overdue_commitment=False,
    )
    assert level == AttentionLevel.CRITICAL


def test_classify_attention_level_blocker_override_critical(
    engine: AttentionEngine,
) -> None:
    # Urgency 0.85 + active blocker -> CRITICAL even if score is below 0.80
    level = engine.classify_attention_level(
        attention_score=0.64,
        urgency_score=0.85,
        has_active_blocker=True,
        has_overdue_commitment=False,
    )
    assert level == AttentionLevel.CRITICAL


def test_classify_attention_level_overdue_override_critical(
    engine: AttentionEngine,
) -> None:
    # Urgency 0.85 + overdue commitment -> CRITICAL even if score is below 0.80
    level = engine.classify_attention_level(
        attention_score=0.60,
        urgency_score=0.85,
        has_active_blocker=False,
        has_overdue_commitment=True,
    )
    assert level == AttentionLevel.CRITICAL


def test_classify_attention_level_exact_0849_non_override(
    engine: AttentionEngine,
) -> None:
    # Urgency 0.849 (below 0.85) with blocker -> NO override!
    # Evaluates according to standard score threshold
    level_high = engine.classify_attention_level(
        attention_score=0.70,
        urgency_score=0.849,
        has_active_blocker=True,
        has_overdue_commitment=False,
    )
    assert level_high == AttentionLevel.HIGH

    level_med = engine.classify_attention_level(
        attention_score=0.50,
        urgency_score=0.849,
        has_active_blocker=True,
        has_overdue_commitment=False,
    )
    assert level_med == AttentionLevel.MEDIUM


def test_classify_attention_level_threshold_boundaries(engine: AttentionEngine) -> None:
    # 0.80 -> CRITICAL
    assert (
        engine.classify_attention_level(0.80, 0.5, False, False)
        == AttentionLevel.CRITICAL
    )
    # 0.799 -> HIGH
    assert (
        engine.classify_attention_level(0.799, 0.5, False, False) == AttentionLevel.HIGH
    )
    # 0.65 -> HIGH
    assert (
        engine.classify_attention_level(0.65, 0.5, False, False) == AttentionLevel.HIGH
    )
    # 0.649 -> MEDIUM
    assert (
        engine.classify_attention_level(0.649, 0.5, False, False)
        == AttentionLevel.MEDIUM
    )
    # 0.40 -> MEDIUM
    assert (
        engine.classify_attention_level(0.40, 0.5, False, False)
        == AttentionLevel.MEDIUM
    )
    # 0.399 -> LOW
    assert (
        engine.classify_attention_level(0.399, 0.5, False, False) == AttentionLevel.LOW
    )
    # 0.20 -> LOW
    assert (
        engine.classify_attention_level(0.20, 0.5, False, False) == AttentionLevel.LOW
    )
    # 0.199 -> NONE
    assert (
        engine.classify_attention_level(0.199, 0.5, False, False) == AttentionLevel.NONE
    )


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


def test_evaluate_thread_determinism(
    engine: AttentionEngine, ref_time: datetime
) -> None:
    c = Commitment(
        id="c1",
        description="Submit paper",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(hours=24),
    )
    d = Dependency(
        id="d1",
        description="Letter",
        type="PERSON",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    e = Evidence(
        id="e1",
        type=EvidenceType.DOCUMENT,
        description="Draft",
        source="Google Drive",
        created_at=ref_time - timedelta(days=2),
        confidence=0.9,
    )
    thread = _build_minimal_thread(
        commitments=[c],
        dependencies=[d],
        evidence=[e],
        last_act=ref_time - timedelta(days=4),
    )

    cand1 = engine.evaluate_thread(thread, change_signal=0.5, reference_time=ref_time)
    cand2 = engine.evaluate_thread(thread, change_signal=0.5, reference_time=ref_time)

    assert cand1.attention_score == cand2.attention_score
    assert cand1.urgency_score == cand2.urgency_score
    assert cand1.attention_level == cand2.attention_level
    assert cand1.reason_codes == cand2.reason_codes
    assert cand1.human_readable_explanation == cand2.human_readable_explanation
    assert cand1.supporting_commitment_ids == cand2.supporting_commitment_ids
    assert cand1.blocker_ids == cand2.blocker_ids
    assert cand1.generated_at == cand2.generated_at


# ---------------------------------------------------------------------------
# 8. Thread Evaluation & Multi-Thread Ranking
# ---------------------------------------------------------------------------


def test_evaluate_threads_ranking(engine: AttentionEngine, ref_time: datetime) -> None:
    # Thread 1: Urgent + Blocked (should rank high)
    c1 = Commitment(
        id="c1",
        description="Urgent",
        status=CommitmentStatus.OPEN,
        due_at=ref_time - timedelta(hours=1),
    )
    d1 = Dependency(
        id="d1",
        description="Ahmed",
        type="PERSON",
        status=DependencyStatus.OPEN,
        blocking=True,
    )
    t1 = _build_minimal_thread(
        thread_id="t-urgent",
        priority=Priority.HIGH,
        commitments=[c1],
        dependencies=[d1],
        last_act=ref_time - timedelta(days=15),
    )

    # Thread 2: Distant / healthy (should rank lower)
    c2 = Commitment(
        id="c2",
        description="Distant",
        status=CommitmentStatus.OPEN,
        due_at=ref_time + timedelta(days=30),
    )
    t2 = _build_minimal_thread(
        thread_id="t-distant",
        priority=Priority.LOW,
        commitments=[c2],
        last_act=ref_time - timedelta(days=1),
    )

    candidates = engine.evaluate_threads([t2, t1], reference_time=ref_time)
    assert len(candidates) == 2
    assert candidates[0].thread_id == "t-urgent"
    assert candidates[0].attention_level == AttentionLevel.CRITICAL
    assert AttentionReasonCode.DEADLINE_OVERDUE in candidates[0].reason_codes
    assert AttentionReasonCode.BLOCKER_PRESENT in candidates[0].reason_codes

    assert candidates[1].thread_id == "t-distant"
    assert candidates[0].attention_score > candidates[1].attention_score
