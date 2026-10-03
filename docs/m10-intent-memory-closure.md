# Threadback — Milestone M10: Intent Memory & Lifecycle Closure

**Milestone:** M10  
**Status:** Complete  
**Theme:** Persistent Intent Memory + Evidence-Based Verification & Closure  
**Canonical Protocol:** MCP `2025-11-25` (Streamable HTTP at `/mcp`)  
**Canonical Tools:** Exactly 9 domain tools  

---

## 1. Executive Summary

Milestone M10 evolves Threadback from a system that analyzes, proposes, and simulates actions on transient in-memory state into a persistent system capable of **remembering an intention across time and deterministically verifying when that intention has actually been completed**.

Before M10, Threadback operated on deterministic demo data loaded at startup. Action execution was simulated, but the intention lifecycle had no auditable history across restarts, and no mechanism existed to verify whether an intention was truly finished.

M10 introduces two foundational capabilities:

1. **Intent Memory:**
   - Persistent storage for `IntentThread` aggregates, supporting evidence, commitments, dependencies, action proposals, and auditable event history.
   - Local SQLite persistence with WAL mode, foreign keys, and indexes via a clean repository abstraction (`BaseThreadRepository`).
   - Thread history reconstruction ("Where did I leave off?").
   - Data survival across application restarts without overwriting mutated state.

2. **Lifecycle Closure:**
   - Deterministic verification engine (`VerificationService`) implementing Rules A–E.
   - Safe lifecycle closure (`LifecycleService`) transitioning verified threads to `COMPLETED`.
   - Enforcement of the core invariant: **`EXECUTION_SUCCESS != COMPLETION`**. Action execution is strictly distinguished from intention completion.
   - Prevention of premature closure: `close_thread` cannot bypass `verify_thread_completion`.

```text
DISCOVER → UNDERSTAND → PRIORITIZE → PREPARE → CONFIRM → ACT → VERIFY → CLOSE
```

---

## 2. Core Invariant & Architectural Principles

### 2.1 The Central Invariant

> **An action being executed does not mean an intention has been completed. Completion must be verified through evidence.**

```text
Action Executed (SIMULATED)
        ↓
New / Existing Evidence Recorded
        ↓
verify_thread_completion (Deterministic Rules A–E)
        ↓
If VERIFIED: close_thread (Validated Safety Invariants) → COMPLETED
If NOT VERIFIED: Thread remains OPEN with missing evidence reasons
```

### 2.2 Authority Boundary

The deterministic domain engine is the sole source of truth:
- The LLM **never** decides thread existence or status.
- The LLM **never** fabricates evidence or decides verification outcomes.
- The LLM **never** authorizes thread closure.
- The frontend **never** directly mutates thread status to `COMPLETED`.
- All closures require verified backend evidence and emit persistent `ThreadEvent` audit records.

---

## 3. Persistent Data Architecture

### 3.1 Repository Abstraction

Threadback domain services depend exclusively on the abstract interface `BaseThreadRepository`, decoupling business logic from SQLite:

```text
Domain Services (ThreadService, VerificationService, LifecycleService, ExecutionService)
                       │
                       ▼
             BaseThreadRepository (app.repositories.base)
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
SQLiteThreadRepository     InMemoryThreadRepository
(Production / Dev)            (Isolated Unit Tests)
```

### 3.2 SQLite Schema

Implemented in `backend/app/repositories/sqlite_repository.py`:

```sql
-- 1. Intent Threads Aggregate
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

-- 2. Evidence Records
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- 3. Commitments
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    due_at TEXT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- 4. Dependencies & Blockers
CREATE TABLE IF NOT EXISTS dependencies (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    description TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    blocking INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- 5. Auditable Lifecycle History
CREATE TABLE IF NOT EXISTS thread_events (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    source TEXT NOT NULL,
    description TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- 6. Action Proposals
CREATE TABLE IF NOT EXISTS action_proposals (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL,
    requires_confirmation INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- 7. Verification Records
CREATE TABLE IF NOT EXISTS thread_verifications (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    verified INTEGER NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    required_evidence TEXT NOT NULL,
    matched_evidence TEXT NOT NULL,
    missing_evidence TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
```

### 3.3 Database Guarantees
- **WAL Mode (`PRAGMA journal_mode=WAL`):** Enables high concurrency between MCP tool readers and write transactions.
- **Foreign Keys (`PRAGMA foreign_keys=ON`):** Enforces relational integrity across aggregates.
- **Seed Non-Destructiveness:** Seed data initializes only when the database is empty; application restarts preserve all mutations.

### 3.4 Local SQLite vs Remote AgentCore Persistence

Threadback explicitly distinguishes between the local M10 persistence architecture and future remote cloud deployment:

```text
Local M10 Architecture:
Frontend / Agent
      ↓
MCP
      ↓
Deterministic Core
      ↓
SQLite
      ↓
Persistent Local Intent Memory

Future Remote Deployment:
Alexa+ / External MCP Client
      ↓
AgentCore Runtime
      ↓
Threadback MCP
      ↓
Deterministic Core
      ↓
Future Durable Cloud Repository
```

> **Important Persistence Boundary:** SQLite is the M10 local persistence implementation. Durable remote AgentCore persistence is not implemented or verified in M10 and remains a future deployment concern.

---

## 4. Intent Memory & Event History

Each lifecycle transition appends a `ThreadEvent` record to `thread_events`. `ThreadEvent` records are treated as append-only audit records by the application; lifecycle code does not modify existing events.

| Event Type | Trigger |
| :--- | :--- |
| `THREAD_DISCOVERED` | Intent thread ingested or discovered |
| `EVIDENCE_ADDED` | New factual evidence associated with thread |
| `BLOCKER_IDENTIFIED` | Blocking dependency detected |
| `ACTION_PREPARED` | Action proposal constructed and registered |
| `ACTION_CONFIRMED` | Explicit user authorization recorded |
| `ACTION_EXECUTED` | Simulated action executed |
| `VERIFICATION_STARTED` | Verification engine initiates rule evaluation |
| `VERIFICATION_PASSED` | All verification rules satisfied |
| `VERIFICATION_FAILED` | Verification failed due to blocker or missing evidence |
| `THREAD_COMPLETED` | Thread transitioned to `COMPLETED` |
| `THREAD_ABANDONED` | Thread marked as abandoned |

### History Reconstruction
Calling `thread_service.reconstruct_history(thread_id)` returns the chronological log of what occurred on that intention, answering:
> *"Where did I leave off with the university application?"*

---

## 5. Deterministic Verification Engine (`VerificationService`)

Verification is handled by `VerificationService` using five deterministic rules:

### Rule A — No Evidence
If the thread has no evidence records:
- `verified = false`
- `reason = "Insufficient evidence to verify completion."`

### Rule B — Blocking Dependency
If an active blocker (`blocking == True` and `status == OPEN`) exists and has no resolving evidence:
- `verified = false`
- `reason = "The recommendation letter remains unresolved."` (or corresponding blocker name)
- `missing_evidence = [blocker.description]`

### Rule C — Open Commitment
If a mandatory commitment (`status == OPEN`) remains unfulfilled:
- `verified = false`
- `reason = "Open commitment '<description>' remains unfulfilled."`
- `missing_evidence = [commitment.description]`

### Rule D — Completion Evidence Present
If required completion evidence is present and no blocking condition remains:
- `verified = true`
- `confidence = thread.confidence`
- `reason = "Required completion evidence is present and no blocking dependency remains."`
- `matched_evidence = [evidence_ids]`

### Rule E — Contradictory Evidence
If evidence contains contradictory indicators (e.g., *rejected*, *failed*, *cancelled*, *denied*, *dispute*):
- `verified = false`
- `reason = "Contradictory evidence indicates the intention is unresolved: <description>"`

*Note: Evidence containing in-progress indicators ("requesting", "awaiting", "draft") is disqualified from satisfying resolution criteria.*

---

## 6. Protected Lifecycle Closure (`LifecycleService`)

A thread can only transition to `COMPLETED` through `close_thread`, which validates seven conditions:

1. **Existence:** Thread must exist in repository.
2. **Not Abandoned:** Thread must not be in `ABANDONED` status.
3. **Not Already Completed:** Idempotent check returning `ALREADY_COMPLETED` without duplicate events.
4. **Verification Record Exists:** Verification must have been executed.
5. **Verification Succeeded:** Latest verification must have `verified == True`.
6. **Completion Evidence Valid:** Evidence from verification must remain present on the thread.
7. **No New Blockers:** No blocking conditions introduced post-verification.

If any check fails:
- Closure is **REJECTED**.
- No status mutation occurs.
- A deterministic rejection reason is returned.

---

## 7. Canonical MCP Interface (9 Tools)

All tools communicate over Streamable HTTP at `/mcp` using MCP protocol `2025-11-25`:

```text
Threadback MCP
├── 1. discover_unfinished_threads (M3)
├── 2. get_thread_context          (M3)
├── 3. find_thread_blockers        (M3)
├── 4. analyze_thread              (M4)
├── 5. suggest_next_action         (M5)
├── 6. prepare_action              (M6)
├── 7. execute_action              (M7)
├── 8. verify_thread_completion    (M10)
└── 9. close_thread                (M10)
```

### Tool 8: `verify_thread_completion`
- **Inputs:** `{"thread_id": "thread-university-application"}`
- **Output:**
```json
{
  "thread_id": "thread-university-application",
  "verified": true,
  "confidence": 0.98,
  "reason": "Required completion evidence is present and no blocking dependency remains.",
  "required_evidence": ["Completion evidence verifying resolved dependencies and commitments"],
  "matched_evidence": ["evi-uni-demo-res"],
  "missing_evidence": []
}
```

### Tool 9: `close_thread`
- **Inputs:** `{"thread_id": "thread-university-application"}`
- **Output:**
```json
{
  "thread_id": "thread-university-application",
  "closure_status": "COMPLETED",
  "event_id": "evt-close-thread-university-application-1790930060055",
  "message": "Thread 'University Application' was successfully verified and closed.",
  "closed_at": "2026-10-02T08:34:20Z"
}
```

---

## 8. Canonical 6-Phase Demo Scenario

The complete end-to-end flow is validated in `tests/test_agent_lifecycle.py::test_agent_complete_m10_demo_scenario`:

```text
Phase 1: Discover
  User: "What am I forgetting?"
  Agent: Discovers unfinished University Application (BLOCKED)

Phase 2: Reconstruct
  User: "Where did I leave off with the university application?"
  Agent: Reconstructs audit history from persistent memory: recommendation letter blocker identified, follow-up simulated

Phase 3: Act
  User: "Help me finish the application."
  Agent: Prepares action proposal -> Halts for confirmation
  User: "Yes, go ahead."
  Agent: Executes action in SIMULATED mode -> Records audit event

Phase 4: New Evidence
  Structured persisted evidence chain introduced into SQLite:
    Evidence 1: Recommendation letter received.
    Evidence 2: Application submission completed.

Phase 5: Verify
  User: "Is it actually finished?"
  Agent: Invokes verify_thread_completion:
    Deterministic criteria evaluated against persisted facts:
      - required evidence present
      - blocker resolved
      - no mandatory open commitment
      - no contradictory evidence
    Result: VERIFIED
    (Completion is strictly based on structured persisted evidence, not merely on an LLM-generated statement)

Phase 6: Close
  User: "Close the thread."
  Agent: Invokes close_thread -> Status: COMPLETED
```

---

## 9. Verification & Test Suite Results

The complete verification test suite passes with **zero regressions**:

```bash
.venv/bin/pytest -v
============================= 267 passed in 10.35s ==============================
```

### Test Coverage Summary

| Test Module | Tests | Verifications |
| :--- | :--- | :--- |
| `test_sqlite_repository.py` | 5 | Initial seeding, restart persistence, non-destructive reload, proposal/verification storage, persistent ActionProposal authority & restart idempotency |
| `test_verification_service.py` | 7 | Rules A–E, no status mutation during verification, unknown thread errors |
| `test_lifecycle_closure.py` | 6 | Successful closure, unverified rejection, blocked rejection, idempotency, audit events |
| `test_m10_mcp_tools.py` | 4 | Canonical 9 tools check, verify tool HTTP execution, close tool HTTP execution, error handling |
| `test_agent_lifecycle.py` | 3 | Agent verification inquiry, agent closure safety invariant, 6-phase demo walkthrough |
| `test_execution_service.py` | 16 | M7 confirmation, ready proposals, rejection on abandoned/unknown threads |
| `test_next_action_service.py` | 20 | M5 next-action decision rules, tie-breaking, confidence formulas |
| `test_mcp_http_tools.py` | 17 | Streamable HTTP endpoint parity across tools |
| `test_mcp_tools.py` | 28 | Read-only invariant, tool schemas, discover/context/blockers |
| Existing Regression Suites | 161 | M0–M9 domain tests, router tests, performance tests |
| **Total** | **267** | **100% Pass Rate** |

### Quality & Linter Checks
- **Backend:** `ruff check app tests` → `All checks passed!`
- **Frontend Linter:** `oxlint` → `Found 0 warnings and 0 errors.`
- **Frontend Build:** `tsc -b && vite build` → `✓ built in 98ms`

---

## 10. M10 Acceptance Checklist

- [x] **Persistent ActionProposal Authority:** `ActionProposal` persists in SQLite; authoritative for execution and idempotency after restart.
- [x] **Intent Memory:** IntentThreads, evidence, commitments, dependencies, proposals, and events persist in SQLite.
- [x] **Restart Survival:** Data survives application restart without losing mutated state.
- [x] **Deterministic Verification:** `VerificationService` evaluates Rules A–E without LLM authority.
- [x] **Protected Closure:** `close_thread` enforces verification prerequisite and closure safety rules.
- [x] **Auditable History:** `ThreadEvent` records are treated as append-only audit records by the application; lifecycle code does not modify existing events.
- [x] **Canonical MCP:** Exactly 9 canonical tools exposed over Streamable HTTP (`2025-11-25`).
- [x] **Agent Orchestration:** Agent handles verification and closure flows safely.
- [x] **Frontend:** Exposes chronological history timeline, verification status, and completion state.
- [x] **Persistence Boundaries:** Local SQLite explicitly distinguished from future remote AgentCore cloud deployment.
- [x] **Strict Safety:** `SIMULATED` execution mode maintained; no real-world external side effects.
- [x] **Regressions:** All 242 previous tests + 25 M10 tests pass (267 total).
