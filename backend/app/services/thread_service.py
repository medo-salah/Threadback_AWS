"""
Thread service for Threadback.

Provides querying, inspection, and lifecycle operations over IntentThread domain objects.
Maintains complete independence from transport and protocol layers (no MCP imports).
Backed by BaseThreadRepository (SQLite by default in M10, with in-memory support).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.config import settings
from app.domain.enums import DependencyStatus, ThreadStatus
from app.domain.models import Dependency, Event, Evidence, IntentThread, ThreadEvent
from app.repositories.base import BaseThreadRepository
from app.repositories.in_memory_repository import InMemoryThreadRepository
from app.repositories.sqlite_repository import SQLiteThreadRepository

# Unfinished statuses that discover_unfinished_threads is permitted to return
UNFINISHED_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.DISCOVERED,
        ThreadStatus.ACTIVE,
        ThreadStatus.BLOCKED,
        ThreadStatus.WAITING,
    }
)


class ThreadNotFoundError(KeyError):
    """Raised when an intent thread with the specified ID does not exist."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(f"Thread '{thread_id}' was not found.")
        self.thread_id = thread_id


class ThreadService:
    """
    Deterministic domain service for querying and inspecting IntentThreads.

    Backed by a BaseThreadRepository interface (SQLite by default for M10).
    """

    def __init__(
        self,
        threads: Iterable[IntentThread] | None = None,
        repository: BaseThreadRepository | None = None,
    ) -> None:
        """
        Initialize the service with an optional thread collection or repository.

        If a repository is provided, it is used directly.
        If threads are provided, an InMemoryThreadRepository is created with them.
        If neither is provided, SQLiteThreadRepository is initialized.
        """
        if repository is not None:
            self._repository: BaseThreadRepository = repository
        elif threads is not None:
            self._repository = InMemoryThreadRepository(list(threads))
        else:
            self._repository = SQLiteThreadRepository(
                db_path=settings.sqlite_db_path, auto_seed=True
            )

        # In-memory dictionary reference maintained for backward compatibility
        self._threads: dict[str, IntentThread] = {}
        for t in self._repository.list_threads(unfinished_only=False):
            self._threads[t.id] = t

    @property
    def repository(self) -> BaseThreadRepository:
        """Expose the underlying persistence repository."""
        return self._repository

    def list_threads(
        self,
        status: str | ThreadStatus | None = None,
        limit: int | None = None,
    ) -> list[IntentThread]:
        """
        List unfinished intent threads (excludes COMPLETED and ABANDONED).

        Args:
            status: Optional status filter. Only unfinished statuses
                    (DISCOVERED, ACTIVE, BLOCKED, WAITING) will match.
            limit: Optional non-negative integer maximum number of threads.

        Returns:
            List of matching unfinished IntentThread instances (deep-copied).

        Raises:
            ValueError: If status is not a valid ThreadStatus or limit is negative.
        """
        if limit is not None and limit < 0:
            raise ValueError("Limit must be a non-negative integer.")

        target_status: ThreadStatus | None = None
        if status is not None:
            if isinstance(status, ThreadStatus):
                target_status = status
            else:
                try:
                    target_status = ThreadStatus(status.upper())
                except ValueError as err:
                    valid = ", ".join(s.value for s in ThreadStatus)
                    raise ValueError(
                        f"Invalid status '{status}'. Valid statuses: {valid}"
                    ) from err

        results = self._repository.list_threads(
            status=target_status,
            limit=limit,
            unfinished_only=True,
        )
        for t in results:
            self._threads[t.id] = t
        return [t.model_copy(deep=True) for t in results]

    def get_thread(self, thread_id: str) -> IntentThread:
        """Retrieve a single intent thread by ID.

        Args:
            thread_id: Unique identifier of the thread.

        Returns:
            The requested IntentThread instance (deep-copied).

        Raises:
            ThreadNotFoundError: If thread_id is not in the repository.
        """
        if thread_id in self._threads:
            cached = self._threads[thread_id]
            repo_thread = self._repository.get_thread(thread_id)
            if repo_thread is None:
                raise ThreadNotFoundError(thread_id)
            # If repository has newer evidence or events (e.g. from another process), sync it
            if len(repo_thread.evidence) > len(cached.evidence) or len(
                repo_thread.events
            ) > len(cached.events):
                self._threads[thread_id] = repo_thread
                return repo_thread.model_copy(deep=True)
            return cached.model_copy(deep=True)

        thread = self._repository.get_thread(thread_id)
        if thread is None:
            raise ThreadNotFoundError(thread_id)
        self._threads[thread_id] = thread
        return thread.model_copy(deep=True)

    def find_blockers(self, thread_id: str) -> list[Dependency]:
        """Find active blockers for a given thread.

        A dependency is an active blocker if and only if:
            blocking == True AND status == DependencyStatus.OPEN

        Args:
            thread_id: Unique identifier of the thread.

        Returns:
            List of active blocking Dependency instances.

        Raises:
            ThreadNotFoundError: If thread_id is not found.
        """
        thread = self.get_thread(thread_id)
        return [
            d.model_copy(deep=True)
            for d in thread.dependencies
            if d.blocking and d.status == DependencyStatus.OPEN
        ]

    def add_event(self, thread_id: str, event: ThreadEvent | Event) -> None:
        """Record an internal event on the specified thread.

        Args:
            thread_id: Unique identifier of the thread.
            event: Event instance to append.

        Raises:
            ThreadNotFoundError: If thread_id is not found.
        """
        if self._repository.get_thread(thread_id) is None:
            raise ThreadNotFoundError(thread_id)
        self._repository.add_event(thread_id, event)
        refreshed = self._repository.get_thread(thread_id)
        if refreshed is not None:
            self._threads[thread_id] = refreshed

    def add_evidence(self, thread_id: str, evidence: Evidence) -> None:
        """Add an evidence item to the specified thread and persist.

        Args:
            thread_id: Unique identifier of the thread.
            evidence: Evidence instance to add.

        Raises:
            ThreadNotFoundError: If thread_id is not found.
        """
        if self._repository.get_thread(thread_id) is None:
            raise ThreadNotFoundError(thread_id)
        self._repository.add_evidence(thread_id, evidence)
        refreshed = self._repository.get_thread(thread_id)
        if refreshed is not None:
            self._threads[thread_id] = refreshed

    def update_thread(self, thread: IntentThread) -> None:
        """Update or persist an entire IntentThread aggregate."""
        self._repository.save_thread(thread)
        self._threads[thread.id] = thread.model_copy(deep=True)

    def update_status(self, thread_id: str, status: ThreadStatus) -> None:
        """Update thread status in both cache and repository."""
        if self._repository.get_thread(thread_id) is None:
            raise ThreadNotFoundError(thread_id)
        self._repository.update_thread_status(thread_id, status)
        refreshed = self._repository.get_thread(thread_id)
        if refreshed is not None:
            self._threads[thread_id] = refreshed

    def get_events(self, thread_id: str) -> list[ThreadEvent]:
        """Retrieve chronological lifecycle events for the thread."""
        if self._repository.get_thread(thread_id) is None:
            raise ThreadNotFoundError(thread_id)
        return self._repository.get_events(thread_id)

    def reconstruct_history(self, thread_id: str) -> list[ThreadEvent]:
        """Reconstruct full lifecycle event history for 'Where did I leave off?'."""
        return self.get_events(thread_id)

    def reset(self, seed: bool = True) -> None:
        """Reset the underlying repository and rebuild the local thread cache."""
        self._repository.reset(seed=seed)
        self._threads = {}
        for t in self._repository.list_threads(unfinished_only=False):
            self._threads[t.id] = t
