"""
What-If Scenario Simulation Service for Threadback (M15).

Deterministic, read-only counterfactual reasoning engine.
Simulates consequence deltas on urgency, attention, decay, deadlines, blockers,
and cross-thread conflicts without modifying internal or external persistent state.

Mandatory Invariant:
  SIMULATION — NO STATE CHANGED.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.enums import (
    DependencyStatus,
    ResumeEligibility,
    WhatIfScenarioType,
)
from app.domain.models import (
    IntentThread,
    WhatIfSimulationResult,
)
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME
from app.services.attention_engine import AttentionEngine
from app.services.conflict_service import ConflictDetectionService
from app.services.intent_radar_service import IntentRadarService
from app.services.resume_service import ResumeEligibilityService

logger = logging.getLogger(__name__)


class WhatIfService:
    """
    Deterministic scenario simulation service.

    Evaluates hypothetical operations on an IntentThread in a clean,
    deep-copied environment to predict state consequences without persistence side-effects.
    """

    def __init__(
        self,
        radar_service: IntentRadarService | None = None,
        attention_engine: AttentionEngine | None = None,
        resume_service: ResumeEligibilityService | None = None,
        conflict_service: ConflictDetectionService | None = None,
    ) -> None:
        self._radar_service = radar_service or IntentRadarService()
        self._attention_engine = attention_engine or AttentionEngine(
            radar_service=self._radar_service
        )
        self._resume_service = resume_service or ResumeEligibilityService()
        self._conflict_service = conflict_service or ConflictDetectionService()

    def simulate(
        self,
        thread: IntentThread,
        scenario: WhatIfScenarioType | str,
        parameters: dict[str, Any] | None = None,
        reference_time: datetime | None = None,
        all_threads: list[IntentThread] | None = None,
    ) -> WhatIfSimulationResult:
        """
        Execute a deterministic read-only simulation on a thread clone.

        Args:
            thread: Target IntentThread (will NOT be mutated).
            scenario: WhatIfScenarioType or string identifier.
            parameters: Optional parameter dictionary (e.g. {'days': 7}).
            reference_time: Evaluation anchor datetime.
            all_threads: Optional landscape context to evaluate cross-thread impacts.

        Returns:
            WhatIfSimulationResult containing before/after deltas and factual impact notes.
        """
        params = parameters or {}
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Parse scenario type
        if isinstance(scenario, WhatIfScenarioType):
            scen_type = scenario
        else:
            try:
                scen_type = WhatIfScenarioType(scenario.upper())
            except ValueError:
                scen_type = WhatIfScenarioType.IGNORE_TEMPORARILY

        # Baseline evaluation on un-mutated thread
        base_radar = self._radar_service.compute_radar_item(
            thread, reference_time=ref_time
        )
        base_candidate = self._attention_engine.evaluate_thread(
            thread, reference_time=ref_time
        )
        orig_urgency = base_radar.urgency_score
        orig_attention = base_candidate.attention_score
        orig_decay_state = base_radar.decay_state.value

        # Create isolated clone for simulation
        sim_thread = thread.model_copy(deep=True)
        sim_ref_time = ref_time
        affected_threads: list[str] = []

        deadline_impact = "No direct deadline impact."
        blocker_impact = "No blocker changes simulated."
        resumability_impact = "Resumability unaffected."

        if scen_type in (
            WhatIfScenarioType.IGNORE_TEMPORARILY,
            WhatIfScenarioType.POSTPONE,
        ):
            days = int(params.get("days", 7))
            sim_ref_time = ref_time + timedelta(days=days)

            # Check commitment deadline lapse
            overdue_soon = [
                c
                for c in sim_thread.commitments
                if c.due_at
                and (
                    c.due_at.replace(tzinfo=timezone.utc)
                    if c.due_at.tzinfo is None
                    else c.due_at
                )
                <= sim_ref_time
            ]
            if overdue_soon:
                deadline_impact = f"Postponing by {days} day(s) causes {len(overdue_soon)} commitment(s) to become overdue or enter critical window."
            else:
                deadline_impact = f"Postponing by {days} day(s) advances time with no overdue commitments."

            if scen_type == WhatIfScenarioType.POSTPONE:
                sim_thread.deferred_until = sim_ref_time
                resumability_impact = f"Thread deferred until {sim_ref_time.strftime('%Y-%m-%d')}. Not eligible for resumption until that date."

        elif scen_type == WhatIfScenarioType.RESOLVE_BLOCKER:
            target_dep_id = params.get("dependency_id")
            resolved_count = 0
            for dep in sim_thread.dependencies:
                if (
                    target_dep_id is None or dep.id == target_dep_id
                ) and dep.is_active_blocker:
                    dep.status = DependencyStatus.RESOLVED
                    dep.blocking = False
                    resolved_count += 1
                    if target_dep_id is not None:
                        break

            if resolved_count > 0:
                blocker_impact = f"Simulated resolution of {resolved_count} active blocker(s) resolved. Blocker pressure reduced."
                # Check resume eligibility under simulated state
                resume_eval = self._resume_service.evaluate_thread(
                    sim_thread, reference_time=ref_time
                )
                if resume_eval.eligibility == ResumeEligibility.RESUMABLE:
                    resumability_impact = (
                        f"Thread becomes RESUMABLE: {resume_eval.reason}"
                    )
                else:
                    resumability_impact = f"Resume status: {resume_eval.eligibility.value} ({resume_eval.reason})"
            else:
                blocker_impact = "No active blockers were found to resolve."

        elif scen_type == WhatIfScenarioType.CHANGE_GOAL:
            new_goal = params.get("new_goal", "Refined strategic objective")
            sim_thread.current_goal = new_goal
            blocker_impact = "Goal updated in simulation; existing blockers remain anchored to current tasks."
            deadline_impact = (
                "Commitment alignment should be reviewed against the updated goal."
            )

        # Evaluate simulated clone under simulated anchor
        sim_radar = self._radar_service.compute_radar_item(
            sim_thread, reference_time=sim_ref_time
        )
        sim_candidate = self._attention_engine.evaluate_thread(
            sim_thread, reference_time=sim_ref_time
        )
        sim_urgency = sim_radar.urgency_score
        sim_attention = sim_candidate.attention_score
        sim_decay_state = sim_radar.decay_state.value

        # Conservative Cross-Thread Consequence Rule:
        # Cross-thread consequences may ONLY be reported when an explicit structured relationship exists:
        # 1. Explicit Dependency: other_thread depends on thread or thread depends on other_thread.
        # 2. Explicit Conflict: an explicit IntentConflict exists (e.g. resource or time conflict).
        # 3. Explicit Commitment/Dependency relationship.
        # Natural language similarity alone MUST NEVER trigger cross-thread consequences.
        relationship_evidence: list[str] = []
        if all_threads:
            affected_threads, relationship_evidence = (
                self._evaluate_cross_thread_consequences(
                    sim_thread=sim_thread,
                    all_threads=all_threads,
                    ref_time=ref_time,
                    sim_ref_time=sim_ref_time,
                )
            )

        # Build concise executive simulation summary
        urg_delta = sim_urgency - orig_urgency
        att_delta = sim_attention - orig_attention
        urg_change_str = f"{urg_delta:+.2f}"
        att_change_str = f"{att_delta:+.2f}"

        summary_parts = [
            f"Simulation ({scen_type.value}):",
            f"Urgency shifts from {orig_urgency:.2f} to {sim_urgency:.2f} ({urg_change_str});",
            f"Attention shifts from {orig_attention:.2f} to {sim_attention:.2f} ({att_change_str});",
            f"Decay state: {orig_decay_state} → {sim_decay_state}.",
            deadline_impact,
            blocker_impact,
        ]
        if affected_threads:
            summary_parts.append(
                f"Affected related threads: {', '.join(affected_threads)} ({relationship_evidence[0]})."
            )
        else:
            summary_parts.append(
                "No cross-thread consequences detected (no explicit structured relationships)."
            )

        simulation_summary = " ".join(summary_parts)

        return WhatIfSimulationResult(
            scenario_type=scen_type,
            thread_id=thread.id,
            thread_title=thread.title,
            parameters=params,
            original_urgency=round(orig_urgency, 4),
            simulated_urgency=round(sim_urgency, 4),
            original_attention=round(orig_attention, 4),
            simulated_attention=round(sim_attention, 4),
            original_decay_state=orig_decay_state,
            simulated_decay_state=sim_decay_state,
            deadline_impact_description=deadline_impact,
            blocker_impact_description=blocker_impact,
            resumability_impact_description=resumability_impact,
            affected_related_thread_ids=affected_threads,
            relationship_evidence=relationship_evidence,
            simulation_summary=simulation_summary,
            label="SIMULATION — NO STATE CHANGED",
            simulated_at=ref_time,
        )

    def _evaluate_cross_thread_consequences(
        self,
        sim_thread: IntentThread,
        all_threads: list[IntentThread],
        ref_time: datetime,
        sim_ref_time: datetime,
    ) -> tuple[list[str], list[str]]:
        """
        Conservative deterministic evaluation of cross-thread consequences.

        Cross-thread consequences may ONLY be reported when an explicit structured relationship exists:
          1. Explicit dependency relationship (e.g., target_thread_id, dep.id prefix, or explicit [thread_id] tag).
          2. Explicit conflict relationship (e.g., TIME_CONFLICT, RESOURCE_CONFLICT, or GOAL_CONFLICT from ConflictDetectionService).
          3. Explicit commitment relationship (shared exclusive resource or explicit commitment target).

        Natural language similarity alone MUST NEVER trigger cross-thread consequences.
        If no explicit structured relationship exists, returns ([], []).
        """
        other_threads = [t for t in all_threads if t.id != sim_thread.id]
        if not other_threads:
            return [], []

        affected_threads: list[str] = []
        relationship_evidence: list[str] = []

        # 1. Detect explicit conflicts involving sim_thread
        sim_landscape = other_threads + [sim_thread]
        sim_conflicts = self._conflict_service.detect_conflicts(
            sim_landscape, reference_time=sim_ref_time
        )

        for sc in sim_conflicts:
            if sc.thread_a_id == sim_thread.id or sc.thread_b_id == sim_thread.id:
                other_id = (
                    sc.thread_b_id
                    if sc.thread_a_id == sim_thread.id
                    else sc.thread_a_id
                )
                if other_id not in affected_threads:
                    affected_threads.append(other_id)
                    relationship_evidence.append(
                        f"Explicit conflict ({sc.conflict_type.value}): {sc.explanation}"
                    )

        # 2. Check explicit dependencies
        for ot in other_threads:
            # Does ot have a structured dependency on sim_thread?
            for dep in ot.dependencies:
                dep_id_lower = dep.id.lower()
                dep_desc_lower = dep.description.lower()
                target_token = sim_thread.id.lower()
                if (
                    dep.id == f"dep-{sim_thread.id}"
                    or dep.id == sim_thread.id
                    or target_token in dep_id_lower
                    or f"thread:{target_token}" in dep_desc_lower
                    or f"[{target_token}]" in dep_desc_lower
                ):
                    if ot.id not in affected_threads:
                        affected_threads.append(ot.id)
                        relationship_evidence.append(
                            f"Explicit dependency: Thread '{ot.title}' depends on '{sim_thread.title}' ({dep.description})"
                        )
                    break

            # Does sim_thread have a structured dependency on ot?
            for dep in sim_thread.dependencies:
                dep_id_lower = dep.id.lower()
                dep_desc_lower = dep.description.lower()
                target_token = ot.id.lower()
                if (
                    dep.id == f"dep-{ot.id}"
                    or dep.id == ot.id
                    or target_token in dep_id_lower
                    or f"thread:{target_token}" in dep_desc_lower
                    or f"[{target_token}]" in dep_desc_lower
                ):
                    if ot.id not in affected_threads:
                        affected_threads.append(ot.id)
                        relationship_evidence.append(
                            f"Explicit dependency: Thread '{sim_thread.title}' depends on '{ot.title}' ({dep.description})"
                        )
                    break

        return affected_threads, relationship_evidence
