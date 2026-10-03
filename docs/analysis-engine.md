# Threadback — Intent & Evidence Engine (M4)

## Overview

The Intent & Evidence Engine provides a deterministic, pre-LLM reasoning layer for Threadback. It evaluates structured domain data (`IntentThread`, `Evidence`, `Commitment`, `Dependency`, and `Event`) and produces a structured, explainable analysis of what is happening, why it matters, what is blocking it, and the system's confidence in that assessment.

All calculations are fully deterministic: identical inputs always yield identical outputs without reliance on `datetime.now()`, external models, heuristics, or external services.

---

## 1. Analysis Pipeline

```text
IntentThread
    ↓
Evidence Aggregation
    ↓
Commitment Analysis
    ↓
Blocker Analysis
    ↓
Attention Calculation
    ↓
Confidence Calculation
    ↓
ThreadAnalysis
```

### Pipeline Stages

1. **Evidence Aggregation (`aggregate_evidence`)**:
   - Collects evidence items associated with the thread.
   - Computes counts by `EvidenceType` (`CONVERSATION`, `DOCUMENT`, `CALENDAR`, `NOTE`, `MESSAGE`, `USER_ACTION`).
   - Identifies the strongest evidence items (ranked by confidence descending, tie-broken by recency).
   - Computes weighted aggregate evidence confidence using recency decay.
   - Evaluates evidence staleness across individual items, set containment, and entire set staleness.
   - Evaluates evidence sufficiency.

2. **Commitment Analysis**:
   - Inspects `thread.commitments`.
   - Distinguishes active `OPEN` commitments from completed or cancelled commitments.

3. **Blocker Analysis**:
   - Evaluates `thread.dependencies`.
   - Identifies active blockers where `status == DependencyStatus.OPEN` and `blocking == True`.
   - Generates structured `BlockerDetail` entries with supporting evidence links.

4. **Unfinished Reason Classification (`classify_unfinished_reasons`)**:
   - Determines deterministic reasons why a thread remains incomplete based strictly on structured evidence and state relative to the analysis reference time.

5. **Attention Calculation (`compute_attention`)**:
   - Combines priority, blockers, open commitments, recency relative to the analysis reference time, and evidence signals using an explainable weighted linear sum.
   - Categorizes attention into `HIGH`, `MEDIUM`, or `LOW`.

6. **Confidence Calculation (`compute_overall_confidence`)**:
   - Combines the thread-level confidence (60%) with the aggregate evidence confidence (40%).
   - Classifies the final score into one of four M0-defined bands (`STRONG`, `GOOD`, `UNCERTAIN`, `WEAK`).

7. **Explanation Synthesis (`generate_explanation`)**:
   - Generates a human-readable, factual explanation derived solely from structured domain signals.

---

## 2. Deterministic Reference Time

To guarantee strict reproducibility across all environments and test runs:
- The engine defines an explicit analysis reference time:
  ```python
  DEFAULT_ANALYSIS_REFERENCE_TIME = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
  ```
- The deterministic calculation does **not** rely directly on `datetime.now()`.
- Functions accept an optional `reference_time: datetime | None = None` parameter which defaults to `DEFAULT_ANALYSIS_REFERENCE_TIME`.

---

## 3. Formulas & Thresholds

### A. Evidence Recency & Weighting

For each evidence item $i$ created at $t_i$, relative to analysis reference time $t_{ref}$:

$$\Delta \text{days}_i = \frac{t_{ref} - t_i}{86400}$$

$$\text{recency\_factor}_i = \max\left(0.0, 1.0 - \frac{\Delta \text{days}_i}{90.0}\right)$$

$$w_i = 0.5 + 0.5 \times \text{recency\_factor}_i$$

The aggregate evidence confidence is the weighted mean:

$$C_{evidence} = \frac{\sum_i c_i \cdot w_i}{\sum_i w_i}$$

If no evidence exists, $C_{evidence} = 0.0$.

### B. Evidence Staleness Semantics

The engine explicitly distinguishes between three levels of staleness:

1. **Age of Individual Evidence**:
   For an evidence item $e_i$, its age is $\Delta \text{days}_i = \frac{t_{ref} - t_i}{86400}$.
   An individual item is classified as stale if:
   $$\Delta \text{days}_i > 30.0\text{ days}$$
   All stale item IDs are recorded in `stale_evidence_ids`.

2. **Whether Evidence Set Contains Stale Evidence (`has_stale_evidence`)**:
   The evidence set contains stale evidence if at least one item is older than $30.0$ days:
   $$\text{has\_stale\_evidence} = (\exists i \text{ such that } \Delta \text{days}_i > 30.0) \iff \max_i(\Delta \text{days}_i) > 30.0\text{ days}$$
   If the evidence set is empty, `has_stale_evidence = False`.

3. **Whether Entire Evidence Set is Stale (`is_stale`)**:
   The entire evidence set is stale if *all* evidence items are older than $30.0$ days (or if the set is empty):
   $$\text{is\_stale} = (\forall i, \Delta \text{days}_i > 30.0) \iff \min_i(\Delta \text{days}_i) > 30.0\text{ days}$$
   If fresh evidence exists ($\le 30.0$ days old), `is_stale = False` even if older items are also present.

### C. Evidence Sufficiency

Evidence is classified as sufficient (`is_sufficient = True`) if:
- Total evidence count $\ge 2$ (`MIN_EVIDENCE_COUNT`) AND
- Simple average confidence $\ge 0.50$ (`MIN_AVERAGE_CONFIDENCE`).

### D. Overall Confidence Calculation

When evidence is present:

$$C_{overall} = 0.60 \times C_{thread} + 0.40 \times C_{evidence}$$

When no evidence is present:

$$C_{overall} = 0.50 \times C_{thread}$$

All confidence scores are clamped to $[0.0, 1.0]$.

### E. Confidence Bands (M0 Specification)

| Band | Range | Description |
|---|---|---|
| `STRONG` | $0.90 \le C \le 1.00$ | High certainty backed by strong, fresh evidence |
| `GOOD` | $0.75 \le C < 0.90$ | Clear signals with reliable supporting evidence |
| `UNCERTAIN` | $0.50 \le C < 0.75$ | Incomplete evidence or conflicting signals |
| `WEAK` | $0.00 \le C < 0.50$ | Missing evidence, stale data, or low initial confidence |

### F. Attention Signal Model

The attention score $P \in [0.0, 1.0]$ is computed as:

$$P = w_p \cdot S_p + w_b \cdot S_b + w_c \cdot S_c + w_r \cdot S_r + w_e \cdot S_e$$

Weights:
- $w_p = 0.30$ (Priority weight)
- $w_b = 0.25$ (Active blocker weight)
- $w_c = 0.20$ (Open commitment weight)
- $w_r = 0.15$ (Recency weight)
- $w_e = 0.10$ (Evidence strength weight)

Scores:
- **Priority Score ($S_p$)**: `HIGH` $\to 1.0$, `MEDIUM` $\to 0.5$, `LOW` $\to 0.2$.
- **Blocker Score ($S_b$)**: $1.0$ if $\ge 1$ active blockers exist; else $0.0$.
- **Commitment Score ($S_c$)**: $\min(1.0, n_{open} / \max(1, n_{total}))$.
- **Recency Score ($S_r$)**: $\max(0.0, 1.0 - \text{event\_age\_days} / 90.0)$ based on the most recent event relative to $t_{ref}$.
- **Evidence Score ($S_e$)**: The aggregate evidence confidence $C_{evidence}$.

#### Attention Levels
- **`HIGH`**: $P \ge 0.65$
- **`MEDIUM`**: $0.35 \le P < 0.65$
- **`LOW`**: $P < 0.35$

---

## 4. Unfinished Reason Classification & Domain Terminology

### Domain Lifecycle Status (M3)
In the M3 domain model, `ThreadStatus` has exactly 6 lifecycle states:
- `DISCOVERED`
- `ACTIVE`
- `BLOCKED`
- `WAITING`
- `COMPLETED`
- `ABANDONED`

> **Note on Terminology**: `WAITING` is the thread lifecycle status (`ThreadStatus.WAITING`). `WAITING_ON_DEPENDENCY` is an **unfinished-reason concept** (`UnfinishedReason.WAITING_ON_DEPENDENCY`), NOT a thread lifecycle status.

### Unfinished Reason Rules
A thread's `unfinished_reasons` list is derived deterministically from the following rules:

1. **`OPEN_COMMITMENT`**:
   - Present if there is at least one commitment with status `OPEN`.
2. **`ACTIVE_BLOCKER`**:
   - Present if there is at least one dependency with status `OPEN` and `blocking == True`.
3. **`WAITING_ON_DEPENDENCY`**:
   - Present if the thread's lifecycle status is `ThreadStatus.WAITING` and it has open dependencies (`status == DependencyStatus.OPEN`).
4. **`RECENT_ACTIVITY`**:
   - Present if the most recent event occurred $\le 7$ days before the explicit `reference_time` ($0.0 \le \Delta \text{days} \le 7.0$).
5. **`MISSING_REQUIRED_EVIDENCE`**:
   - Present if the thread has fewer than `MIN_EVIDENCE_COUNT` ($2$) evidence items.

---

## 5. MCP Tool: `analyze_thread`

Exposed at the canonical endpoint:

```text
POST http://localhost:8000/mcp
```

### Signature
- **Tool Name**: `analyze_thread`
- **Description**: Deterministically analyze an IntentThread and return structured reasoning, evidence aggregation, attention signal, and confidence assessment.
- **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "thread_id": {
        "type": "string",
        "description": "Unique identifier of the IntentThread to analyze"
      }
    },
    "required": ["thread_id"]
  }
  ```

### Tool Inventory (Exact 4 Tools in M4)
1. `discover_unfinished_threads`
2. `get_thread_context`
3. `find_thread_blockers`
4. `analyze_thread`
