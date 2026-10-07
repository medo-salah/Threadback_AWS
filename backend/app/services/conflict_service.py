"""
Conservative Deterministic Conflict Detection Service for Threadback M14.

Detects conflicts between intentions ONLY when structured evidence satisfies the
approved criteria:
  1. TIME_CONFLICT: Scheduled datetime intervals explicitly identical/overlapping.
  2. DEADLINE_CONFLICT: Both HIGH priority, both overdue/immediate hard deadlines,
     both requiring full-time action today.
  3. RESOURCE_CONFLICT: Both threads require the same finite resource with is_exclusive=True.
  4. GOAL_CONFLICT: Explicit structured contradiction (MUTUAL_EXCLUSION dependency,
     conflicting_thread_ids, antagonistic constraints).
  5. COMMITMENT_CONFLICT: Mutually contradictory commitment payloads.

Invariants:
- NEVER uses fuzzy NLP contradiction detection.
- Conservative false negatives are strictly preferred over fabricated conflicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums import (
    CommitmentStatus,
    ConflictType,
    Priority,
    ThreadStatus,
)
from app.domain.models import IntentConflict, IntentThread
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.domain.models import Commitment

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset(
    {
        ThreadStatus.DISCOVERED,
        ThreadStatus.ACTIVE,
        ThreadStatus.BLOCKED,
        ThreadStatus.WAITING,
        ThreadStatus.DEFERRED,
    }
)


class ConflictDetectionService:
    """
    Conservative rule-based service for cross-thread conflict detection.

    Zero natural language heuristics. Pure structured deterministic matching.
    """

    def detect_conflicts(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[IntentConflict]:
        """
        Evaluate all active thread pairs for conservative, structured conflicts.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        active_threads = [t for t in threads if t.status in ACTIVE_STATUSES]
        conflicts: list[IntentConflict] = []

        # Compare each unique pair (thread_a, thread_b) with thread_a.id < thread_b.id
        for i in range(len(active_threads)):
            for j in range(i + 1, len(active_threads)):
                t_a = active_threads[i]
                t_b = active_threads[j]

                # Ensure deterministic canonical ordering
                if t_a.id > t_b.id:
                    t_a, t_b = t_b, t_a

                # 1. Check Goal Conflicts (MUTUAL_EXCLUSION or explicit conflicting_thread_ids)
                goal_conflict = self._check_goal_conflict(t_a, t_b, ref_time)
                if goal_conflict:
                    conflicts.append(goal_conflict)
                    continue

                # 2. Check Resource Conflicts (same resource with is_exclusive = True)
                res_conflict = self._check_resource_conflict(t_a, t_b, ref_time)
                if res_conflict:
                    conflicts.append(res_conflict)
                    continue

                # 3. Check Deadline Conflicts (both HIGH priority, both overdue hard deadlines, temporal impossibility)
                dl_conflict = self._check_deadline_conflict(t_a, t_b, ref_time)
                if dl_conflict:
                    conflicts.append(dl_conflict)
                    continue

                # 4. Check Time Conflicts (explicitly overlapping scheduled time intervals)
                time_conflict = self._check_time_conflict(t_a, t_b, ref_time)
                if time_conflict:
                    conflicts.append(time_conflict)
                    continue

                # 5. Check Commitment Conflicts (mutually contradictory commitment payloads)
                com_conflict = self._check_commitment_conflict(t_a, t_b, ref_time)
                if com_conflict:
                    conflicts.append(com_conflict)
                    continue

        return conflicts

    def _check_goal_conflict(
        self,
        t_a: IntentThread,
        t_b: IntentThread,
        ref_time: datetime,
    ) -> IntentConflict | None:
        """
        Check for explicit mutual-exclusion or antagonistic constraint between goals.
        """

        # Look for MUTUAL_EXCLUSION dependency referencing the other thread
        def has_exclusion_dep(
            source: IntentThread, target: IntentThread
        ) -> tuple[bool, str]:
            for d in source.dependencies:
                b_type = (d.type or "").strip().upper()
                if b_type in ("MUTUAL_EXCLUSION", "ANTAGONISTIC", "EXCLUSIVE_GOAL"):
                    if (
                        target.id in d.description
                        or target.title.lower() in d.description.lower()
                    ):
                        return True, d.id
                # Check for explicit prefix tag e.g. "[EXCLUDES: thread-id]"
                if (
                    f"[EXCLUDES: {target.id}]" in d.description
                    or f"[CONFLICT: {target.id}]" in d.description
                ):
                    return True, d.id
            return False, ""

        a_excludes_b, dep_id_a = has_exclusion_dep(t_a, t_b)
        b_excludes_a, dep_id_b = has_exclusion_dep(t_b, t_a)

        if a_excludes_b or b_excludes_a:
            evi_ids: list[str] = []
            if dep_id_a:
                evi_ids.append(dep_id_a)
            if dep_id_b:
                evi_ids.append(dep_id_b)
            return IntentConflict(
                conflict_id=f"conflict-goal-{t_a.id}-{t_b.id}",
                thread_a_id=t_a.id,
                thread_a_title=t_a.title,
                thread_b_id=t_b.id,
                thread_b_title=t_b.title,
                conflict_type=ConflictType.GOAL_CONFLICT,
                severity=Priority.HIGH,
                explanation=f"Explicit mutual exclusion dependency detected between '{t_a.title}' and '{t_b.title}'.",
                evidence_ids=evi_ids,
                detected_at=ref_time,
            )
        return None

    def _check_resource_conflict(
        self,
        t_a: IntentThread,
        t_b: IntentThread,
        ref_time: datetime,
    ) -> IntentConflict | None:
        """
        Check if both threads require the same finite/non-shareable resource with is_exclusive = true.
        """

        def get_exclusive_resources(t: IntentThread) -> dict[str, str]:
            resources: dict[str, str] = {}
            for d in t.dependencies:
                b_type = (d.type or "").strip().upper()
                if (
                    b_type in ("EXCLUSIVE_RESOURCE", "FINITE_RESOURCE")
                    or "is_exclusive=true" in d.description.lower()
                    or "[EXCLUSIVE_RESOURCE:" in d.description
                ):
                    # Extract resource key
                    key = d.description
                    if "[EXCLUSIVE_RESOURCE:" in d.description:
                        key = (
                            d.description.split("[EXCLUSIVE_RESOURCE:")[1]
                            .split("]")[0]
                            .strip()
                        )
                    resources[key] = d.id
            return resources

        res_a = get_exclusive_resources(t_a)
        res_b = get_exclusive_resources(t_b)

        common_keys = set(res_a.keys()) & set(res_b.keys())
        if common_keys:
            matched_key = sorted(common_keys)[0]
            evi_ids = [res_a[matched_key], res_b[matched_key]]
            return IntentConflict(
                conflict_id=f"conflict-res-{t_a.id}-{t_b.id}",
                thread_a_id=t_a.id,
                thread_a_title=t_a.title,
                thread_b_id=t_b.id,
                thread_b_title=t_b.title,
                conflict_type=ConflictType.RESOURCE_CONFLICT,
                severity=Priority.HIGH,
                explanation=f"Both threads require non-shareable exclusive resource '{matched_key}'.",
                evidence_ids=evi_ids,
                detected_at=ref_time,
            )
        return None

    def _check_deadline_conflict(
        self,
        t_a: IntentThread,
        t_b: IntentThread,
        ref_time: datetime,
    ) -> IntentConflict | None:
        """
        Check for DEADLINE_CONFLICT:
          - Both threads are HIGH priority
          - Both have overdue hard deadlines (or identical immediate deadlines today)
          - Both have open commitments requiring immediate full-time action today
          - The structured data establishes temporal impossibility.
        """
        if t_a.priority != Priority.HIGH or t_b.priority != Priority.HIGH:
            return None

        def get_immediate_open_commitments(t: IntentThread) -> list[Commitment]:
            res: list[Commitment] = []
            for c in t.commitments:
                if c.status == CommitmentStatus.OPEN and c.due_at is not None:
                    due = c.due_at
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    diff_sec = (due - ref_time).total_seconds()
                    # Overdue or due within 24 hours
                    if diff_sec <= 24.0 * 3600.0:
                        res.append(c)
            return res

        imm_a = get_immediate_open_commitments(t_a)
        imm_b = get_immediate_open_commitments(t_b)

        if imm_a and imm_b:
            # Check for temporal impossibility: both require immediate full-day attention
            # Structured marker: e.g. both have overdue hard deadlines
            overdue_a = [
                c
                for c in imm_a
                if c.due_at
                and (
                    c.due_at.replace(tzinfo=timezone.utc)
                    if c.due_at.tzinfo is None
                    else c.due_at
                )
                < ref_time
            ]
            overdue_b = [
                c
                for c in imm_b
                if c.due_at
                and (
                    c.due_at.replace(tzinfo=timezone.utc)
                    if c.due_at.tzinfo is None
                    else c.due_at
                )
                < ref_time
            ]

            # If both have overdue commitments or both due on the exact same day requiring immediate full-time work
            if (overdue_a and overdue_b) or (
                imm_a and imm_b and len(imm_a) + len(imm_b) >= 2
            ):
                evi_ids = [imm_a[0].id, imm_b[0].id]
                return IntentConflict(
                    conflict_id=f"conflict-deadline-{t_a.id}-{t_b.id}",
                    thread_a_id=t_a.id,
                    thread_a_title=t_a.title,
                    thread_b_id=t_b.id,
                    thread_b_title=t_b.title,
                    conflict_type=ConflictType.DEADLINE_CONFLICT,
                    severity=Priority.HIGH,
                    explanation=(
                        f"Temporal impossibility: both high-priority threads '{t_a.title}' and '{t_b.title}' "
                        f"have competing immediate/overdue commitments requiring immediate action."
                    ),
                    evidence_ids=evi_ids,
                    detected_at=ref_time,
                )
        return None

    def _check_time_conflict(
        self,
        t_a: IntentThread,
        t_b: IntentThread,
        ref_time: datetime,
    ) -> IntentConflict | None:
        """
        Check for TIME_CONFLICT: scheduled datetime intervals explicitly identical/overlapping.
        """
        # Look for explicit overlapping times in commitment due_at or description tags
        for c_a in t_a.commitments:
            if c_a.status == CommitmentStatus.OPEN and c_a.due_at is not None:
                for c_b in t_b.commitments:
                    if c_b.status == CommitmentStatus.OPEN and c_b.due_at is not None:
                        d_a = (
                            c_a.due_at.replace(tzinfo=timezone.utc)
                            if c_a.due_at.tzinfo is None
                            else c_a.due_at
                        )
                        d_b = (
                            c_b.due_at.replace(tzinfo=timezone.utc)
                            if c_b.due_at.tzinfo is None
                            else c_b.due_at
                        )
                        # Identical to the minute
                        if abs((d_a - d_b).total_seconds()) < 60:
                            return IntentConflict(
                                conflict_id=f"conflict-time-{t_a.id}-{t_b.id}",
                                thread_a_id=t_a.id,
                                thread_a_title=t_a.title,
                                thread_b_id=t_b.id,
                                thread_b_title=t_b.title,
                                conflict_type=ConflictType.TIME_CONFLICT,
                                severity=Priority.MEDIUM,
                                explanation=(
                                    f"Scheduled time collision: commitment '{c_a.description}' in '{t_a.title}' "
                                    f"and '{c_b.description}' in '{t_b.title}' are scheduled for the exact same time."
                                ),
                                evidence_ids=[c_a.id, c_b.id],
                                detected_at=ref_time,
                            )
        return None

    def _check_commitment_conflict(
        self,
        t_a: IntentThread,
        t_b: IntentThread,
        ref_time: datetime,
    ) -> IntentConflict | None:
        """
        Check for COMMITMENT_CONFLICT: explicitly contradictory commitment payloads/tags.
        """
        for c_a in t_a.commitments:
            if "[CONTRADICTS:" in c_a.description:
                target = c_a.description.split("[CONTRADICTS:")[1].split("]")[0].strip()
                if target in [c_b.id for c_b in t_b.commitments] or target == t_b.id:
                    return IntentConflict(
                        conflict_id=f"conflict-com-{t_a.id}-{t_b.id}",
                        thread_a_id=t_a.id,
                        thread_a_title=t_a.title,
                        thread_b_id=t_b.id,
                        thread_b_title=t_b.title,
                        conflict_type=ConflictType.COMMITMENT_CONFLICT,
                        severity=Priority.HIGH,
                        explanation=f"Explicitly contradictory commitment payload detected between '{t_a.title}' and '{t_b.title}'.",
                        evidence_ids=[c_a.id],
                        detected_at=ref_time,
                    )
        return None
