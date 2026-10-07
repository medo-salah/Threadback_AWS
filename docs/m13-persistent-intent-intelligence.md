# Threadback M13 — Persistent Intent Intelligence & Memory

> *"Threadback remembers what I intended to accomplish, understands how that intention evolved, detects when it is forgotten or blocked, and helps me resume it."*

---

## 1. Architectural Overview

Milestone 13 (M13) elevates Threadback from an interactive multi-turn conversational agent into an authoritative **persistent intent-memory agent**. It adds structured intent tracking, goal evolution history, proactive decay detection, composite urgency prioritization (Intent Radar), factual state differencing ("What Changed?"), and full DEFER / RESUME / ABANDON lifecycle state handling.

### Non-Negotiable Invariants Enforced

1. **Exactly 9 Canonical MCP Tools**: No 10th tool was added. The MCP contract on `/mcp` remains exactly 9 canonical tools:
   `discover_unfinished_threads`, `get_thread_context`, `find_thread_blockers`, `analyze_thread`, `suggest_next_action`, `prepare_action`, `execute_action`, `verify_thread_completion`, and `close_thread`.
2. **MCP Streamable HTTP Protocol `2025-11-25`**: Preserved strictly on the `/mcp` endpoint for Amazon Alexa+ and AWS Bedrock AgentCore.
3. **Action Preparation & Execution Dispatch**: All external mutations (including M13 goal evolutions, deferrals, resumes, and abandonments) follow `prepare_action` $\to$ `execute_action`.
4. **Domain Services Convergence**: All mutation paths (conversational `/api/agent/chat` and external MCP `/mcp`) converge on the exact same deterministic domain services: `IntentMemoryService`, `LifecycleService`, and `IntentRadarService`.
5. **Strictly Immutable `original_goal`**: A thread's `original_goal` is recorded at discovery and can **never** be altered, overwritten, or deleted by any evolution or lifecycle event.
6. **Explicit Persistence vs. Speculative Hold**: Explicit, unambiguous natural-language goal revisions persist directly through auditable `INTENTION_EVOLVED` events. Ambiguous or speculative statements ("I might change...", "Maybe I should...") are held for clarification and **never** mutate durable state.
7. **Zero Fabrication**: Reasons, blockers, evidence, and completion states are derived exclusively from verified domain records and explicit user instructions — never fabricated by an LLM.
8. **Fundamental Safety Invariant**: `EXECUTION_SUCCESS != VERIFIED_COMPLETION`. Simulated action execution never bypasses factual verification.
9. **Regression Safety**: All 302 pre-existing M0–M12 tests remain green (total suite now 321 tests).

---

## 2. Intent Memory & Evolution Engine

### Domain Models

* **`original_goal`** *(str)*: Permanent record of the user's initial intention.
* **`current_goal`** *(str)*: Active working objective, updated upon validated evolutions.
* **`IntentEvolution`**:
  ```python
  class IntentEvolution(BaseModel):
      id: str
      thread_id: str
      previous_goal: str
      revised_goal: str
      reason: str
      timestamp: datetime
      trigger_event_id: str | None = None
  ```

### Authoritative Domain Service: `IntentMemoryService`

* **`evolve_goal(thread_id, revised_goal, reason, reference_time=None)`**:
  - Validates thread exists and is not in terminal status (`COMPLETED` or `ABANDONED`).
  - Enforces non-empty goal and non-empty reason.
  - Updates `current_goal` while keeping `original_goal` strictly immutable.
  - Atomically records an `INTENTION_EVOLVED` event into thread event history and persists the `IntentEvolution` record.
* **`get_evolution_history(thread_id)`**: Chronological audit trail of all historical goal revisions.
* **`get_intent_summary(thread_id)`**: Holistic overview combining current status, goals, blockers, commitments, and decay state.

---

## 3. Intent Radar & Decay Detection Engine

### Decay States (`DecayState`)

Deterministic classification based on inactivity duration and commitment deadlines:
* **`HEALTHY`**: Inactive < 3 days and no deadline pressure.
* **`ATTENTION`**: Inactive 3–7 days OR deadline approaching within 72 hours.
* **`DECAYING`**: Inactive 7–14 days OR inactive ≥ 4 days with active blockers.
* **`STALE`**: Inactive ≥ 14 days OR deadline overdue by ≥ 7 days.

### Composite Urgency Formula

Threads are prioritized across the intent radar using a deterministic weighted urgency formula:

$$U = 0.30 \cdot S_{\text{priority}} + 0.25 \cdot S_{\text{deadline}} + 0.20 \cdot S_{\text{decay}} + 0.15 \cdot S_{\text{blocker}} + 0.10 \cdot S_{\text{commitments}}$$

Where:
* $S_{\text{priority}} \in \{1.0, 0.6, 0.2\}$ based on `Priority` (HIGH, MEDIUM, LOW)
* $S_{\text{deadline}} \in \{1.0 \text{ (overdue)}, 0.9 \text{ (imminent)}, 0.6 \text{ (approaching)}, 0.2 \text{ (normal)}\}$
* $S_{\text{decay}} \in \{1.0 \text{ (STALE)}, 0.8 \text{ (DECAYING)}, 0.5 \text{ (ATTENTION)}, 0.1 \text{ (HEALTHY)}\}$
* $S_{\text{blocker}} \in \{0.9 \text{ (blocked)}, 0.6 \text{ (waiting)}, 0.3 \text{ (active)}\}$
* $S_{\text{commitments}} = \frac{\text{open commitments}}{\max(1, \text{total commitments})}$

---

## 4. Deterministic "What Changed?" Differential Engine

Evaluates changes between two points in time using a 4-tier differential anchor resolution:
1. **Tier 1 (Explicit range)**: Specific timestamp provided by user.
2. **Tier 2 (Conversation checkpoint)**: `conversation_checkpoints` table anchor for multi-turn session.
3. **Tier 3 (Thread interaction)**: `thread.last_interaction_at`.
4. **Tier 4 (System baseline)**: `DEFAULT_ANALYSIS_REFERENCE_TIME`.

Produces structured `StateChangeItem` entries across:
* `GOAL_REVISED`: Previous goal $\to$ new goal with reason.
* `STATUS_CHANGED`: Active, Waiting, Blocked, Deferred transitions.
* `EVIDENCE_ADDED`: New communications, calendar items, notes.
* `BLOCKER_RESOLVED`: Dependency or commitment fulfillment.

---

## 5. Defer, Resume, Abandon Lifecycle Handling

* **`DEFER`**: Transitions open thread to `ThreadStatus.DEFERRED`, records `deferred_until`, records `THREAD_DEFERRED` event. Thread is excluded from regular active discovery while preserving full historical context.
* **`RESUME`**: Returns thread to active lifecycle (`ACTIVE`, `WAITING`, or `BLOCKED` depending on unresolved blockers), clears `deferred_until`, records `THREAD_RESUMED` event.
* **`ABANDON`**: Transitions thread to `ThreadStatus.ABANDONED` with explicit reason, recording `THREAD_ABANDONED` event. Preserves all history; never deletes evidence or audit trails.

---

## 6. Safe Action Proposal Dispatch (`prepare_action` $\to$ `execute_action`)

To satisfy MCP Invariant 1 (exactly 9 tools) and Invariant 3 (prepare $\to$ execute pattern), M13 exposes durable mutations through typed action proposals:

| Action Type | Parameters | Deterministic Proposal ID | Execution Mode | Execution Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `EVOLVE_INTENTION` | `new_goal`, `reason` | `derive_proposal_id(...)` | `PERSISTENT_MUTATION` | Updates `current_goal`, persists `IntentEvolution`, emits `INTENTION_EVOLVED` |
| `DEFER_INTENTION` | `deferred_until`, `reason` | `derive_proposal_id(...)` | `PERSISTENT_MUTATION` | Updates status to `DEFERRED`, sets `deferred_until`, emits `THREAD_DEFERRED` |
| `RESUME_INTENTION` | `reason` | `derive_proposal_id(...)` | `PERSISTENT_MUTATION` | Updates status to `ACTIVE`, clears `deferred_until`, emits `THREAD_RESUMED` |
| `ABANDON_INTENTION`| `reason` | `derive_proposal_id(...)` | `PERSISTENT_MUTATION` | Updates status to `ABANDONED`, sets `abandoned_reason`, emits `THREAD_ABANDONED` |

### Critical Safety Invariants:
1. **External Operational Actions remain SIMULATED ONLY**: Actions like sending an email or submitting an application execute strictly in `ExecutionMode.SIMULATED`. Zero real-world side effects.
2. **Internal Threadback State Mutations are PERSISTENT_MUTATION**: Actions modifying goals or lifecycle states execute in `ExecutionMode.PERSISTENT_MUTATION`. They intentionally modify durable SQLite records and audit trails.
3. **Execution Distinction**: `Persistent Threadback mutation != external-world action`. An abandoned thread is an intentional, durable lifecycle state change within Threadback memory, never described as simulated external work.
4. **Completion Invariant**: `EXECUTION_SUCCESS != VERIFIED_COMPLETION` remains strictly preserved across both categories.

---

## 7. The Six Deterministic Demo Scenarios

1. **Scenario 1 — Intent Radar Scan**:
   - Query: *"Scan my intent radar"*
   - Behavior: Scans all open threads, computes composite urgency scores, identifies Top Focus (`thread-university-application`), renders radar prioritization report.
2. **Scenario 2 — Intent Decay Detection**:
   - Query: *"Which intentions are decaying?"*
   - Behavior: Filters threads with decay states `ATTENTION`, `DECAYING`, or `STALE`, explaining exact days of inactivity and overdue commitments.
3. **Scenario 3 — What Changed? Differential**:
   - Query: *"What changed on University Application?"*
   - Behavior: Resolves checkpoint anchor, computes factual state delta, highlights blocker status and recent evidence additions.
4. **Scenario 4 — Explicit Goal Evolution**:
   - Query: *"Update my dentist goal to: Schedule teeth cleaning and consult on wisdom tooth"*
   - Behavior: Prepares `EVOLVE_INTENTION`, executes dispatch in `PERSISTENT_MUTATION` mode, mutates `current_goal`, records `INTENTION_EVOLVED` audit event, preserves immutable `original_goal`.
5. **Scenario 5 — Ambiguous Evolution Hold**:
   - Query: *"I might want to change my dentist appointment to another clinic maybe"*
   - Behavior: Detects ambiguity, pauses mutation, requests clarification, leaves durable state 100% intact.
6. **Scenario 6 — Lifecycle Defer & Resume**:
   - Queries: *"Defer Client Quarterly Report until next Monday"* followed by *"Resume Client Quarterly Report"*
   - Behavior: Transitions through `DEFERRED` and `ACTIVE` states with auditable lifecycle events and timestamps.

---

## 8. Quality Gate Verification Results

| Quality Gate | Requirement | Status | Result |
| :--- | :--- | :--- | :--- |
| **Backend Unit & Integration Tests** | `pytest -q` | **PASSED** | 331 passed in 23.96s |
| **Backend Lint** | `ruff check app tests` | **PASSED** | All checks passed |
| **Backend Format** | `ruff format --check app tests` | **PASSED** | 72 files already formatted |
| **Frontend Lint** | `npm run lint` (oxlint) | **PASSED** | 0 warnings, 0 errors |
| **Frontend Build** | `npm run build` (tsc + vite) | **PASSED** | Built in 168ms without errors |
| **MCP Tool Count** | Exactly 9 canonical tools | **PASSED** | Verified by `test_m12_canonical_mcp_tool_count` |
| **MCP Protocol Version** | `2025-11-25` | **PASSED** | Verified by `test_mcp_protocol_version` |
| **Restart Persistence** | SQLite schema & checkpoints | **PASSED** | Verified by `test_safety_audit_10_restart_persistence_preserves_m13_mutations` |
| **M0–M12 Regression Suite** | Zero regressions | **PASSED** | All 302 prior tests + 29 M13 tests pass (331 total) |
| **Secrets & Debug Check** | No credentials or scratch files | **PASSED** | Clean git working directory |
