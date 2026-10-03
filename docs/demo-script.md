# Threadback — Live Demo Script & Evaluator Walkthrough

**Scenario:** The University Application Intent Recovery  
**Target Duration:** 3–5 minutes  
**Audience:** Hackathon Evaluators & Judges

---

## Opening (30 Seconds)

> *"Hi everyone. Traditional assistants and to-do apps fail because they treat human commitments as static checkboxes. When you fall behind, they spam notifications without understanding what is actually blocking you.*
> 
> *Our core insight is simple: **People don't forget tasks. They forget intentions.***
> 
> *Threadback is an intent-recovery agent. It pairs natural conversation with a deterministic, evidence-based engine to reconstruct open loops, identify blockers, safely prepare actions, verify independent evidence, and close intentions."*

---

## Live Demonstration Flow

### Phase 1 — Discover

**Spoken User Input:**
> *"What am I forgetting?"*

**Behind the Scenes:**
* Agent orchestrates `discover_unfinished_threads` and `analyze_thread` via MCP.
* Evaluates attention level and urgency across all open intent threads in SQLite.

**What the Evaluator Should Observe:**
* Natural-language response summarizing unfinished intentions.
* Clear highlight of the **University Application** thread (Priority: HIGH, Status: BLOCKED).
* Conversational context established: session now tracks University Application as active context.

---

### Phase 2 — Reconstruct

**Spoken User Input:**
> *"Where did I leave off?"*

**Behind the Scenes:**
* Agent uses pronoun resolution to anchor `"where did I leave off"` to the University Application thread.
* Orchestrates `get_thread_context` and `analyze_thread`.

**What the Evaluator Should Observe:**
* No need to repeat the thread name; natural conversational continuity.
* Detailed context reconstruction: application deadline, transcripts received, recommendation letter dependency.
* Status clearly displayed as `BLOCKED`.

---

### Phase 3 — Understand Blocker

**Spoken User Input:**
> *"Why haven't I finished it?"*

**Behind the Scenes:**
* Agent resolves `"it"` to the active thread and calls `find_thread_blockers`.

**What the Evaluator Should Observe:**
* Precise root cause explanation: the application is blocked waiting on an external dependency (recommendation letter from Professor Smith).
* Proactive prompt asking if the user would like a recommended next action.

---

### Phase 4 — Decide

**Spoken User Input:**
> *"What should I do?"*

**Behind the Scenes:**
* Agent calls `suggest_next_action`.
* Deterministic engine selects an unblocker action based on priority and blocker overlap.

**What the Evaluator Should Observe:**
* Clear recommended next step: send a follow-up inquiry to Professor Smith.
* Clear statement that confirmation will be required before execution.

---

### Phase 5 — Prepare

**Spoken User Input:**
> *"Help me finish it."*

**Behind the Scenes:**
* Agent calls `prepare_action`.
* Creates an authoritative `ActionProposal` with a unique ID (e.g., `proposal-uni-follow-up-1`), sets status to `CONFIRMATION_REQUIRED`, and pauses.

**What the Evaluator Should Observe:**
* **Safety Pause**: The agent stops and asks for explicit confirmation.
* Action details displayed: Proposal ID, Action Type, Risk Level (`MEDIUM`).
* Explicit safety warning: **Execution is strictly SIMULATED**.

---

### Phase 6 — Confirm & Simulate

**Spoken User Input:**
> *"Yes, go ahead."*

**Behind the Scenes:**
* Agent verifies explicit affirmative confirmation using `is_explicit_confirmation`.
* Calls `execute_action(proposal_id=..., confirmed=True, execution_mode="SIMULATED")`.
* Emits a simulated execution event to the thread audit ledger in SQLite.

**What the Evaluator Should Observe:**
* Simulated execution badge: `⚡ SIMULATED ACTION EXECUTED`.
* Clear safety notice: **SIMULATED ACTION ≠ VERIFIED COMPLETION**.
* The thread remains `BLOCKED` in storage. Simulating an email does **not** complete the application.

---

### Phase 7 — External Evidence Arrival

**Demonstration Action:**
* In the live scenario, independent factual evidence arrives (simulated via portal check or direct evidence ingestion).
* A structured evidence record is added:
  * Description: *"Recommendation letter received from Ahmed; application submission completed"*
  * Source: *"Admissions Portal"*
  * Confidence: *0.99*

**What the Evaluator Should Observe:**
* Intent memory in SQLite now contains the factual proof needed for completion.

---

### Phase 8 — Verify Completion

**Spoken User Input:**
> *"Is it actually finished?"*

**Behind the Scenes:**
* Agent orchestrates `verify_thread_completion`.
* Deterministic Verification Engine evaluates Rules A through E against SQLite data.
* Rule D matches: required completion evidence is present, resolving both the blocker and open commitment.

**What the Evaluator Should Observe:**
* Verification badge: `🔍 DETERMINISTIC VERIFICATION`.
* Status: **`VERIFIED`** (VERIFIED by deterministic completion rules).
* Reason: *"All required commitments and blockers resolved by factual evidence."*
* Thread is ready for safe closure.

---

### Phase 9 — Close Intent Thread

**Spoken User Input:**
> *"Close it."*

**Behind the Scenes:**
* Agent calls `verify_thread_completion` (to guarantee invariant) followed by `close_thread`.
* Lifecycle service transitions thread status from `BLOCKED` → `COMPLETED`.
* Emits final closure audit event.

**What the Evaluator Should Observe:**
* Completion banner: `🏁 INTENT THREAD COMPLETED`.
* Full 10-step Chronological Lifecycle Memory rendered in UI:
  1. Intent Discovered
  2. Context Reconstructed
  3. Blocker Identified
  4. Next Action Suggested
  5. Action Proposal Prepared
  6. Explicit Confirmation Validated
  7. Action Simulated (`SIMULATED ACTION ≠ VERIFIED COMPLETION`)
  8. Factual Evidence Received
  9. Completion Deterministically Verified
  10. Thread Closed & Completed
* Invariant verified: **`VERIFIED → CLOSED → COMPLETED`**.

---

## Demo Reset (For Evaluator Retesting)

To prove determinism and repeatability:

1. Click the **`Reset Demo`** button in the top navigation bar (or `POST /api/agent/demo-reset`).
2. Observe conversation state cleared and persistent SQLite tables re-seeded to original initial demo state.
3. Rerun any phase or conversational variation with 100% identical, predictable results.
