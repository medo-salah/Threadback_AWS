"""
Domain enums for Threadback.

Defines the core enumeration types for intent threads, commitments,
evidence, dependencies, and priority levels.
"""

from enum import Enum


class ThreadStatus(str, Enum):
    """
    Lifecycle status of an IntentThread.

    DISCOVERED: Intent detected from unstructured context but not yet acknowledged.
    ACTIVE: User or system is actively pursuing this intent thread.
    BLOCKED: Progress is impeded by an unresolved blocking dependency.
    WAITING: Thread is paused awaiting external input, time, or event.
    DEFERRED: Intent is explicitly postponed or on hold.
    COMPLETED: Intent has been successfully fulfilled and closed.
    ABANDONED: Intent is no longer relevant or has been dismissed.
    """

    DISCOVERED = "DISCOVERED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class CommitmentStatus(str, Enum):
    """Status of an explicit or implicit commitment within a thread."""

    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvidenceType(str, Enum):
    """Source modality from which intent evidence was captured."""

    CONVERSATION = "CONVERSATION"
    DOCUMENT = "DOCUMENT"
    CALENDAR = "CALENDAR"
    NOTE = "NOTE"
    MESSAGE = "MESSAGE"
    USER_ACTION = "USER_ACTION"


class DependencyStatus(str, Enum):
    """Resolution status of a dependency."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class Priority(str, Enum):
    """Relative importance level of an intent thread."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConfidenceBand(str, Enum):
    """
    Confidence classification band as defined in M0.

    STRONG:    0.90 – 1.00
    GOOD:      0.75 – 0.89
    UNCERTAIN: 0.50 – 0.74
    WEAK:      < 0.50
    """

    STRONG = "STRONG"
    GOOD = "GOOD"
    UNCERTAIN = "UNCERTAIN"
    WEAK = "WEAK"


class AttentionLevel(str, Enum):
    """Deterministic attention signal level for a thread (M0–M14)."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class UnfinishedReason(str, Enum):
    """
    Deterministic reason why an intent thread remains unfinished.

    Each value is derived strictly from structured thread data.
    A thread may have multiple simultaneous reasons.
    """

    OPEN_COMMITMENT = "OPEN_COMMITMENT"
    ACTIVE_BLOCKER = "ACTIVE_BLOCKER"
    WAITING_ON_DEPENDENCY = "WAITING_ON_DEPENDENCY"
    RECENT_ACTIVITY = "RECENT_ACTIVITY"
    MISSING_REQUIRED_EVIDENCE = "MISSING_REQUIRED_EVIDENCE"


class DecayState(str, Enum):
    """
    Deterministic intent decay classification (M13).

    HEALTHY: Active within recent window (< 3 days), no imminent overdue risks.
    ATTENTION: Inactive 3-7 days or deadline approaching within 72 hours.
    DECAYING: Inactive 7-14 days or blocked without activity for 4+ days.
    STALE: Inactive >= 14 days or overdue commitment with week-long inactivity.
    """

    HEALTHY = "HEALTHY"
    ATTENTION = "ATTENTION"
    DECAYING = "DECAYING"
    STALE = "STALE"


class ChangeCategory(str, Enum):
    """Category of state change detected by the differential engine (M13)."""

    BLOCKER_CHANGE = "BLOCKER_CHANGE"
    EVIDENCE_CHANGE = "EVIDENCE_CHANGE"
    COMMITMENT_CHANGE = "COMMITMENT_CHANGE"
    STATUS_CHANGE = "STATUS_CHANGE"
    GOAL_CHANGE = "GOAL_CHANGE"
    ACTION_CHANGE = "ACTION_CHANGE"


class NextActionType(str, Enum):
    """
    Deterministic category of next action recommended for an IntentThread.

    DIRECT_NEXT_ACTION: Actionable step on an unblocked thread (open commitment).
    UNBLOCKER_ACTION: Action to resolve or address an active blocking dependency.
    FOLLOW_UP_ACTION: Follow-up on a pending external dependency/party while waiting.
    GATHER_EVIDENCE_ACTION: Gathering missing context/evidence when data is insufficient.
    NO_ACTION: No action needed (e.g. thread is completed, abandoned, or closed).
    EVOLVE_INTENTION: Update the active goal/direction of the intention (M13).
    DEFER_INTENTION: Explicitly postpone or put intention on hold (M13).
    RESUME_INTENTION: Resume a deferred intention (M13).
    ABANDON_INTENTION: Explicitly surrender an intention while preserving history (M13).
    """

    DIRECT_NEXT_ACTION = "DIRECT_NEXT_ACTION"
    UNBLOCKER_ACTION = "UNBLOCKER_ACTION"
    FOLLOW_UP_ACTION = "FOLLOW_UP_ACTION"
    GATHER_EVIDENCE_ACTION = "GATHER_EVIDENCE_ACTION"
    NO_ACTION = "NO_ACTION"
    EVOLVE_INTENTION = "EVOLVE_INTENTION"
    DEFER_INTENTION = "DEFER_INTENTION"
    RESUME_INTENTION = "RESUME_INTENTION"
    ABANDON_INTENTION = "ABANDON_INTENTION"


class ProposalStatus(str, Enum):
    """
    Review status of an action proposal (M6).

    READY: Action can be prepared without requiring an additional confirmation step.
           Does not mean the action has been executed.
    CONFIRMATION_REQUIRED: Action would eventually create an external side effect and
                           requires explicit user confirmation before execution.
    BLOCKED: Action cannot currently be prepared safely because a required
             precondition or input is missing or unresolved.
    """

    READY = "READY"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    BLOCKED = "BLOCKED"


class RiskLevel(str, Enum):
    """
    Deterministic risk classification of an action proposal (M6).

    LOW: Internal, reversible, informational preparation (e.g. review evidence, checklist).
    MEDIUM: Potential external communication or reversible external change (e.g. email, message).
    HIGH: Potentially consequential external side effect (e.g. payment, cancellation, submission).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ExecutionMode(str, Enum):
    """Execution mode for action proposals (M7 / M13).

    SIMULATED: Controlled simulated execution for external-world operational actions
               (e.g., send an email, submit an application). No real-world external side effects.
    PERSISTENT_MUTATION: Durable internal Threadback state mutation (e.g., evolve goal,
                         defer/resume/abandon thread). Mutates internal SQLite state and appends
                         lifecycle events after passing confirmation/precondition safety.
    """

    SIMULATED = "SIMULATED"
    PERSISTENT_MUTATION = "PERSISTENT_MUTATION"


class ExecutionStatus(str, Enum):
    """Execution outcome status for an action proposal (M7).

    EXECUTED: Proposal successfully executed in simulated mode.
    REJECTED: Proposal execution rejected (e.g. unconfirmed, unknown, terminal thread, NO_ACTION).
    BLOCKED: Proposal execution blocked due to unresolved status or failing preconditions.
    ALREADY_EXECUTED: Proposal has already been executed (idempotency ledger hit).
    """

    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"


class ThreadEventType(str, Enum):
    """
    Persistent lifecycle event types for an IntentThread (M10/M13).

    Captures the auditable history of changes to an intention across time.
    """

    THREAD_DISCOVERED = "THREAD_DISCOVERED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    BLOCKER_IDENTIFIED = "BLOCKER_IDENTIFIED"
    ACTION_PREPARED = "ACTION_PREPARED"
    ACTION_CONFIRMED = "ACTION_CONFIRMED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    THREAD_COMPLETED = "THREAD_COMPLETED"
    THREAD_ABANDONED = "THREAD_ABANDONED"
    INTENTION_EVOLVED = "INTENTION_EVOLVED"
    THREAD_DEFERRED = "THREAD_DEFERRED"
    THREAD_RESUMED = "THREAD_RESUMED"
    BLOCKER_RESOLVED = "BLOCKER_RESOLVED"
    COMMITMENT_ADDED = "COMMITMENT_ADDED"
    COMMITMENT_COMPLETED = "COMMITMENT_COMPLETED"


class ClosureStatus(str, Enum):
    """Outcome status of a thread closure attempt (M10)."""

    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"


# ---------------------------------------------------------------------------
# M14 Proactive Intent Intelligence Enums
# ---------------------------------------------------------------------------


class AttentionReasonCode(str, Enum):
    """Deterministic typed reason codes for proactive attention candidates (M14)."""

    DEADLINE_APPROACHING = "DEADLINE_APPROACHING"
    DEADLINE_OVERDUE = "DEADLINE_OVERDUE"
    INTENT_DECAYING = "INTENT_DECAYING"
    INTENT_STALE = "INTENT_STALE"
    BLOCKER_PRESENT = "BLOCKER_PRESENT"
    COMMITMENT_DUE = "COMMITMENT_DUE"
    COMMITMENT_OVERDUE = "COMMITMENT_OVERDUE"
    IMPORTANT_CHANGE = "IMPORTANT_CHANGE"
    NEW_EVIDENCE = "NEW_EVIDENCE"
    GOAL_EVOLVED = "GOAL_EVOLVED"
    THREAD_RESUMABLE = "THREAD_RESUMABLE"
    LONG_INACTIVITY = "LONG_INACTIVITY"
    CONFLICTING_INTENT = "CONFLICTING_INTENT"


class SignificanceLevel(str, Enum):
    """Significance classification for detected state changes (M14)."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConflictType(str, Enum):
    """Conservative deterministic cross-thread conflict classification (M14)."""

    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    TIME_CONFLICT = "TIME_CONFLICT"
    DEADLINE_CONFLICT = "DEADLINE_CONFLICT"
    GOAL_CONFLICT = "GOAL_CONFLICT"
    COMMITMENT_CONFLICT = "COMMITMENT_CONFLICT"
    NO_CONFLICT_DETERMINED = "NO_CONFLICT_DETERMINED"


class ResumeEligibility(str, Enum):
    """Deterministic resume eligibility classification for deferred threads (M14)."""

    RESUMABLE = "RESUMABLE"
    NOT_RESUMABLE = "NOT_RESUMABLE"
    UNKNOWN = "UNKNOWN"


class ProactiveTriggerType(str, Enum):
    """Deterministic proactive trigger condition types (M14)."""

    ATTENTION_THRESHOLD_CROSSED = "ATTENTION_THRESHOLD_CROSSED"
    DEADLINE_APPROACHING = "DEADLINE_APPROACHING"
    INTENT_DECAYED = "INTENT_DECAYED"
    BLOCKER_RESOLVED = "BLOCKER_RESOLVED"
    THREAD_BECAME_RESUMABLE = "THREAD_BECAME_RESUMABLE"
    SIGNIFICANT_CHANGE = "SIGNIFICANT_CHANGE"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"


# ---------------------------------------------------------------------------
# M15 Intent Copilot Enums
# ---------------------------------------------------------------------------


class DecisionCardType(str, Enum):
    """Categorization of structured intent decision cards (M15)."""

    TOP_PRIORITY = "TOP_PRIORITY"
    WHY_NOW = "WHY_NOW"
    WHAT_CHANGED = "WHAT_CHANGED"
    RESUME = "RESUME"
    WHAT_IF = "WHAT_IF"
    TIME_BUDGET = "TIME_BUDGET"
    SAFE_TO_CLOSE = "SAFE_TO_CLOSE"
    BLOCKED = "BLOCKED"
    CONFLICT = "CONFLICT"


class WhatIfScenarioType(str, Enum):
    """Deterministic scenario types for read-only what-if simulations (M15)."""

    IGNORE_TEMPORARILY = "IGNORE_TEMPORARILY"
    POSTPONE = "POSTPONE"
    RESOLVE_BLOCKER = "RESOLVE_BLOCKER"
    CHANGE_GOAL = "CHANGE_GOAL"
