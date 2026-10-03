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
    COMPLETED: Intent has been successfully fulfilled and closed.
    ABANDONED: Intent is no longer relevant or has been dismissed.
    """

    DISCOVERED = "DISCOVERED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
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
    """Deterministic attention signal level for a thread."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


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


class NextActionType(str, Enum):
    """
    Deterministic category of next action recommended for an IntentThread.

    DIRECT_NEXT_ACTION: Actionable step on an unblocked thread (open commitment).
    UNBLOCKER_ACTION: Action to resolve or address an active blocking dependency.
    FOLLOW_UP_ACTION: Follow-up on a pending external dependency/party while waiting.
    GATHER_EVIDENCE_ACTION: Gathering missing context/evidence when data is insufficient.
    NO_ACTION: No action needed (e.g. thread is completed, abandoned, or closed).
    """

    DIRECT_NEXT_ACTION = "DIRECT_NEXT_ACTION"
    UNBLOCKER_ACTION = "UNBLOCKER_ACTION"
    FOLLOW_UP_ACTION = "FOLLOW_UP_ACTION"
    GATHER_EVIDENCE_ACTION = "GATHER_EVIDENCE_ACTION"
    NO_ACTION = "NO_ACTION"


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
    """Execution mode for action proposals (M7).

    SIMULATED: Controlled simulated execution within Threadback memory.
               No external side effects, network calls, or third-party mutations.
    """

    SIMULATED = "SIMULATED"


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
    Persistent lifecycle event types for an IntentThread (M10).

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


class ClosureStatus(str, Enum):
    """Outcome status of a thread closure attempt (M10)."""

    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
