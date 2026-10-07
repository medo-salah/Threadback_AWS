"""
In-memory implementation of BaseThreadRepository for testing and mock execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.enums import ThreadEventType, ThreadStatus
from app.domain.models import (
    IntentEvolution,
    IntentThread,
    ProactiveInsightRecord,
    ThreadEvent,
)
from app.repositories.base import BaseThreadRepository

if TYPE_CHECKING:
    from app.domain.models import (
        ActionProposal,
        Commitment,
        Dependency,
        Event,
        Evidence,
        ThreadVerification,
    )

UNFINISHED_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.DISCOVERED,
        ThreadStatus.ACTIVE,
        ThreadStatus.BLOCKED,
        ThreadStatus.WAITING,
    }
)


class InMemoryThreadRepository(BaseThreadRepository):
    """Ephemeral, in-memory repository implementing BaseThreadRepository."""

    def __init__(self, initial_threads: list[IntentThread] | None = None) -> None:
        self._threads: dict[str, IntentThread] = {}
        self._events: dict[str, list[ThreadEvent]] = {}
        self._proposals: dict[str, ActionProposal] = {}
        self._verifications: dict[str, list[ThreadVerification]] = {}
        self._evolutions: dict[str, list[IntentEvolution]] = {}
        self._checkpoints: dict[str, datetime] = {}
        self._insights: list[ProactiveInsightRecord] = []

        if initial_threads:
            for thread in initial_threads:
                self.save_thread(thread)

    def get_thread(self, thread_id: str) -> IntentThread | None:
        thread = self._threads.get(thread_id)
        if thread is None:
            return None
        return thread.model_copy(deep=True)

    def list_threads(
        self,
        status: ThreadStatus | None = None,
        limit: int | None = None,
        unfinished_only: bool = True,
    ) -> list[IntentThread]:
        results: list[IntentThread] = []
        for thread in self._threads.values():
            if unfinished_only and thread.status not in UNFINISHED_STATUSES:
                continue
            if status is not None and thread.status != status:
                continue
            results.append(thread.model_copy(deep=True))

        if limit is not None and limit >= 0:
            results = results[:limit]
        return results

    def save_thread(self, thread: IntentThread) -> None:
        copy_thread = thread.model_copy(deep=True)
        self._threads[copy_thread.id] = copy_thread

        # Index existing events
        if copy_thread.id not in self._events:
            self._events[copy_thread.id] = []
        for ev in copy_thread.events:
            if isinstance(ev, ThreadEvent):
                self._events[copy_thread.id].append(ev.model_copy(deep=True))
            else:
                self._events[copy_thread.id].append(
                    ThreadEvent(
                        id=ev.id,
                        thread_id=copy_thread.id,
                        event_type=ThreadEventType.THREAD_DISCOVERED,
                        type=ev.type,
                        description=ev.description,
                        timestamp=ev.timestamp,
                    )
                )

    def update_thread_status(self, thread_id: str, status: ThreadStatus) -> None:
        thread = self._threads.get(thread_id)
        if thread is not None:
            thread.status = status

    def add_evidence(self, thread_id: str, evidence: Evidence) -> None:
        thread = self._threads.get(thread_id)
        if thread is not None:
            # Replace if id exists, else append
            existing_idx = next(
                (i for i, e in enumerate(thread.evidence) if e.id == evidence.id), None
            )
            if existing_idx is not None:
                thread.evidence[existing_idx] = evidence.model_copy(deep=True)
            else:
                thread.evidence.append(evidence.model_copy(deep=True))

    def get_evidence(self, thread_id: str) -> list[Evidence]:
        thread = self._threads.get(thread_id)
        if thread is None:
            return []
        return [e.model_copy(deep=True) for e in thread.evidence]

    def update_dependency(self, thread_id: str, dependency: Dependency) -> None:
        thread = self._threads.get(thread_id)
        if thread is not None:
            existing_idx = next(
                (i for i, d in enumerate(thread.dependencies) if d.id == dependency.id),
                None,
            )
            if existing_idx is not None:
                thread.dependencies[existing_idx] = dependency.model_copy(deep=True)
            else:
                thread.dependencies.append(dependency.model_copy(deep=True))

    def update_commitment(self, thread_id: str, commitment: Commitment) -> None:
        thread = self._threads.get(thread_id)
        if thread is not None:
            existing_idx = next(
                (i for i, c in enumerate(thread.commitments) if c.id == commitment.id),
                None,
            )
            if existing_idx is not None:
                thread.commitments[existing_idx] = commitment.model_copy(deep=True)
            else:
                thread.commitments.append(commitment.model_copy(deep=True))

    def add_event(self, thread_id: str, event: ThreadEvent | Event) -> None:
        if isinstance(event, ThreadEvent):
            th_event = event.model_copy(deep=True)
        else:
            th_event = ThreadEvent(
                id=event.id,
                thread_id=thread_id,
                event_type=event.type,
                type=event.type,
                description=event.description,
                timestamp=event.timestamp,
            )
        if thread_id not in self._events:
            self._events[thread_id] = []
        self._events[thread_id].append(th_event)

        thread = self._threads.get(thread_id)
        if thread is not None:
            thread.events.append(th_event)

    def get_events(self, thread_id: str) -> list[ThreadEvent]:
        events = self._events.get(thread_id, [])
        return [e.model_copy(deep=True) for e in events]

    def save_proposal(self, proposal: ActionProposal) -> None:
        self._proposals[proposal.id] = proposal.model_copy(deep=True)

    def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        p = self._proposals.get(proposal_id)
        return p.model_copy(deep=True) if p else None

    def list_proposals(self, thread_id: str | None = None) -> list[ActionProposal]:
        if thread_id is None:
            return [p.model_copy(deep=True) for p in self._proposals.values()]
        return [
            p.model_copy(deep=True)
            for p in self._proposals.values()
            if p.thread_id == thread_id
        ]

    def save_verification(self, verification: ThreadVerification) -> None:
        if verification.thread_id not in self._verifications:
            self._verifications[verification.thread_id] = []
        self._verifications[verification.thread_id].append(
            verification.model_copy(deep=True)
        )

    def get_latest_verification(self, thread_id: str) -> ThreadVerification | None:
        vers = self._verifications.get(thread_id, [])
        return vers[-1].model_copy(deep=True) if vers else None

    def add_intent_evolution(self, evolution: IntentEvolution) -> None:
        if evolution.thread_id not in self._evolutions:
            self._evolutions[evolution.thread_id] = []
        self._evolutions[evolution.thread_id].append(evolution.model_copy(deep=True))
        thread = self._threads.get(evolution.thread_id)
        if thread is not None:
            thread.evolutions.append(evolution.model_copy(deep=True))
            thread.current_goal = evolution.revised_goal

    def get_intent_evolutions(self, thread_id: str) -> list[IntentEvolution]:
        evos = self._evolutions.get(thread_id, [])
        return [e.model_copy(deep=True) for e in evos]

    def set_conversation_checkpoint(
        self,
        conversation_id: str,
        last_seen_at: datetime,
        checkpoint_event_id: str | None = None,
    ) -> None:
        self._checkpoints[conversation_id] = last_seen_at

    def get_conversation_checkpoint(self, conversation_id: str) -> datetime | None:
        return self._checkpoints.get(conversation_id)

    def record_proactive_insight(self, record: ProactiveInsightRecord) -> None:
        """Persist a proactive insight record for deduplication (M14)."""
        # Overwrite if matching insight_id exists
        self._insights = [
            i for i in self._insights if i.insight_id != record.insight_id
        ]
        self._insights.append(record.model_copy(deep=True))

    def get_proactive_insights(
        self, thread_id: str | None = None, limit: int = 50
    ) -> list[ProactiveInsightRecord]:
        """Retrieve proactive insight records, optionally filtered by thread ID (M14)."""
        filtered = self._insights
        if thread_id:
            filtered = [i for i in filtered if i.thread_id == thread_id]
        # Sort descending by created_at
        sorted_records = sorted(filtered, key=lambda x: x.created_at, reverse=True)
        return [r.model_copy(deep=True) for r in sorted_records[:limit]]

    def is_insight_duplicate(
        self, thread_id: str, insight_type: str, state_fingerprint: str
    ) -> bool:
        """Check if an insight for this thread, type, and state fingerprint already exists (M14)."""
        return any(
            i.thread_id == thread_id
            and i.insight_type == insight_type
            and i.state_fingerprint == state_fingerprint
            for i in self._insights
        )

    def count_threads(self) -> int:
        return len(self._threads)

    def reset(self, seed: bool = True) -> None:
        """Clear all in-memory collections and optionally re-seed demo threads."""
        self._threads.clear()
        self._events.clear()
        self._proposals.clear()
        self._verifications.clear()
        self._evolutions.clear()
        self._checkpoints.clear()
        self._insights.clear()
        if seed:
            from app.data.demo_data import get_demo_threads

            for thread in get_demo_threads():
                self.save_thread(thread)

    def close(self) -> None:
        pass
