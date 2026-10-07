"""
Unit tests for Threadback M14.1 domain enums and Pydantic models.

Validates:
1. Every new enum member across all M14 enumerations.
2. Field validation and score bounds ([0, 1]) for AttentionCandidate and AttentionDelta.
3. Required vs optional fields.
4. JSON serialization and deserialization roundtrips.
5. Timezone-aware UTC datetime defaults.
6. ProactiveInsightRecord has no acknowledged_at field.
7. AttentionCandidate does NOT embed NextActionSuggestion (decoupled architecture).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.domain.enums import (
    AttentionLevel,
    AttentionReasonCode,
    ChangeCategory,
    ConflictType,
    Priority,
    ProactiveTriggerType,
    ResumeEligibility,
    SignificanceLevel,
)
from app.domain.models import (
    AttentionCandidate,
    AttentionDelta,
    IntentConflict,
    IntentHealthSummary,
    ProactiveBriefing,
    ProactiveInsightRecord,
    ProactiveTrigger,
    ResumableCandidate,
    StateChangeItem,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# 1. Enumeration Member Tests
# ---------------------------------------------------------------------------


def test_attention_level_members() -> None:
    expected = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"}
    actual = {m.value for m in AttentionLevel}
    assert actual == expected
    assert AttentionLevel.CRITICAL.value == "CRITICAL"
    assert AttentionLevel.NONE.value == "NONE"


def test_attention_reason_code_members() -> None:
    expected = {
        "DEADLINE_APPROACHING",
        "DEADLINE_OVERDUE",
        "INTENT_DECAYING",
        "INTENT_STALE",
        "BLOCKER_PRESENT",
        "COMMITMENT_DUE",
        "COMMITMENT_OVERDUE",
        "IMPORTANT_CHANGE",
        "NEW_EVIDENCE",
        "GOAL_EVOLVED",
        "THREAD_RESUMABLE",
        "LONG_INACTIVITY",
        "CONFLICTING_INTENT",
    }
    actual = {m.value for m in AttentionReasonCode}
    assert actual == expected


def test_significance_level_members() -> None:
    expected = {"NONE", "LOW", "MEDIUM", "HIGH"}
    actual = {m.value for m in SignificanceLevel}
    assert actual == expected


def test_conflict_type_members() -> None:
    expected = {
        "RESOURCE_CONFLICT",
        "TIME_CONFLICT",
        "DEADLINE_CONFLICT",
        "GOAL_CONFLICT",
        "COMMITMENT_CONFLICT",
        "NO_CONFLICT_DETERMINED",
    }
    actual = {m.value for m in ConflictType}
    assert actual == expected


def test_resume_eligibility_members() -> None:
    expected = {"RESUMABLE", "NOT_RESUMABLE", "UNKNOWN"}
    actual = {m.value for m in ResumeEligibility}
    assert actual == expected


def test_proactive_trigger_type_members() -> None:
    expected = {
        "ATTENTION_THRESHOLD_CROSSED",
        "DEADLINE_APPROACHING",
        "INTENT_DECAYED",
        "BLOCKER_RESOLVED",
        "THREAD_BECAME_RESUMABLE",
        "SIGNIFICANT_CHANGE",
        "CONFLICT_DETECTED",
    }
    actual = {m.value for m in ProactiveTriggerType}
    assert actual == expected


# ---------------------------------------------------------------------------
# 2. AttentionCandidate Tests
# ---------------------------------------------------------------------------


def test_attention_candidate_valid() -> None:
    cand = AttentionCandidate(
        thread_id="thread-test-1",
        thread_title="Graduate Application",
        attention_level=AttentionLevel.HIGH,
        attention_score=0.75,
        urgency_score=0.80,
        reason_codes=[
            AttentionReasonCode.DEADLINE_APPROACHING,
            AttentionReasonCode.BLOCKER_PRESENT,
        ],
        human_readable_explanation="Deadline is approaching and blocker is open.",
        supporting_evidence_ids=["evi-1"],
        supporting_commitment_ids=["com-1"],
        blocker_ids=["dep-1"],
        recommended_action_summary="Follow up on recommendation letter",
    )
    assert cand.thread_id == "thread-test-1"
    assert cand.attention_score == 0.75
    assert cand.urgency_score == 0.80
    assert cand.generated_at.tzinfo is not None
    assert cand.recommended_action_summary == "Follow up on recommendation letter"


def test_attention_candidate_score_bounds() -> None:
    # Test valid boundary values 0.0 and 1.0
    c_low = AttentionCandidate(
        thread_id="t1",
        thread_title="Low",
        attention_level=AttentionLevel.NONE,
        attention_score=0.0,
        urgency_score=0.0,
        human_readable_explanation="None",
    )
    assert c_low.attention_score == 0.0

    c_high = AttentionCandidate(
        thread_id="t2",
        thread_title="High",
        attention_level=AttentionLevel.CRITICAL,
        attention_score=1.0,
        urgency_score=1.0,
        human_readable_explanation="Critical",
    )
    assert c_high.attention_score == 1.0

    # Negative attention_score
    with pytest.raises(ValidationError):
        AttentionCandidate(
            thread_id="t3",
            thread_title="Invalid",
            attention_level=AttentionLevel.LOW,
            attention_score=-0.01,
            urgency_score=0.5,
            human_readable_explanation="Invalid",
        )

    # Attention score > 1.0
    with pytest.raises(ValidationError):
        AttentionCandidate(
            thread_id="t4",
            thread_title="Invalid",
            attention_level=AttentionLevel.HIGH,
            attention_score=1.01,
            urgency_score=0.5,
            human_readable_explanation="Invalid",
        )

    # Negative urgency_score
    with pytest.raises(ValidationError):
        AttentionCandidate(
            thread_id="t5",
            thread_title="Invalid",
            attention_level=AttentionLevel.LOW,
            attention_score=0.5,
            urgency_score=-0.1,
            human_readable_explanation="Invalid",
        )

    # Urgency score > 1.0
    with pytest.raises(ValidationError):
        AttentionCandidate(
            thread_id="t6",
            thread_title="Invalid",
            attention_level=AttentionLevel.HIGH,
            attention_score=0.5,
            urgency_score=1.1,
            human_readable_explanation="Invalid",
        )


def test_attention_candidate_decoupling_from_next_action() -> None:
    """Ensure AttentionCandidate does not have a NextActionSuggestion field."""
    fields = AttentionCandidate.model_fields
    assert "recommended_next_action" not in fields
    assert "next_action" not in fields
    assert "recommended_action_summary" in fields


# ---------------------------------------------------------------------------
# 3. AttentionDelta Tests
# ---------------------------------------------------------------------------


def test_attention_delta_valid() -> None:
    now = datetime.now(timezone.utc)
    change = StateChangeItem(
        category=ChangeCategory.GOAL_CHANGE,
        description="Goal evolved to include teeth cleaning",
        timestamp=now,
        before_value="Routine checkup",
        after_value="Comprehensive cleaning",
    )
    delta = AttentionDelta(
        thread_id="thread-dentist",
        thread_title="Dentist",
        changes=[change],
        significance_score=0.85,
        significance_level=SignificanceLevel.HIGH,
        reason_codes=[AttentionReasonCode.GOAL_EVOLVED],
        source_event_ids=["evt-dentist-1"],
    )
    assert delta.thread_id == "thread-dentist"
    assert len(delta.changes) == 1
    assert delta.changes[0].category == ChangeCategory.GOAL_CHANGE
    assert delta.significance_score == 0.85
    assert delta.evaluated_at.tzinfo is not None


def test_attention_delta_score_bounds() -> None:
    with pytest.raises(ValidationError):
        AttentionDelta(
            thread_id="t1",
            thread_title="Invalid",
            significance_score=1.5,
            significance_level=SignificanceLevel.HIGH,
        )

    with pytest.raises(ValidationError):
        AttentionDelta(
            thread_id="t2",
            thread_title="Invalid",
            significance_score=-0.1,
            significance_level=SignificanceLevel.LOW,
        )


# ---------------------------------------------------------------------------
# 4. IntentConflict Tests
# ---------------------------------------------------------------------------


def test_intent_conflict_valid() -> None:
    conflict = IntentConflict(
        conflict_id="conf-1",
        thread_a_id="thread-aws-hackathon",
        thread_a_title="AWS Hackathon",
        thread_b_id="thread-client-report",
        thread_b_title="Client Report",
        conflict_type=ConflictType.TIME_CONFLICT,
        severity=Priority.HIGH,
        explanation="Both threads have mutually exclusive commitments at 10:00 UTC",
        evidence_ids=["evi-aws-1", "evi-client-1"],
    )
    assert conflict.conflict_id == "conf-1"
    assert conflict.conflict_type == ConflictType.TIME_CONFLICT
    assert conflict.severity == Priority.HIGH
    assert conflict.detected_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 5. ResumableCandidate Tests
# ---------------------------------------------------------------------------


def test_resumable_candidate_valid() -> None:
    resume_target = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = ResumableCandidate(
        thread_id="thread-cert",
        thread_title="Certification Exam",
        eligibility=ResumeEligibility.RESUMABLE,
        reason="Deferral deadline passed and transcript blocker is resolved.",
        supporting_blocker_ids=["dep-transcript"],
        supporting_evidence_ids=["evi-transcript"],
        supporting_event_ids=["evt-resumed-check"],
        deferred_until=resume_target,
    )
    assert res.thread_id == "thread-cert"
    assert res.eligibility == ResumeEligibility.RESUMABLE
    assert res.deferred_until == resume_target
    assert res.evaluated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 6. IntentHealthSummary & ProactiveBriefing Tests
# ---------------------------------------------------------------------------


def test_intent_health_summary_valid() -> None:
    summary = IntentHealthSummary(
        total_active_threads=5,
        healthy_threads=2,
        attention_threads=1,
        decaying_threads=1,
        stale_threads=0,
        blocked_threads=1,
        deferred_threads=1,
        resumable_threads=1,
        conflicts_count=0,
    )
    assert summary.total_active_threads == 5
    assert summary.healthy_threads == 2
    assert summary.generated_at.tzinfo is not None


def test_proactive_briefing_valid() -> None:
    summary = IntentHealthSummary(
        total_active_threads=3,
        healthy_threads=1,
        attention_threads=1,
        decaying_threads=0,
        stale_threads=0,
        blocked_threads=1,
        deferred_threads=0,
        resumable_threads=0,
        conflicts_count=0,
    )
    cand = AttentionCandidate(
        thread_id="thread-app",
        thread_title="Application",
        attention_level=AttentionLevel.HIGH,
        attention_score=0.72,
        urgency_score=0.81,
        reason_codes=[AttentionReasonCode.BLOCKER_PRESENT],
        human_readable_explanation="Recommendation letter missing.",
    )
    briefing = ProactiveBriefing(
        top_attention=[cand],
        top_changes=[],
        top_resumable=[],
        top_conflicts=[],
        health_summary=summary,
        briefing_text="You have 1 item requiring attention.",
    )
    assert len(briefing.top_attention) == 1
    assert briefing.briefing_text == "You have 1 item requiring attention."
    assert briefing.generated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 7. ProactiveInsightRecord & ProactiveTrigger Tests
# ---------------------------------------------------------------------------


def test_proactive_insight_record_has_no_acknowledged_at() -> None:
    """Explicitly verify acknowledged_at is NOT in ProactiveInsightRecord."""
    fields = ProactiveInsightRecord.model_fields
    assert "acknowledged_at" not in fields
    assert "insight_id" in fields
    assert "thread_id" in fields
    assert "insight_type" in fields
    assert "state_fingerprint" in fields
    assert "source_event_ids" in fields
    assert "created_at" in fields

    rec = ProactiveInsightRecord(
        insight_id="ins-1",
        thread_id="t-1",
        insight_type="ATTENTION_THRESHOLD_CROSSED",
        state_fingerprint="abc123hash",
        source_event_ids=["evt-1"],
    )
    assert rec.insight_id == "ins-1"
    assert rec.created_at.tzinfo is not None


def test_proactive_trigger_valid() -> None:
    trigger = ProactiveTrigger(
        trigger_id="trig-1",
        trigger_type=ProactiveTriggerType.ATTENTION_THRESHOLD_CROSSED,
        thread_id="thread-app",
        reason="Attention score crossed 0.65 threshold",
        candidate_id="cand-1",
    )
    assert trigger.trigger_id == "trig-1"
    assert trigger.trigger_type == ProactiveTriggerType.ATTENTION_THRESHOLD_CROSSED
    assert trigger.evaluated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 8. Serialization / Deserialization Roundtrips
# ---------------------------------------------------------------------------


def test_serialization_roundtrips() -> None:
    cand = AttentionCandidate(
        thread_id="thread-app",
        thread_title="Application",
        attention_level=AttentionLevel.CRITICAL,
        attention_score=0.88,
        urgency_score=0.90,
        reason_codes=[
            AttentionReasonCode.DEADLINE_OVERDUE,
            AttentionReasonCode.BLOCKER_PRESENT,
        ],
        human_readable_explanation="Critical deadline overdue and blocked.",
        supporting_evidence_ids=["evi-1"],
        supporting_commitment_ids=["com-1"],
        blocker_ids=["dep-1"],
        recommended_action_summary="Urgent follow-up",
    )
    raw = cand.model_dump_json()
    restored = AttentionCandidate.model_validate_json(raw)
    assert restored.thread_id == cand.thread_id
    assert restored.attention_level == AttentionLevel.CRITICAL
    assert restored.attention_score == 0.88
    assert restored.reason_codes == cand.reason_codes
    assert restored.recommended_action_summary == "Urgent follow-up"
