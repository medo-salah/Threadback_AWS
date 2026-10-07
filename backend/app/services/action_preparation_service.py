"""
Action Preparation & Confirmation Service for Threadback M6.

Converts a deterministic NextActionSuggestion (M5) into a structured,
human-reviewable ActionProposal.
Pre-execution planning only — does NOT execute actions, send messages,
call APIs, mutate state, or interact with external systems.
No LLM, no external APIs, no database, no random values.

Architecture Pipeline
---------------------
IntentThread
     ↓
AnalysisService.analyze() [M4]
     ↓
ThreadAnalysis
     ↓
NextActionService.suggest_action() [M5]
     ↓
NextActionSuggestion
     ↓
ActionPreparationService.prepare_action() [M6]
     ↓
ActionProposal
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.domain.enums import (
    NextActionType,
    ProposalStatus,
    RiskLevel,
)
from app.domain.models import ActionProposal
from app.services.analysis_service import DEFAULT_ANALYSIS_REFERENCE_TIME

if TYPE_CHECKING:
    from app.domain.models import (
        Dependency,
        IntentThread,
        NextActionSuggestion,
    )
    from app.repositories.base import BaseThreadRepository
    from app.services.proposal_registry import ProposalRegistry

# Keywords indicating potentially consequential external side effects (HIGH risk)
HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "pay",
    "payment",
    "charge",
    "wire",
    "refund",
    "cancel",
    "cancellation",
    "terminate",
    "final submission",
    "irreversible",
    "delete",
)

# Regex patterns to extract recipient names from dependency or evidence descriptions
RECIPIENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfrom\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
    re.compile(r"\bsent\s+to\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
    re.compile(r"\bwith\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
    re.compile(r"\bfor\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
    re.compile(r"\bcontact\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
    re.compile(r"\bask\s+([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)\b"),
)


def _extract_recipient(
    thread: IntentThread,
    dep: Dependency | None = None,
) -> str | None:
    """
    Deterministically extract the recipient party from existing domain data.

    Inspects:
      1. Target dependency description (if provided)
      2. Supporting evidence descriptions
      3. Thread description

    Does NOT invent or guess names; returns None if unavailable.
    """
    texts_to_scan: list[str] = []
    if dep is not None:
        texts_to_scan.append(dep.description)
    for e in thread.evidence:
        texts_to_scan.append(e.description)
    texts_to_scan.append(thread.description)

    for text in texts_to_scan:
        for pat in RECIPIENT_PATTERNS:
            match = pat.search(text)
            if match:
                extracted = match.group(1).strip()
                # Ignore generic nouns captured by capitalization at sentence starts
                if extracted.lower() not in (
                    "academic",
                    "draft",
                    "completed",
                    "application",
                    "preliminary",
                    "review",
                    "the",
                    "a",
                    "an",
                ):
                    return extracted
    return None


def _classify_risk_level(
    action_type: NextActionType,
    text: str,
    requires_confirmation: bool,
) -> RiskLevel:
    """
    Deterministically classify the risk level of an action proposal.

    LOW: Internal, reversible, informational preparation (e.g. review, checklist, no-action).
    MEDIUM: Potential external communication or reversible external change (e.g. email, message).
    HIGH: Potentially consequential external side effect (e.g. payment, cancellation, submission).
    """
    lower = text.lower()
    if any(kw in lower for kw in HIGH_RISK_KEYWORDS):
        return RiskLevel.HIGH

    if action_type in (
        NextActionType.GATHER_EVIDENCE_ACTION,
        NextActionType.NO_ACTION,
    ):
        return RiskLevel.LOW

    if requires_confirmation or action_type in (
        NextActionType.FOLLOW_UP_ACTION,
        NextActionType.UNBLOCKER_ACTION,
    ):
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def derive_proposal_id(
    thread_id: str,
    action_type: NextActionType,
    supporting_evidence_ids: list[str],
    supporting_commitment_ids: list[str],
    supporting_dependency_ids: list[str],
    extra_payload: str = "",
) -> str:
    """Deterministically derive a unique, stable ActionProposal ID.

    Derivation inputs:
      1. thread_id
      2. action_type (enum string value)
      3. sorted supporting_evidence_ids
      4. sorted supporting_commitment_ids
      5. sorted supporting_dependency_ids
      6. optional extra_payload (for parameterized M13 mutations)

    Format:
      proposal-<16-character-sha256-hex>

    Guarantees:
      - 100% deterministic (no random UUIDs, no timestamps, no object IDs).
      - Derived solely from stable domain inputs.
      - Provides a stable reference for execution.
    """
    parts = [
        thread_id,
        action_type.value,
        ",".join(sorted(supporting_evidence_ids)),
        ",".join(sorted(supporting_commitment_ids)),
        ",".join(sorted(supporting_dependency_ids)),
    ]
    if extra_payload:
        parts.append(extra_payload)
    raw_material = ":".join(parts)
    digest = hashlib.sha256(raw_material.encode("utf-8")).hexdigest()[:16]
    return f"proposal-{digest}"


class ActionPreparationService:
    """Action Preparation & Confirmation Service for IntentThreads (M6 + M13).

    Consumes M5 NextActionSuggestion or M13 typed intent actions and prepares
    a transparent, structured ActionProposal ready for human review.
    Does NOT execute actions.
    """

    def __init__(
        self,
        registry: ProposalRegistry | None = None,
        repository: BaseThreadRepository | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository or (
            getattr(registry, "_repository", None) if registry else None
        )

    def prepare_action(
        self,
        thread: IntentThread,
        suggestion: NextActionSuggestion | None = None,
        reference_time: datetime | None = None,
        action_type: NextActionType | str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> ActionProposal:
        """
        Prepare a structured ActionProposal from a NextActionSuggestion or M13 typed action.

        Enforces:
          - Non-execution: proposal only.
          - Traceability: retains all supporting IDs from suggestion.
          - Confirmation invariant: requires_confirmation == True implies CONFIRMATION_REQUIRED
            unless proposal is BLOCKED.
          - Missing information handling: if essential information (such as recipient)
            is unknown, marks proposal as BLOCKED instead of fabricating facts.
          - Deterministic timestamps: uses reference_time anchor.

        Args:
            thread: The IntentThread being acted upon.
            suggestion: Optional M5 next-action recommendation.
            reference_time: Optional deterministic reference timestamp.
            action_type: Optional M13 typed action type (EVOLVE_INTENTION, DEFER_INTENTION, etc.).
            parameters: Optional parameter payload for typed actions.

        Returns:
            ActionProposal structured for human review.
        """
        ref_time = reference_time or DEFAULT_ANALYSIS_REFERENCE_TIME

        # Resolve typed action if specified
        resolved_action_type: NextActionType | None = None
        if action_type is not None:
            resolved_action_type = (
                action_type
                if isinstance(action_type, NextActionType)
                else NextActionType(action_type)
            )

        # -------------------------------------------------------------------
        # M13 Typed Mutation Actions
        # -------------------------------------------------------------------
        if resolved_action_type == NextActionType.EVOLVE_INTENTION:
            params = parameters or {}
            new_goal = (
                params.get("new_goal") or params.get("revised_goal") or ""
            ).strip()
            reason = (params.get("reason") or "User revised active objective").strip()
            if not new_goal:
                status = ProposalStatus.BLOCKED
                description = (
                    f"Cannot prepare intent evolution for '{thread.title}': "
                    "revised goal is missing."
                )
                rationale = "A clear revised goal is required for intent evolution."
                preconditions = ["Revised goal must be specified"]
                requires_confirmation = False
                confirmation_reason = "Missing revised goal."
            else:
                status = ProposalStatus.READY
                description = (
                    f"Update active goal for '{thread.title}' to '{new_goal}'. "
                    f"Reason: {reason}."
                )
                rationale = (
                    f"User instructed goal revision from "
                    f"'{thread.current_goal or thread.description}' to '{new_goal}'."
                )
                preconditions = [
                    "Thread must not be in terminal status (COMPLETED/ABANDONED)"
                ]
                requires_confirmation = False
                confirmation_reason = None

            proposal_id = derive_proposal_id(
                thread_id=thread.id,
                action_type=NextActionType.EVOLVE_INTENTION,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                extra_payload=new_goal,
            )
            proposal = ActionProposal(
                id=proposal_id,
                thread_id=thread.id,
                action_type=NextActionType.EVOLVE_INTENTION,
                title=f"Evolve goal: {new_goal}" if new_goal else "Evolve intention",
                description=description,
                rationale=rationale,
                status=status,
                requires_confirmation=requires_confirmation,
                confirmation_reason=confirmation_reason,
                inputs={"thread_id": thread.id, "new_goal": new_goal, "reason": reason},
                preconditions=preconditions,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                risk_level=RiskLevel.LOW,
                created_at=ref_time,
            )
            if self._repository is not None:
                self._repository.save_proposal(proposal)
            if self._registry is not None:
                self._registry.register(proposal)
            return proposal

        elif resolved_action_type == NextActionType.DEFER_INTENTION:
            params = parameters or {}
            deferred_until = params.get("deferred_until")
            reason = (params.get("reason") or "Postponed by user").strip()
            status = ProposalStatus.READY
            description = (
                f"Defer thread '{thread.title}' until {deferred_until or 'further notice'}. "
                f"Reason: {reason}."
            )
            rationale = f"User instructed thread postponement: {reason}."
            proposal_id = derive_proposal_id(
                thread_id=thread.id,
                action_type=NextActionType.DEFER_INTENTION,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                extra_payload=f"{deferred_until or ''}:{reason}",
            )
            proposal = ActionProposal(
                id=proposal_id,
                thread_id=thread.id,
                action_type=NextActionType.DEFER_INTENTION,
                title=f"Defer thread: {thread.title}",
                description=description,
                rationale=rationale,
                status=status,
                requires_confirmation=False,
                confirmation_reason=None,
                inputs={
                    "thread_id": thread.id,
                    "deferred_until": deferred_until,
                    "reason": reason,
                },
                preconditions=[
                    "Thread must not be in terminal status (COMPLETED/ABANDONED)"
                ],
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                risk_level=RiskLevel.LOW,
                created_at=ref_time,
            )
            if self._repository is not None:
                self._repository.save_proposal(proposal)
            if self._registry is not None:
                self._registry.register(proposal)
            return proposal

        elif resolved_action_type == NextActionType.RESUME_INTENTION:
            params = parameters or {}
            reason = (params.get("reason") or "Resumed by user").strip()
            status = ProposalStatus.READY
            description = (
                f"Resume thread '{thread.title}' back into active lifecycle. "
                f"Reason: {reason}."
            )
            rationale = f"User instructed thread reactivation: {reason}."
            proposal_id = derive_proposal_id(
                thread_id=thread.id,
                action_type=NextActionType.RESUME_INTENTION,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                extra_payload=reason,
            )
            proposal = ActionProposal(
                id=proposal_id,
                thread_id=thread.id,
                action_type=NextActionType.RESUME_INTENTION,
                title=f"Resume thread: {thread.title}",
                description=description,
                rationale=rationale,
                status=status,
                requires_confirmation=False,
                confirmation_reason=None,
                inputs={"thread_id": thread.id, "reason": reason},
                preconditions=["Thread must not be in terminal status (COMPLETED)"],
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                risk_level=RiskLevel.LOW,
                created_at=ref_time,
            )
            if self._repository is not None:
                self._repository.save_proposal(proposal)
            if self._registry is not None:
                self._registry.register(proposal)
            return proposal

        elif resolved_action_type == NextActionType.ABANDON_INTENTION:
            params = parameters or {}
            reason = (params.get("reason") or "Abandoned by user").strip()
            status = ProposalStatus.CONFIRMATION_REQUIRED
            description = f"Abandon thread '{thread.title}'. Reason: {reason}."
            rationale = (
                f"User requested abandonment: {reason}. "
                "Crucial invariant: all historical evidence and commitments remain intact."
            )
            proposal_id = derive_proposal_id(
                thread_id=thread.id,
                action_type=NextActionType.ABANDON_INTENTION,
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                extra_payload=reason,
            )
            proposal = ActionProposal(
                id=proposal_id,
                thread_id=thread.id,
                action_type=NextActionType.ABANDON_INTENTION,
                title=f"Abandon thread: {thread.title}",
                description=description,
                rationale=rationale,
                status=status,
                requires_confirmation=True,
                confirmation_reason=(
                    "Abandoning an intention is an explicit lifecycle termination. "
                    "User confirmation required."
                ),
                inputs={"thread_id": thread.id, "reason": reason},
                preconditions=["Thread must not be in terminal status (COMPLETED)"],
                supporting_evidence_ids=[],
                supporting_commitment_ids=[],
                supporting_dependency_ids=[],
                risk_level=RiskLevel.MEDIUM,
                created_at=ref_time,
            )
            if self._repository is not None:
                self._repository.save_proposal(proposal)
            if self._registry is not None:
                self._registry.register(proposal)
            return proposal

        if suggestion is None:
            raise ValueError(
                "Either suggestion or a valid M13 action_type must be provided to prepare_action."
            )

        # Find target dependency if referenced
        target_dep: Dependency | None = None
        if suggestion.supporting_dependency_ids:
            dep_id = suggestion.supporting_dependency_ids[0]
            target_dep = next((d for d in thread.dependencies if d.id == dep_id), None)

        # Base fields from suggestion
        title = suggestion.action
        rationale = suggestion.rationale
        requires_confirmation = suggestion.requires_confirmation
        preconditions = list(suggestion.preconditions)
        supporting_evidence_ids = list(suggestion.supporting_evidence_ids)
        supporting_commitment_ids = list(suggestion.supporting_commitment_ids)
        supporting_dependency_ids = list(suggestion.supporting_dependency_ids)

        inputs: dict[str, Any] = {}
        confirmation_reason: str | None = None
        description: str
        status: ProposalStatus

        # -------------------------------------------------------------------
        # Category A: DIRECT_NEXT_ACTION
        # -------------------------------------------------------------------
        if suggestion.action_type == NextActionType.DIRECT_NEXT_ACTION:
            description = (
                f"Prepare execution steps for '{suggestion.action}' on thread "
                f"'{thread.title}'."
            )
            inputs["thread_id"] = thread.id
            if supporting_commitment_ids:
                cid = supporting_commitment_ids[0]
                comm = next((c for c in thread.commitments if c.id == cid), None)
                if comm:
                    inputs["commitment_id"] = comm.id
                    inputs["task"] = comm.description
            else:
                inputs["task"] = suggestion.action

            if requires_confirmation:
                status = ProposalStatus.CONFIRMATION_REQUIRED
                confirmation_reason = (
                    "Direct action involves external side effects requiring "
                    "user confirmation before proceeding."
                )
            else:
                status = ProposalStatus.READY
                confirmation_reason = None

        # -------------------------------------------------------------------
        # Category B: UNBLOCKER_ACTION
        # -------------------------------------------------------------------
        elif suggestion.action_type == NextActionType.UNBLOCKER_ACTION:
            recipient = _extract_recipient(thread, target_dep)
            dep_desc = target_dep.description if target_dep else suggestion.action

            if requires_confirmation and recipient is None:
                # Required recipient unknown -> BLOCKED
                status = ProposalStatus.BLOCKED
                description = (
                    f"Unblocker action cannot be prepared for '{thread.title}' "
                    "because the required recipient is missing."
                )
                confirmation_reason = (
                    "The unblocker action cannot be prepared because the required "
                    "recipient is not identified in the available Threadback data."
                )
                preconditions.append(
                    "Recipient identity must be established before preparation"
                )
                inputs["thread_id"] = thread.id
                inputs["missing_field"] = "recipient"
            else:
                description = (
                    f"Prepare a request or outreach to resolve blocking dependency "
                    f"'{dep_desc}'."
                )
                inputs["thread_id"] = thread.id
                if recipient:
                    inputs["recipient"] = recipient
                if target_dep:
                    inputs["blocker_id"] = target_dep.id
                    inputs["blocker_description"] = target_dep.description

                if requires_confirmation:
                    status = ProposalStatus.CONFIRMATION_REQUIRED
                    target_label = f"with {recipient}" if recipient else "externally"
                    confirmation_reason = (
                        f"External communication {target_label} requires explicit "
                        "user confirmation before sending."
                    )
                else:
                    status = ProposalStatus.READY
                    confirmation_reason = None

        # -------------------------------------------------------------------
        # Category C: FOLLOW_UP_ACTION
        # -------------------------------------------------------------------
        elif suggestion.action_type == NextActionType.FOLLOW_UP_ACTION:
            recipient = _extract_recipient(thread, target_dep)
            dep_desc = target_dep.description if target_dep else suggestion.action

            if requires_confirmation and recipient is None:
                # Required recipient unknown -> BLOCKED
                status = ProposalStatus.BLOCKED
                description = (
                    f"Follow-up action cannot be prepared for '{thread.title}' "
                    "because the required recipient is missing."
                )
                confirmation_reason = (
                    "The follow-up cannot be prepared because the required recipient "
                    "is not identified in the available Threadback data."
                )
                preconditions.append(
                    "Recipient identity must be established before preparation"
                )
                inputs["thread_id"] = thread.id
                inputs["missing_field"] = "recipient"
            else:
                description = (
                    f"Prepare a follow-up inquiry regarding pending dependency "
                    f"'{dep_desc}'."
                )
                inputs["thread_id"] = thread.id
                if recipient:
                    inputs["recipient"] = recipient
                if target_dep:
                    inputs["dependency_id"] = target_dep.id
                    inputs["subject"] = target_dep.description

                if requires_confirmation:
                    status = ProposalStatus.CONFIRMATION_REQUIRED
                    target_label = f"with {recipient}" if recipient else "externally"
                    confirmation_reason = (
                        f"External communication {target_label} requires explicit "
                        "user confirmation before sending."
                    )
                else:
                    status = ProposalStatus.READY
                    confirmation_reason = None

        # -------------------------------------------------------------------
        # Category D: GATHER_EVIDENCE_ACTION
        # -------------------------------------------------------------------
        elif suggestion.action_type == NextActionType.GATHER_EVIDENCE_ACTION:
            description = (
                f"Prepare an evidence-gathering checklist to clarify current "
                f"status and documentation for '{thread.title}'."
            )
            inputs["thread_id"] = thread.id
            inputs["thread_title"] = thread.title
            status = ProposalStatus.READY
            requires_confirmation = False
            confirmation_reason = None

        # -------------------------------------------------------------------
        # Category E: NO_ACTION
        # -------------------------------------------------------------------
        else:
            description = (
                f"Thread '{thread.title}' is {thread.status.value.lower()}. "
                "No action required."
            )
            status = ProposalStatus.READY
            requires_confirmation = False
            confirmation_reason = None

        # Deterministic risk classification
        risk_level = _classify_risk_level(
            suggestion.action_type,
            title,
            requires_confirmation,
        )

        # Deterministic proposal ID derivation
        proposal_id = derive_proposal_id(
            thread_id=thread.id,
            action_type=suggestion.action_type,
            supporting_evidence_ids=supporting_evidence_ids,
            supporting_commitment_ids=supporting_commitment_ids,
            supporting_dependency_ids=supporting_dependency_ids,
        )

        proposal = ActionProposal(
            id=proposal_id,
            thread_id=thread.id,
            action_type=suggestion.action_type,
            title=title,
            description=description,
            rationale=rationale,
            status=status,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            inputs=inputs,
            preconditions=preconditions,
            supporting_evidence_ids=supporting_evidence_ids,
            supporting_commitment_ids=supporting_commitment_ids,
            supporting_dependency_ids=supporting_dependency_ids,
            risk_level=risk_level,
            created_at=ref_time,
        )

        if self._repository is not None:
            self._repository.save_proposal(proposal)

        if self._registry is not None:
            self._registry.register(proposal)

        return proposal
