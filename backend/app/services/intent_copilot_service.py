"""
Intent Copilot Master Service for Threadback (M15).

Unifies:
  - M13 Intent Memory & Urgency
  - M14 Attention Engine, WhyNow, Change Analysis, Resume Eligibility & Conflicts
  - M15 What-If Simulation, Time-Budget Planning & Safe Closure Assistant

Adheres strictly to deterministic, explainable, evidence-grounded principles.
Distinguishes Urgency (execution pressure) from Attention (cognitive salience).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.domain.enums import (
    DecisionCardType,
    ResumeEligibility,
    ThreadStatus,
)
from app.domain.models import (
    IntentCopilotOverview,
    IntentDecisionCard,
    IntentThread,
    PrioritizedThreadSummary,
)
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME
from app.services.attention_engine import AttentionEngine
from app.services.change_analysis_service import ChangeAnalysisService
from app.services.conflict_service import ConflictDetectionService
from app.services.intent_radar_service import IntentRadarService
from app.services.next_action_service import NextActionService
from app.services.resume_service import ResumeEligibilityService
from app.services.safe_closure_assistant import SafeClosureAssistant
from app.services.time_budget_service import TimeBudgetService
from app.services.verification_service import VerificationService
from app.services.what_if_service import WhatIfService
from app.services.why_now_service import WhyNowService

logger = logging.getLogger(__name__)


class IntentCopilotService:
    """
    Master Intent Copilot domain service orchestrating proactive guidance.
    """

    def __init__(
        self,
        radar_service: IntentRadarService | None = None,
        attention_engine: AttentionEngine | None = None,
        why_now_service: WhyNowService | None = None,
        change_service: ChangeAnalysisService | None = None,
        resume_service: ResumeEligibilityService | None = None,
        conflict_service: ConflictDetectionService | None = None,
        next_action_service: NextActionService | None = None,
        verification_service: VerificationService | None = None,
        what_if_service: WhatIfService | None = None,
        time_budget_service: TimeBudgetService | None = None,
        closure_assistant: SafeClosureAssistant | None = None,
    ) -> None:
        self._radar_service = radar_service or IntentRadarService()
        self._attention_engine = attention_engine or AttentionEngine(
            radar_service=self._radar_service
        )
        self._why_now_service = why_now_service or WhyNowService()
        self._change_service = change_service or ChangeAnalysisService()
        self._resume_service = resume_service or ResumeEligibilityService()
        self._conflict_service = conflict_service or ConflictDetectionService()
        self._next_action_service = next_action_service or NextActionService()
        self._verification_service = verification_service or VerificationService()

        self._what_if_service = what_if_service or WhatIfService(
            radar_service=self._radar_service,
            attention_engine=self._attention_engine,
            resume_service=self._resume_service,
            conflict_service=self._conflict_service,
        )
        self._time_budget_service = time_budget_service or TimeBudgetService(
            next_action_service=self._next_action_service,
            attention_engine=self._attention_engine,
        )
        self._closure_assistant = closure_assistant or SafeClosureAssistant(
            verification_service=self._verification_service
        )

    # -----------------------------------------------------------------------
    # Sub-service accessors
    # -----------------------------------------------------------------------
    @property
    def what_if_service(self) -> WhatIfService:
        return self._what_if_service

    @property
    def time_budget_service(self) -> TimeBudgetService:
        return self._time_budget_service

    @property
    def closure_assistant(self) -> SafeClosureAssistant:
        return self._closure_assistant

    # -----------------------------------------------------------------------
    # 1. Explainable Prioritization (What should I do first?)
    # -----------------------------------------------------------------------
    def prioritize_threads(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
    ) -> list[PrioritizedThreadSummary]:
        """
        Rank actionable threads clearly distinguishing Urgency vs Attention.

        Urgency: time/execution pressure (from M13 radar).
        Attention: cognitive importance & change salience (from M14 engine).
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        active = [
            t
            for t in threads
            if t.status
            in (
                ThreadStatus.ACTIVE,
                ThreadStatus.BLOCKED,
                ThreadStatus.WAITING,
                ThreadStatus.DISCOVERED,
            )
        ]
        if not active:
            return []

        candidates = self._attention_engine.evaluate_threads(
            active, reference_time=ref_time
        )
        priorities: list[PrioritizedThreadSummary] = []

        for idx, cand in enumerate(candidates, start=1):
            thread = next((t for t in active if t.id == cand.thread_id), None)
            if not thread:
                continue

            next_step = self._next_action_service.suggest_action(thread).action

            # Identify why it ranks high
            factors = []
            if cand.urgency_score >= 0.70:
                factors.append(f"high urgency ({cand.urgency_score:.2f})")
            if cand.blocker_ids:
                factors.append(f"{len(cand.blocker_ids)} active blocker(s)")
            if cand.supporting_commitment_ids:
                factors.append(
                    f"{len(cand.supporting_commitment_ids)} open commitment(s)"
                )
            if not factors:
                factors.append(f"attention score of {cand.attention_score:.2f}")

            why_text = f"Ranked #{idx} due to {', '.join(factors)}. {cand.human_readable_explanation}"

            # Extract signal components
            blk_pressure, _, _ = self._attention_engine.compute_blocker_pressure(thread)
            blocker_pres = round(blk_pressure, 2)

            decay_signal = self._radar_service.compute_decay_signal(
                thread, reference_time=ref_time
            )
            s_deadline = 0.2
            if decay_signal.days_until_deadline is not None:
                dd = decay_signal.days_until_deadline
                if dd < 0:
                    s_deadline = 1.0
                elif dd <= 1.0:
                    s_deadline = 0.9
                elif dd <= 3.0:
                    s_deadline = 0.6
                elif dd <= 7.0:
                    s_deadline = 0.3
            deadline_pres = round(s_deadline, 2)

            priorities.append(
                PrioritizedThreadSummary(
                    rank=idx,
                    thread_id=thread.id,
                    thread_title=thread.title,
                    priority=thread.priority,
                    attention_level=cand.attention_level,
                    urgency_score=round(cand.urgency_score, 4),
                    attention_score=round(cand.attention_score, 4),
                    blocker_pressure=blocker_pres,
                    deadline_pressure=deadline_pres,
                    why_it_ranks_high=why_text,
                    recommended_next_step=next_step,
                )
            )

        return priorities

    # -----------------------------------------------------------------------
    # 2. Intent Decision Cards Generation
    # -----------------------------------------------------------------------
    def generate_decision_cards(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
        conversation_id: str | None = None,
    ) -> list[IntentDecisionCard]:
        """
        Generate structured conversational decision cards across all intelligence categories.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        cards: list[IntentDecisionCard] = []

        # 1. TOP_PRIORITY Card
        ranked = self.prioritize_threads(threads, reference_time=ref_time)
        if ranked:
            top = ranked[0]
            cards.append(
                IntentDecisionCard(
                    card_id=f"card-top-{top.thread_id}",
                    card_type=DecisionCardType.TOP_PRIORITY,
                    thread_id=top.thread_id,
                    thread_title=top.thread_title,
                    title=f"Top Priority: {top.thread_title}",
                    summary=f"Requires your primary attention. Urgency: {top.urgency_score:.2f}, Attention: {top.attention_score:.2f}. {top.why_it_ranks_high}",
                    evidence_snippets=[top.recommended_next_step],
                    recommended_action=top.recommended_next_step,
                    attention_level=top.attention_level,
                    urgency_score=top.urgency_score,
                    attention_score=top.attention_score,
                    metadata={"rank": 1},
                    created_at=ref_time,
                )
            )

        # 2. WHY_NOW Card
        if ranked:
            top_th = next((t for t in threads if t.id == ranked[0].thread_id), None)
            if top_th:
                why_now = self._why_now_service.explain(top_th, reference_time=ref_time)
                if why_now.has_reason:
                    cards.append(
                        IntentDecisionCard(
                            card_id=f"card-why-{top_th.id}",
                            card_type=DecisionCardType.WHY_NOW,
                            thread_id=top_th.id,
                            thread_title=top_th.title,
                            title=f"Why Now: {top_th.title}",
                            summary=why_now.concise_alexa_text,
                            evidence_snippets=why_now.contributing_factors,
                            recommended_action=ranked[0].recommended_next_step,
                            attention_level=ranked[0].attention_level,
                            urgency_score=ranked[0].urgency_score,
                            attention_score=ranked[0].attention_score,
                            created_at=ref_time,
                        )
                    )

        # 3. WHAT_CHANGED Card
        for t in threads:
            delta = self._change_service.analyze_changes(
                t, conversation_id=conversation_id, reference_time=ref_time
            )
            if delta.changes:
                cards.append(
                    IntentDecisionCard(
                        card_id=f"card-change-{t.id}",
                        card_type=DecisionCardType.WHAT_CHANGED,
                        thread_id=t.id,
                        thread_title=t.title,
                        title=f"What Changed: {t.title}",
                        summary=f"{len(delta.changes)} recent state change(s) detected since last checkpoint.",
                        evidence_snippets=[c.description for c in delta.changes[:3]],
                        recommended_action="Review recent changes or verify completion status.",
                        created_at=ref_time,
                    )
                )
                break  # Show the most salient change card

        # 4. RESUME Card (for deferred threads)
        for t in threads:
            if t.status == ThreadStatus.DEFERRED:
                eval_res = self._resume_service.evaluate_thread(
                    t, reference_time=ref_time
                )
                if eval_res.eligibility == ResumeEligibility.RESUMABLE:
                    cards.append(
                        IntentDecisionCard(
                            card_id=f"card-resume-{t.id}",
                            card_type=DecisionCardType.RESUME,
                            thread_id=t.id,
                            thread_title=t.title,
                            title=f"Ready to Resume: {t.title}",
                            summary=f"Deferred intention is now eligible to resume. {eval_res.reason}",
                            evidence_snippets=eval_res.supporting_evidence_ids,
                            recommended_action=f"Ask 'Continue my {t.title.lower()}' to safely prepare resumption.",
                            metadata={"eligibility": eval_res.eligibility.value},
                            created_at=ref_time,
                        )
                    )
                    break

        # 5. SAFE_TO_CLOSE Card
        closable = self._closure_assistant.evaluate_threads(threads)
        safe_closable = [c for c in closable if c.is_safe_to_close]
        if safe_closable:
            c_top = safe_closable[0]
            cards.append(
                IntentDecisionCard(
                    card_id=f"card-close-{c_top.thread_id}",
                    card_type=DecisionCardType.SAFE_TO_CLOSE,
                    thread_id=c_top.thread_id,
                    thread_title=c_top.thread_title,
                    title=f"Safe to Close: {c_top.thread_title}",
                    summary=c_top.closure_readiness_reason,
                    evidence_snippets=[
                        f"Evidence count: {c_top.completion_evidence_count}"
                    ],
                    recommended_action=c_top.next_step,
                    created_at=ref_time,
                )
            )

        # 6. CONFLICT Card
        conflicts = self._conflict_service.detect_conflicts(
            threads, reference_time=ref_time
        )
        if conflicts:
            conf = conflicts[0]
            cards.append(
                IntentDecisionCard(
                    card_id=f"card-conf-{conf.conflict_id}",
                    card_type=DecisionCardType.CONFLICT,
                    thread_id=conf.thread_a_id,
                    thread_title=conf.thread_a_title,
                    title=f"Conflict Detected: {conf.conflict_type.value}",
                    summary=conf.explanation,
                    evidence_snippets=conf.evidence_ids,
                    recommended_action="Resolve scheduled time slot or resource overlap.",
                    metadata={
                        "conflict_type": conf.conflict_type.value,
                        "conflict_id": conf.conflict_id,
                    },
                    created_at=ref_time,
                )
            )

        # 7. TIME_BUDGET Card (preset 30 minutes)
        budget_plan = self._time_budget_service.recommend(
            threads, available_minutes=30, reference_time=ref_time
        )
        if budget_plan.selected_thread_id != "none":
            cards.append(
                IntentDecisionCard(
                    card_id=f"card-budget-{budget_plan.selected_thread_id}",
                    card_type=DecisionCardType.TIME_BUDGET,
                    thread_id=budget_plan.selected_thread_id,
                    thread_title=budget_plan.selected_thread_title,
                    title=f"30-Minute Plan: {budget_plan.selected_thread_title}",
                    summary=budget_plan.reason,
                    evidence_snippets=[budget_plan.expected_next_action],
                    recommended_action=budget_plan.expected_next_action,
                    metadata={
                        "available_minutes": 30,
                        "fits_budget": budget_plan.fits_budget,
                    },
                    created_at=ref_time,
                )
            )

        return cards

    # -----------------------------------------------------------------------
    # 3. Comprehensive Copilot Overview
    # -----------------------------------------------------------------------
    def generate_overview(
        self,
        threads: list[IntentThread],
        reference_time: datetime | None = None,
        conversation_id: str | None = None,
    ) -> IntentCopilotOverview:
        """
        Generate full Copilot overview for the Intent Copilot frontend workspace.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        priorities = self.prioritize_threads(threads, reference_time=ref_time)
        cards = self.generate_decision_cards(
            threads, reference_time=ref_time, conversation_id=conversation_id
        )

        # Resumables
        deferred = [t for t in threads if t.status == ThreadStatus.DEFERRED]
        resumables = [
            self._resume_service.evaluate_thread(t, reference_time=ref_time)
            for t in deferred
        ]

        # Closable
        closable = self._closure_assistant.evaluate_threads(threads)

        # Build primary voice recommendation
        if priorities:
            top = priorities[0]
            voice = (
                f"You should deal with '{top.thread_title}' first. "
                f"It has high urgency ({top.urgency_score:.2f}) and attention ({top.attention_score:.2f}). "
                f"Recommended next step: {top.recommended_next_step}."
            )
        else:
            voice = "Your active intentions are in good standing with no urgent actions required."

        return IntentCopilotOverview(
            primary_recommendation=voice,
            ranked_priorities=priorities,
            decision_cards=cards,
            resumable_candidates=resumables,
            safe_closure_candidates=closable,
            alexa_voice_text=voice,
            generated_at=ref_time,
        )

    # -----------------------------------------------------------------------
    # 4. Resume Where I Left Off Formatter
    # -----------------------------------------------------------------------
    def format_resume_context(
        self,
        thread: IntentThread,
        reference_time: datetime | None = None,
    ) -> str:
        """
        Format comprehensive 'Where did I leave off?' state reconstruction.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME
        last_act = (
            thread.last_activity_at.strftime("%b %d, %Y")
            if thread.last_activity_at
            else "Unknown"
        )

        active_blockers = thread.active_blockers
        blocker_text = (
            f"Active blocker: '{active_blockers[0].description}'."
            if active_blockers
            else "No active blockers."
        )

        res_eval = self._resume_service.evaluate_thread(thread, reference_time=ref_time)
        next_step = self._next_action_service.suggest_action(thread).action

        lines = [
            f"Here is where you left off on **{thread.title}**:",
            f"• **Original Goal**: {thread.original_goal or thread.description}",
            f"• **Current Goal**: {thread.current_goal or thread.description}",
            f"• **Status**: {thread.status.value}",
            f"• **Last Activity**: {last_act}",
            f"• **Blockers**: {blocker_text}",
            f"• **Resume Eligibility**: {res_eval.eligibility.value} ({res_eval.reason})",
            f"• **Recommended Next Step**: {next_step}",
            "",
            "Would you like me to help you move this forward or simulate what happens next?",
        ]
        return "\n".join(lines)
