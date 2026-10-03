"""
SQLite implementation of BaseThreadRepository for Threadback (M10).

Provides persistent intent memory across process restarts using the Python
standard library sqlite3 module.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data.demo_data import get_demo_threads
from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    NextActionType,
    Priority,
    ProposalStatus,
    RiskLevel,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import (
    ActionProposal,
    Commitment,
    Dependency,
    Event,
    Evidence,
    IntentThread,
    ThreadEvent,
    ThreadVerification,
)
from app.repositories.base import BaseThreadRepository

logger = logging.getLogger(__name__)

UNFINISHED_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.DISCOVERED,
        ThreadStatus.ACTIVE,
        ThreadStatus.BLOCKED,
        ThreadStatus.WAITING,
    }
)


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _iso_to_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


class SQLiteThreadRepository(BaseThreadRepository):
    """
    Persistent SQLite storage engine for IntentThreads, evidence, commitments,
    dependencies, proposals, verifications, and auditable lifecycle event history.
    """

    def __init__(self, db_path: str = "threadback.db", auto_seed: bool = True) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._initialize_schema()
        if auto_seed:
            self._seed_if_empty()

    def _connect(self) -> None:
        # If relative path, ensure directory exists
        path_obj = Path(self.db_path)
        if path_obj.parent and not path_obj.parent.exists():
            path_obj.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")

    def _initialize_schema(self) -> None:
        assert self._conn is not None
        schema_sql = """
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS commitments (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            due_at TEXT
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dependencies (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            blocking INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS thread_events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            source TEXT NOT NULL,
            description TEXT NOT NULL,
            payload TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS action_proposals (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            rationale TEXT NOT NULL,
            status TEXT NOT NULL,
            requires_confirmation INTEGER NOT NULL,
            confirmation_reason TEXT,
            inputs TEXT NOT NULL,
            preconditions TEXT NOT NULL,
            supporting_evidence_ids TEXT NOT NULL,
            supporting_commitment_ids TEXT NOT NULL,
            supporting_dependency_ids TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS thread_verifications (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            verified INTEGER NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            required_evidence TEXT NOT NULL,
            matched_evidence TEXT NOT NULL,
            missing_evidence TEXT NOT NULL,
            verified_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_commitments_thread ON commitments(thread_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_thread ON evidence(thread_id);
        CREATE INDEX IF NOT EXISTS idx_dependencies_thread ON dependencies(thread_id);
        CREATE INDEX IF NOT EXISTS idx_events_thread ON thread_events(thread_id);
        CREATE INDEX IF NOT EXISTS idx_verifications_thread ON thread_verifications(thread_id);
        CREATE INDEX IF NOT EXISTS idx_proposals_thread ON action_proposals(thread_id);
        """
        with self._conn:
            self._conn.executescript(schema_sql)

    def _seed_if_empty(self) -> None:
        """Seed demo threads only if the threads table is currently empty."""
        assert self._conn is not None
        cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM threads;")
        row = cursor.fetchone()
        if row and row["cnt"] == 0:
            logger.info(
                "Initializing SQLite repository with deterministic demo data..."
            )
            demo_threads = get_demo_threads()
            for thread in demo_threads:
                self.save_thread(thread)

    def get_thread(self, thread_id: str) -> IntentThread | None:
        assert self._conn is not None
        cursor = self._conn.execute("SELECT * FROM threads WHERE id = ?;", (thread_id,))
        row = cursor.fetchone()
        if not row:
            return None

        # Fetch commitments
        c_rows = self._conn.execute(
            "SELECT * FROM commitments WHERE thread_id = ?;", (thread_id,)
        ).fetchall()
        commitments = [
            Commitment(
                id=c["id"],
                description=c["description"],
                status=CommitmentStatus(c["status"]),
                due_at=_iso_to_dt(c["due_at"]),
            )
            for c in c_rows
        ]

        # Fetch evidence
        e_rows = self._conn.execute(
            "SELECT * FROM evidence WHERE thread_id = ?;", (thread_id,)
        ).fetchall()
        evidence_items = [
            Evidence(
                id=e["id"],
                type=EvidenceType(e["type"]),
                description=e["description"],
                source=e["source"],
                confidence=float(e["confidence"]),
                created_at=_iso_to_dt(e["created_at"]) or datetime.now(timezone.utc),
            )
            for e in e_rows
        ]

        # Fetch dependencies
        d_rows = self._conn.execute(
            "SELECT * FROM dependencies WHERE thread_id = ?;", (thread_id,)
        ).fetchall()
        dependencies = [
            Dependency(
                id=d["id"],
                description=d["description"],
                type=d["type"],
                status=DependencyStatus(d["status"]),
                blocking=bool(d["blocking"]),
            )
            for d in d_rows
        ]

        # Fetch events
        ev_rows = self._conn.execute(
            "SELECT * FROM thread_events WHERE thread_id = ? ORDER BY timestamp ASC;",
            (thread_id,),
        ).fetchall()
        events: list[ThreadEvent | Event] = []
        for ev in ev_rows:
            try:
                payload = json.loads(ev["payload"]) if ev["payload"] else {}
            except Exception:
                payload = {}
            events.append(
                ThreadEvent(
                    id=ev["id"],
                    thread_id=ev["thread_id"],
                    event_type=ev["event_type"],
                    type=ev["event_type"],
                    description=ev["description"],
                    timestamp=_iso_to_dt(ev["timestamp"]) or datetime.now(timezone.utc),
                    actor=ev["actor"],
                    source=ev["source"],
                    payload=payload,
                )
            )

        return IntentThread(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            status=ThreadStatus(row["status"]),
            priority=Priority(row["priority"]),
            confidence=float(row["confidence"]),
            created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
            last_activity_at=_iso_to_dt(row["last_activity_at"])
            or datetime.now(timezone.utc),
            commitments=commitments,
            evidence=evidence_items,
            dependencies=dependencies,
            events=events,
        )

    def list_threads(
        self,
        status: ThreadStatus | None = None,
        limit: int | None = None,
        unfinished_only: bool = True,
    ) -> list[IntentThread]:
        assert self._conn is not None
        query = "SELECT id FROM threads"
        params: list[Any] = []
        conditions: list[str] = []

        if unfinished_only:
            placeholders = ", ".join("?" for _ in UNFINISHED_STATUSES)
            conditions.append(f"status IN ({placeholders})")
            params.extend(s.value for s in UNFINISHED_STATUSES)

        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY rowid ASC"

        if limit is not None and limit >= 0:
            query += f" LIMIT {int(limit)}"

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        results: list[IntentThread] = []
        for r in rows:
            thread = self.get_thread(r["id"])
            if thread is not None:
                results.append(thread)
        return results

    def save_thread(self, thread: IntentThread) -> None:
        assert self._conn is not None
        with self._conn:
            # 1. Upsert thread
            self._conn.execute(
                """
                INSERT INTO threads (id, title, description, status, priority, confidence, created_at, updated_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    status=excluded.status,
                    priority=excluded.priority,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at,
                    last_activity_at=excluded.last_activity_at;
                """,
                (
                    thread.id,
                    thread.title,
                    thread.description,
                    thread.status.value,
                    thread.priority.value,
                    thread.confidence,
                    _dt_to_iso(thread.created_at),
                    _dt_to_iso(thread.updated_at),
                    _dt_to_iso(thread.last_activity_at),
                ),
            )

            # 2. Upsert commitments
            for c in thread.commitments:
                self._conn.execute(
                    """
                    INSERT INTO commitments (id, thread_id, description, status, due_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        description=excluded.description,
                        status=excluded.status,
                        due_at=excluded.due_at;
                    """,
                    (
                        c.id,
                        thread.id,
                        c.description,
                        c.status.value,
                        _dt_to_iso(c.due_at),
                    ),
                )

            # 3. Upsert evidence
            for e in thread.evidence:
                self._conn.execute(
                    """
                    INSERT INTO evidence (id, thread_id, type, description, source, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        type=excluded.type,
                        description=excluded.description,
                        source=excluded.source,
                        confidence=excluded.confidence,
                        created_at=excluded.created_at;
                    """,
                    (
                        e.id,
                        thread.id,
                        e.type.value,
                        e.description,
                        e.source,
                        e.confidence,
                        _dt_to_iso(e.created_at),
                    ),
                )

            # 4. Upsert dependencies
            for d in thread.dependencies:
                self._conn.execute(
                    """
                    INSERT INTO dependencies (id, thread_id, description, type, status, blocking)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        description=excluded.description,
                        type=excluded.type,
                        status=excluded.status,
                        blocking=excluded.blocking;
                    """,
                    (
                        d.id,
                        thread.id,
                        d.description,
                        d.type,
                        d.status.value,
                        1 if d.blocking else 0,
                    ),
                )

            # 5. Upsert events
            for ev in thread.events:
                event_type = getattr(ev, "event_type", ev.type)
                if hasattr(event_type, "value"):
                    event_type = event_type.value
                actor = getattr(ev, "actor", "system")
                source = getattr(ev, "source", "deterministic_engine")
                payload = getattr(ev, "payload", {})
                self._conn.execute(
                    """
                    INSERT INTO thread_events (id, thread_id, event_type, timestamp, actor, source, description, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        event_type=excluded.event_type,
                        timestamp=excluded.timestamp,
                        actor=excluded.actor,
                        source=excluded.source,
                        description=excluded.description,
                        payload=excluded.payload;
                    """,
                    (
                        ev.id,
                        thread.id,
                        str(event_type),
                        _dt_to_iso(ev.timestamp),
                        actor,
                        source,
                        ev.description,
                        json.dumps(payload),
                    ),
                )

    def update_thread_status(self, thread_id: str, status: ThreadStatus) -> None:
        assert self._conn is not None
        now_iso = _dt_to_iso(datetime.now(timezone.utc))
        with self._conn:
            self._conn.execute(
                "UPDATE threads SET status = ?, updated_at = ?, last_activity_at = ? WHERE id = ?;",
                (status.value, now_iso, now_iso, thread_id),
            )

    def add_evidence(self, thread_id: str, evidence: Evidence) -> None:
        assert self._conn is not None
        now_iso = _dt_to_iso(datetime.now(timezone.utc))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO evidence (id, thread_id, type, description, source, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    description=excluded.description,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    created_at=excluded.created_at;
                """,
                (
                    evidence.id,
                    thread_id,
                    evidence.type.value,
                    evidence.description,
                    evidence.source,
                    evidence.confidence,
                    _dt_to_iso(evidence.created_at),
                ),
            )
            self._conn.execute(
                "UPDATE threads SET updated_at = ?, last_activity_at = ? WHERE id = ?;",
                (now_iso, now_iso, thread_id),
            )

            # Record auditable event
            event_id = f"evt-evi-{evidence.id}"
            self._conn.execute(
                """
                INSERT INTO thread_events (id, thread_id, event_type, timestamp, actor, source, description, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING;
                """,
                (
                    event_id,
                    thread_id,
                    ThreadEventType.EVIDENCE_ADDED.value,
                    now_iso,
                    "system",
                    evidence.source,
                    f"Evidence added: {evidence.description}",
                    json.dumps(
                        {"evidence_id": evidence.id, "type": evidence.type.value}
                    ),
                ),
            )

    def get_evidence(self, thread_id: str) -> list[Evidence]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM evidence WHERE thread_id = ? ORDER BY created_at ASC;",
            (thread_id,),
        ).fetchall()
        return [
            Evidence(
                id=r["id"],
                type=EvidenceType(r["type"]),
                description=r["description"],
                source=r["source"],
                confidence=float(r["confidence"]),
                created_at=_iso_to_dt(r["created_at"]) or datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def update_dependency(self, thread_id: str, dependency: Dependency) -> None:
        assert self._conn is not None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO dependencies (id, thread_id, description, type, status, blocking)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    description=excluded.description,
                    type=excluded.type,
                    status=excluded.status,
                    blocking=excluded.blocking;
                """,
                (
                    dependency.id,
                    thread_id,
                    dependency.description,
                    dependency.type,
                    dependency.status.value,
                    1 if dependency.blocking else 0,
                ),
            )

    def update_commitment(self, thread_id: str, commitment: Commitment) -> None:
        assert self._conn is not None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO commitments (id, thread_id, description, status, due_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    description=excluded.description,
                    status=excluded.status,
                    due_at=excluded.due_at;
                """,
                (
                    commitment.id,
                    thread_id,
                    commitment.description,
                    commitment.status.value,
                    _dt_to_iso(commitment.due_at),
                ),
            )

    def add_event(self, thread_id: str, event: ThreadEvent | Event) -> None:
        assert self._conn is not None
        event_type = getattr(event, "event_type", event.type)
        if hasattr(event_type, "value"):
            event_type = event_type.value
        actor = getattr(event, "actor", "system")
        source = getattr(event, "source", "deterministic_engine")
        payload = getattr(event, "payload", {})

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO thread_events (id, thread_id, event_type, timestamp, actor, source, description, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    event_type=excluded.event_type,
                    timestamp=excluded.timestamp,
                    actor=excluded.actor,
                    source=excluded.source,
                    description=excluded.description,
                    payload=excluded.payload;
                """,
                (
                    event.id,
                    thread_id,
                    str(event_type),
                    _dt_to_iso(event.timestamp),
                    actor,
                    source,
                    event.description,
                    json.dumps(payload),
                ),
            )
            # Update last activity
            self._conn.execute(
                "UPDATE threads SET last_activity_at = ? WHERE id = ?;",
                (_dt_to_iso(event.timestamp), thread_id),
            )

    def get_events(self, thread_id: str) -> list[ThreadEvent]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM thread_events WHERE thread_id = ? ORDER BY timestamp ASC;",
            (thread_id,),
        ).fetchall()
        results: list[ThreadEvent] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"]) if r["payload"] else {}
            except Exception:
                payload = {}
            results.append(
                ThreadEvent(
                    id=r["id"],
                    thread_id=r["thread_id"],
                    event_type=r["event_type"],
                    type=r["event_type"],
                    description=r["description"],
                    timestamp=_iso_to_dt(r["timestamp"]) or datetime.now(timezone.utc),
                    actor=r["actor"],
                    source=r["source"],
                    payload=payload,
                )
            )
        return results

    def save_proposal(self, proposal: ActionProposal) -> None:
        assert self._conn is not None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO action_proposals (
                    id, thread_id, action_type, title, description, rationale, status,
                    requires_confirmation, confirmation_reason, inputs, preconditions,
                    supporting_evidence_ids, supporting_commitment_ids, supporting_dependency_ids,
                    risk_level, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    confirmation_reason=excluded.confirmation_reason,
                    inputs=excluded.inputs,
                    preconditions=excluded.preconditions;
                """,
                (
                    proposal.id,
                    proposal.thread_id,
                    proposal.action_type.value,
                    proposal.title,
                    proposal.description,
                    proposal.rationale,
                    proposal.status.value,
                    1 if proposal.requires_confirmation else 0,
                    proposal.confirmation_reason,
                    json.dumps(proposal.inputs),
                    json.dumps(proposal.preconditions),
                    json.dumps(proposal.supporting_evidence_ids),
                    json.dumps(proposal.supporting_commitment_ids),
                    json.dumps(proposal.supporting_dependency_ids),
                    proposal.risk_level.value,
                    _dt_to_iso(proposal.created_at),
                ),
            )

    def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM action_proposals WHERE id = ?;", (proposal_id,)
        ).fetchone()
        if not row:
            return None

        return ActionProposal(
            id=row["id"],
            thread_id=row["thread_id"],
            action_type=NextActionType(row["action_type"]),
            title=row["title"],
            description=row["description"],
            rationale=row["rationale"],
            status=ProposalStatus(row["status"]),
            requires_confirmation=bool(row["requires_confirmation"]),
            confirmation_reason=row["confirmation_reason"],
            inputs=json.loads(row["inputs"]),
            preconditions=json.loads(row["preconditions"]),
            supporting_evidence_ids=json.loads(row["supporting_evidence_ids"]),
            supporting_commitment_ids=json.loads(row["supporting_commitment_ids"]),
            supporting_dependency_ids=json.loads(row["supporting_dependency_ids"]),
            risk_level=RiskLevel(row["risk_level"]),
            created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        )

    def list_proposals(self, thread_id: str | None = None) -> list[ActionProposal]:
        assert self._conn is not None
        if thread_id is None:
            rows = self._conn.execute("SELECT * FROM action_proposals;").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM action_proposals WHERE thread_id = ?;", (thread_id,)
            ).fetchall()

        results: list[ActionProposal] = []
        for row in rows:
            results.append(
                ActionProposal(
                    id=row["id"],
                    thread_id=row["thread_id"],
                    action_type=NextActionType(row["action_type"]),
                    title=row["title"],
                    description=row["description"],
                    rationale=row["rationale"],
                    status=ProposalStatus(row["status"]),
                    requires_confirmation=bool(row["requires_confirmation"]),
                    confirmation_reason=row["confirmation_reason"],
                    inputs=json.loads(row["inputs"]),
                    preconditions=json.loads(row["preconditions"]),
                    supporting_evidence_ids=json.loads(row["supporting_evidence_ids"]),
                    supporting_commitment_ids=json.loads(
                        row["supporting_commitment_ids"]
                    ),
                    supporting_dependency_ids=json.loads(
                        row["supporting_dependency_ids"]
                    ),
                    risk_level=RiskLevel(row["risk_level"]),
                    created_at=_iso_to_dt(row["created_at"])
                    or datetime.now(timezone.utc),
                )
            )
        return results

    def save_verification(self, verification: ThreadVerification) -> None:
        assert self._conn is not None
        # Derive a stable verification record ID
        ts_suffix = int(verification.verified_at.timestamp() * 1000)
        ver_id = f"ver-{verification.thread_id}-{ts_suffix}"
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO thread_verifications (
                    id, thread_id, verified, confidence, reason, required_evidence,
                    matched_evidence, missing_evidence, verified_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING;
                """,
                (
                    ver_id,
                    verification.thread_id,
                    1 if verification.verified else 0,
                    verification.confidence,
                    verification.reason,
                    json.dumps(verification.required_evidence),
                    json.dumps(verification.matched_evidence),
                    json.dumps(verification.missing_evidence),
                    _dt_to_iso(verification.verified_at),
                ),
            )

    def get_latest_verification(self, thread_id: str) -> ThreadVerification | None:
        assert self._conn is not None
        row = self._conn.execute(
            """
            SELECT * FROM thread_verifications
            WHERE thread_id = ?
            ORDER BY verified_at DESC, rowid DESC
            LIMIT 1;
            """,
            (thread_id,),
        ).fetchone()
        if not row:
            return None

        return ThreadVerification(
            thread_id=row["thread_id"],
            verified=bool(row["verified"]),
            confidence=float(row["confidence"]),
            reason=row["reason"],
            required_evidence=json.loads(row["required_evidence"]),
            matched_evidence=json.loads(row["matched_evidence"]),
            missing_evidence=json.loads(row["missing_evidence"]),
            verified_at=_iso_to_dt(row["verified_at"]) or datetime.now(timezone.utc),
        )

    def count_threads(self) -> int:
        assert self._conn is not None
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM threads;").fetchone()
        return row["cnt"] if row else 0

    def reset(self, seed: bool = True) -> None:
        """Clear all stored data tables and optionally re-seed demo threads."""
        assert self._conn is not None
        with self._conn:
            self._conn.execute("DELETE FROM thread_events;")
            self._conn.execute("DELETE FROM thread_verifications;")
            self._conn.execute("DELETE FROM action_proposals;")
            self._conn.execute("DELETE FROM commitments;")
            self._conn.execute("DELETE FROM evidence;")
            self._conn.execute("DELETE FROM dependencies;")
            self._conn.execute("DELETE FROM threads;")
        if seed:
            self._seed_if_empty()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
