# Threadback — Next Action Engine (M5)

## Overview

The **Next Action Engine** is Threadback's deterministic planning service. Given the current state of an unfinished `IntentThread` and its structured M4 `ThreadAnalysis`, the engine answers:

> **“Given the current state of an unfinished Intent Thread, what should the user do next?”**

The engine is **planning only** and operates strictly **pre-LLM**. It does **not execute actions**, call external APIs, mutate state, or interact with third-party systems.

---

## 1. Architecture & Pipeline

```text
IntentThread
     ↓
AnalysisService.analyze() [M4]
     ↓
ThreadAnalysis
     ↓
NextActionService.suggest_action() [M5]
     ↓
NextActionSuggestion
     ↓
MCP Tool: suggest_next_action
```

The Next Action Engine consumes the rich factual layer computed by M3/M4 (evidence aggregation, blockers, open commitments, attention signals, and confidence) and maps it into a concrete, user-facing action recommendation.

---

## 2. Decision Categories

The engine classifies recommendations into five mutually exclusive categories:

| Action Category | Purpose | Typical Scenario | Example |
|---|---|---|---|
| `DIRECT_NEXT_ACTION` | Actionable step on an unblocked thread | Open commitment with earliest deadline | `"Complete M3 domain layer and MCP tools implementation"` |
| `UNBLOCKER_ACTION` | Directly address or remove an active blocker | Thread is blocked by an external dependency | `"Resolve blocker: Recommendation letter from Ahmed"` |
| `FOLLOW_UP_ACTION` | Follow up on a pending external dependency | Thread is in `WAITING` status | `"Follow up on pending dependency: Client response and data sign-off on Q3 deliverables"` |
| `GATHER_EVIDENCE_ACTION` | Gather missing context when evidence is insufficient | Thread lacks sufficient evidence to plan reliably | `"Gather additional context and documentation for 'Vague Thread'"` |
| `NO_ACTION` | No action required | Thread is completed, abandoned, or closed | `"No action required; thread 'Tax Filing 2025' is completed."` |

---

## 3. Decision Tree & Precedence Rules

Recommendations are derived in a strict deterministic order:

```text
Step 0: Terminal / Closed Thread?
    ├── YES (COMPLETED / ABANDONED) → NO_ACTION
    └── NO  ↓

Step 1: Insufficient Evidence?
    ├── YES (evidence_summary.is_sufficient is False) → GATHER_EVIDENCE_ACTION
    └── NO  ↓

Step 2: Active Blocking Dependency?
    ├── YES (active blockers exist and thread not in WAITING lifecycle) → UNBLOCKER_ACTION
    └── NO  ↓

Step 3: Waiting Dependency?
    ├── YES (status == WAITING with open dependencies, or open non-blocking dependencies) → FOLLOW_UP_ACTION
    └── NO  ↓

Step 4: Open Actionable Commitment?
    ├── YES (commitments with status == OPEN exist) → DIRECT_NEXT_ACTION
    └── NO  ↓

Step 5: Unfinished Thread without Commitments or Blockers?
    ├── YES (DISCOVERED / ACTIVE without blockers/commitments) → DIRECT_NEXT_ACTION (Milestone review)
    └── NO  ↓

Step 6: Fallback → NO_ACTION
```

---

## 4. Deterministic Tie-Breaking

When multiple candidates exist within a decision step, selection is strictly deterministic:

### A. Multiple Active Blockers (`UNBLOCKER_ACTION`)
1. **Commitment Overlap**: Blocker whose description shares keywords with any open commitment description (1 if related, 0 if not; descending).
2. **Evidence Support Count**: Number of supporting evidence items linked to the blocker (`len(b.supporting_evidence_ids)`; descending).
3. **Stable Identifier**: `blocker.dependency_id` (lexicographical ascending).
*(Note: Blocker due date is not used for blocker tie-breaking).*

### B. Multiple Waiting Dependencies (`FOLLOW_UP_ACTION`)
1. **Evidence Match Count**: Number of evidence items sharing keywords with the dependency description (descending).
2. **Stable Identifier**: `dependency.id` (lexicographical ascending).
*(Note: Dependency due date is not used for waiting dependency tie-breaking).*

### C. Multiple Open Commitments (`DIRECT_NEXT_ACTION`)
1. **Due Date**: Earliest `due_at` timestamp first (commitments without a due date are placed last).
2. **Stable Identifier**: `commitment.id` (lexicographical ascending).

---

## 5. Confidence Calculation

Recommendation confidence is strictly bounded in $[0.0, 1.0]$ and derived deterministically:

1. **For Actionable, Blocker, and Follow-up Recommendations** (`DIRECT_NEXT_ACTION`, `UNBLOCKER_ACTION`, `FOLLOW_UP_ACTION`):
   $$C_{action} = \min\left(1.0, 0.50 \times C_{thread} + 0.50 \times C_{analysis}\right)$$
   anchoring on both intrinsic thread confidence and structured evidence analysis.

2. **For Evidence Gathering** (`GATHER_EVIDENCE_ACTION`):
   $$C_{action} = \max\left(0.30, \min\left(0.60, C_{analysis}\right)\right)$$
   Exact behavior:
   - Analysis confidence below $0.30 \to 0.30$
   - Analysis confidence between $0.30$ and $0.60 \to$ unchanged ($C_{analysis}$)
   - Analysis confidence above $0.60 \to 0.60$

3. **For Terminal Threads** (`NO_ACTION`):
   $$C_{action} = 1.0$$
   indicating total certainty that a closed thread requires no further actions.

---

## 6. Preconditions & Confirmation Semantics

### `preconditions`
List of prerequisite conditions that must be fulfilled before the action can occur (e.g. `["Dependency 'Recommendation letter from Ahmed' must be resolved"]`). If no preconditions are known, returns `[]`.

### `requires_confirmation`
Flags whether the recommended action would eventually cause an external side effect if executed by an agent in future milestones:
- **`True`**: Actions involving external communication, messaging, calling, scheduling, booking, or paying (e.g. `"Call clinic to confirm Friday appointment time"`, contacting a person for a recommendation letter, or following up with a client).
- **`False`**: Internal planning, personal document drafting, evidence review, or completed threads.

---

## 7. MCP Tool Specification

Exposed at the canonical Streamable HTTP endpoint:

```text
POST http://localhost:8000/mcp
```

### Signature: `suggest_next_action`
- **Description**: Recommend the deterministic next action for an unfinished IntentThread. Planning only — does NOT execute actions.
- **Input**:
  ```json
  {
    "thread_id": "thread-university-application"
  }
  ```
- **Output Schema**:
  ```json
  {
    "suggestion": {
      "thread_id": "thread-university-application",
      "action_type": "UNBLOCKER_ACTION",
      "action": "Resolve blocker: Recommendation letter from Ahmed",
      "rationale": "Progress on 'University Application' is blocked by pending dependency 'Recommendation letter from Ahmed'. Addressing this blocker is required before the thread can proceed.",
      "confidence": 0.889,
      "supporting_evidence_ids": ["evi-uni-1"],
      "supporting_commitment_ids": ["com-uni-submit"],
      "supporting_dependency_ids": ["dep-uni-rec-letter"],
      "preconditions": ["Dependency 'Recommendation letter from Ahmed' must be resolved"],
      "requires_confirmation": true
    }
  }
  ```

---

## 8. Demo Walkthroughs

### Scenario 1: University Application (Blocked)
- **Status**: `BLOCKED`
- **Blocker**: `dep-uni-rec-letter`
- **Action Type**: `UNBLOCKER_ACTION`
- **Action**: `"Resolve blocker: Recommendation letter from Ahmed"`
- **Traceability**: Links to `dep-uni-rec-letter`, `evi-uni-1`, and `com-uni-submit`.

### Scenario 2: Client Report (Waiting)
- **Status**: `WAITING`
- **Dependency**: `dep-client-response`
- **Action Type**: `FOLLOW_UP_ACTION`
- **Action**: `"Follow up on pending dependency: Client response and data sign-off on Q3 deliverables"`
- **Traceability**: Links to `dep-client-response`.

### Scenario 3: AWS Hackathon (Actionable)
- **Status**: `ACTIVE`
- **Commitment**: `com-aws-m3`
- **Action Type**: `DIRECT_NEXT_ACTION`
- **Action**: `"Complete M3 domain layer and MCP tools implementation"`
- **Traceability**: Links to `com-aws-m3`, `evi-aws-1`, and `evi-aws-2`.

### Scenario 4: Dentist Appointment (Insufficient Evidence)
- **Status**: `ACTIVE`
- **Evidence Count**: 1 (< minimum required 2)
- **Action Type**: `GATHER_EVIDENCE_ACTION`
- **Action**: `"Gather additional context and documentation for 'Dentist Appointment'."`
- **Traceability**: Links to `evi-dentist-1`.

### Scenario 5: Tax Filing 2025 (Completed)
- **Status**: `COMPLETED`
- **Action Type**: `NO_ACTION`
- **Action**: `"No action required; thread 'Tax Filing 2025' is completed."`

---

## 9. Deterministic Guarantees & Known Limitations

- **Planning Only**: M5 recommends actions but does not execute them.
- **Traceability**: Every recommendation points to existing structured evidence, commitments, or dependencies.
- **No LLM Dependence**: All decisions are produced deterministically using domain rules and deterministic tie-breaking.
- **Reproducibility**: Calling `suggest_next_action` multiple times on identical input yields identical output.
