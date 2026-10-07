"""
Repository abstraction for Threadback (M10).

Defines the abstract interface for persistent intent memory, isolating
the domain services from the underlying storage technology (SQLite, PostgreSQL, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from app.domain.enums import ThreadStatus
    from app.domain.models import (
        ActionProposal,
        Commitment,
        Dependency,
        Event,
        Evidence,
        IntentEvolution,
        IntentThread,
        ProactiveInsightRecord,
        ThreadEvent,
        ThreadVerification,
    )


class BaseThreadRepository(ABC):
    """
    Abstract base class for Threadback IntentThread persistence.

    All storage adapters (InMemory, SQLite, PostgreSQL) must implement this interface.
    """

    @abstractmethod
    def get_thread(self, thread_id: str) -> IntentThread | None:
        """Retrieve an IntentThread by ID, returning None if not found."""
        ...

    @abstractmethod
    def list_threads(
        self,
        status: ThreadStatus | None = None,
        limit: int | None = None,
        unfinished_only: bool = True,
    ) -> list[IntentThread]:
        """List threads with optional status filtering and limit."""
        ...

    @abstractmethod
    def save_thread(self, thread: IntentThread) -> None:
        """Persist or update an IntentThread and its associated components."""
        ...

    @abstractmethod
    def update_thread_status(self, thread_id: str, status: ThreadStatus) -> None:
        """Update only the status of an existing thread."""
        ...

    @abstractmethod
    def add_evidence(self, thread_id: str, evidence: Evidence) -> None:
        """Add an evidence item to the specified thread."""
        ...

    @abstractmethod
    def get_evidence(self, thread_id: str) -> list[Evidence]:
        """Retrieve all evidence items associated with a thread."""
        ...

    @abstractmethod
    def update_dependency(self, thread_id: str, dependency: Dependency) -> None:
        """Update or insert a dependency for the specified thread."""
        ...

    @abstractmethod
    def update_commitment(self, thread_id: str, commitment: Commitment) -> None:
        """Update or insert a commitment for the specified thread."""
        ...

    @abstractmethod
    def add_event(self, thread_id: str, event: ThreadEvent | Event) -> None:
        """Append an auditable lifecycle event to the thread's history."""
        ...

    @abstractmethod
    def get_events(self, thread_id: str) -> list[ThreadEvent]:
        """Retrieve chronological lifecycle events for the specified thread."""
        ...

    @abstractmethod
    def save_proposal(self, proposal: ActionProposal) -> None:
        """Persist an ActionProposal."""
        ...

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        """Retrieve an ActionProposal by its ID."""
        ...

    @abstractmethod
    def list_proposals(self, thread_id: str | None = None) -> list[ActionProposal]:
        """List proposals, optionally filtered by thread ID."""
        ...

    @abstractmethod
    def save_verification(self, verification: ThreadVerification) -> None:
        """Record a ThreadVerification evaluation."""
        ...

    @abstractmethod
    def get_latest_verification(self, thread_id: str) -> ThreadVerification | None:
        """Retrieve the most recent verification result for a thread."""
        ...

    @abstractmethod
    def add_intent_evolution(self, evolution: IntentEvolution) -> None:
        """Record an intent evolution entry (M13)."""
        ...

    @abstractmethod
    def get_intent_evolutions(self, thread_id: str) -> list[IntentEvolution]:
        """Retrieve chronological intent evolution history for a thread (M13)."""
        ...

    @abstractmethod
    def set_conversation_checkpoint(
        self,
        conversation_id: str,
        last_seen_at: datetime,
        checkpoint_event_id: str | None = None,
    ) -> None:
        """Persist a conversation interaction checkpoint (M13)."""
        ...

    @abstractmethod
    def get_conversation_checkpoint(self, conversation_id: str) -> datetime | None:
        """Retrieve the last seen timestamp checkpoint for a conversation (M13)."""
        ...

    @abstractmethod
    def record_proactive_insight(self, record: ProactiveInsightRecord) -> None:
        """Persist a proactive insight record for deduplication (M14)."""
        ...

    @abstractmethod
    def get_proactive_insights(
        self, thread_id: str | None = None, limit: int = 50
    ) -> list[ProactiveInsightRecord]:
        """Retrieve proactive insight records, optionally filtered by thread ID (M14)."""
        ...

    @abstractmethod
    def is_insight_duplicate(
        self, thread_id: str, insight_type: str, state_fingerprint: str
    ) -> bool:
        """Check if an insight for this thread, type, and state fingerprint already exists (M14)."""
        ...

    @abstractmethod
    def count_threads(self) -> int:
        """Return the total number of stored threads."""
        ...

    @abstractmethod
    def reset(self, seed: bool = True) -> None:
        """Reset the repository contents, optionally re-seeding with demo data."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close any open connections or resources."""
        ...
