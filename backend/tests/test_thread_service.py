"""
ThreadService unit tests for Threadback M3.

Verifies:
  - list_threads excludes COMPLETED and ABANDONED
  - list_threads filtering by status and limit
  - get_thread with existing and unknown thread IDs
  - find_blockers strict logic (blocking=True and status=OPEN)
  - find_blockers returns empty list for threads without blockers
  - find_blockers raises ThreadNotFoundError for unknown IDs
  - Read-only guarantee: service data is immutable across queries
"""

from __future__ import annotations

import pytest
from app.domain.enums import DependencyStatus, ThreadStatus
from app.services.thread_service import ThreadNotFoundError, ThreadService


@pytest.fixture
def service() -> ThreadService:
    """Provide a freshly initialized ThreadService with demo data."""
    return ThreadService()


def test_list_threads_excludes_completed_and_abandoned(service: ThreadService) -> None:
    """list_threads must strictly exclude COMPLETED and ABANDONED threads."""
    threads = service.list_threads()
    statuses = {t.status for t in threads}

    assert ThreadStatus.COMPLETED not in statuses, "COMPLETED threads must be excluded"
    assert ThreadStatus.ABANDONED not in statuses, "ABANDONED threads must be excluded"
    assert statuses.issubset(
        {
            ThreadStatus.DISCOVERED,
            ThreadStatus.ACTIVE,
            ThreadStatus.BLOCKED,
            ThreadStatus.WAITING,
        }
    )


def test_list_threads_status_filter(service: ThreadService) -> None:
    """Filtering list_threads by status returns only threads with that status."""
    blocked = service.list_threads(status="BLOCKED")
    assert len(blocked) >= 1
    assert all(t.status == ThreadStatus.BLOCKED for t in blocked)

    active = service.list_threads(status="ACTIVE")
    assert len(active) >= 1
    assert all(t.status == ThreadStatus.ACTIVE for t in active)

    waiting = service.list_threads(status=ThreadStatus.WAITING)
    assert len(waiting) >= 1
    assert all(t.status == ThreadStatus.WAITING for t in waiting)


def test_list_threads_filter_for_completed_returns_empty(
    service: ThreadService,
) -> None:
    """Querying COMPLETED or ABANDONED in list_threads returns empty list."""
    assert service.list_threads(status="COMPLETED") == []
    assert service.list_threads(status="ABANDONED") == []


def test_list_threads_invalid_status_raises_value_error(service: ThreadService) -> None:
    """Passing an invalid status name raises ValueError."""
    with pytest.raises(ValueError, match="Invalid status"):
        service.list_threads(status="NONEXISTENT_STATUS")


def test_list_threads_limit(service: ThreadService) -> None:
    """list_threads respects the limit argument."""
    all_threads = service.list_threads()
    assert len(all_threads) >= 4

    limited_2 = service.list_threads(limit=2)
    assert len(limited_2) == 2
    assert [t.id for t in limited_2] == [t.id for t in all_threads[:2]]

    limited_0 = service.list_threads(limit=0)
    assert len(limited_0) == 0


def test_list_threads_negative_limit_raises_value_error(service: ThreadService) -> None:
    """Negative limit raises ValueError."""
    with pytest.raises(ValueError, match="Limit must be a non-negative integer"):
        service.list_threads(limit=-1)


def test_get_thread_existing(service: ThreadService) -> None:
    """get_thread returns the complete IntentThread for a valid ID."""
    thread = service.get_thread("thread-university-application")
    assert thread.id == "thread-university-application"
    assert thread.title == "University Application"
    assert thread.status == ThreadStatus.BLOCKED
    assert len(thread.commitments) > 0
    assert len(thread.evidence) > 0
    assert len(thread.dependencies) > 0
    assert len(thread.events) > 0


def test_get_thread_unknown_raises_error(service: ThreadService) -> None:
    """get_thread raises ThreadNotFoundError for unknown ID."""
    with pytest.raises(ThreadNotFoundError) as exc_info:
        service.get_thread("thread-nonexistent-xyz")
    assert "thread-nonexistent-xyz" in str(exc_info.value)
    assert exc_info.value.thread_id == "thread-nonexistent-xyz"


def test_find_blockers_returns_only_active_blockers(service: ThreadService) -> None:
    """find_blockers only returns dependencies with blocking=True and status=OPEN."""
    blockers = service.find_blockers("thread-university-application")
    assert len(blockers) == 1
    blocker = blockers[0]
    assert blocker.blocking is True
    assert blocker.status == DependencyStatus.OPEN
    assert blocker.id == "dep-uni-rec-letter"


def test_find_blockers_empty_for_unblocked_thread(service: ThreadService) -> None:
    """find_blockers returns an empty list for threads without blockers."""
    # thread-dentist-appointment has a resolved dependency (blocking=False, status=RESOLVED)
    blockers = service.find_blockers("thread-dentist-appointment")
    assert blockers == []

    # thread-aws-hackathon has no dependencies at all
    blockers_aws = service.find_blockers("thread-aws-hackathon")
    assert blockers_aws == []


def test_find_blockers_unknown_thread_raises_error(service: ThreadService) -> None:
    """find_blockers raises ThreadNotFoundError for unknown ID."""
    with pytest.raises(ThreadNotFoundError):
        service.find_blockers("thread-nonexistent-xyz")


def test_read_only_guarantee_immutability(service: ThreadService) -> None:
    """Mutating returned objects must NOT alter internal service state."""
    thread = service.get_thread("thread-dentist-appointment")
    original_title = thread.title

    # Attempt mutation on the returned copy
    thread.title = "MUTATED TITLE"
    thread.status = ThreadStatus.ABANDONED

    # Re-fetch from service
    refetched = service.get_thread("thread-dentist-appointment")
    assert refetched.title == original_title
    assert refetched.status == ThreadStatus.ACTIVE
