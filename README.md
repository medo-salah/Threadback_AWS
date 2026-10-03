# Threadback

> **People don't forget tasks. They forget intentions.**

[![Milestone](https://img.shields.io/badge/milestone-M12%20Submission%20Ready-7c6af7)](#)
[![Track](https://img.shields.io/badge/track-AWS%20Hackathon%20%7C%20Alexa%2B-a78bfa)](#)
[![Status](https://img.shields.io/badge/status-M0--M12%20Complete-10b981)](#)
[![Tests](https://img.shields.io/badge/tests-286%20passed-success)](#)
[![MCP](https://img.shields.io/badge/MCP%20Tools-9%20canonical-blue)](#)

---

## 1. Elevator Pitch

**Threadback** is an intent-recovery agent that reconstructs unfinished human commitments from conversational context and factual evidence, guides users through blockers, and safely verifies completion before closing open loops.

---

## 2. The Problem

Traditional task managers, to-do lists, and voice reminders fail at human follow-through because they treat commitments as flat, static checklists. When life intervenes, a checkbox cannot capture *why* an effort stalled, *where* the human left off, or *what external party* is blocking progress. 

When a user intends to submit a university application, the obstacle is rarely forgetting the deadline; it is that a professor has not yet submitted a required recommendation letter. Sending a generic reminder every morning does not unblock the work—it produces notification fatigue. When commitments fall behind, humans abandon their lists because they lose the surrounding intent, context, blockers, evidence, and unfinished state.

---

## 3. Core Lifecycle

Threadback models human commitments as a continuous, structured 9-stage lifecycle:

```text
Conversation
    ↓
Intent
    ↓
Commitment
    ↓
Dependency
    ↓
Unfinished State
    ↓
Next Action
    ↓
Evidence
    ↓
Verification
    ↓
Closure
```

---

## 4. What Threadback Does

Threadback implements nine core capabilities across the lifecycle:

1. **Discovers Unfinished Intentions**: Discovers unfinished intent threads from persisted structured evidence and state to identify neglected commitments requiring attention.
2. **Reconstructs Context**: Explains where the user left off, what commitments were made, and what factual evidence has been recorded.
3. **Identifies Root Blockers**: Detects whether an intention is stalled waiting on external dependencies or missing requirements.
4. **Recommends Next Actions**: Evaluates prioritized unblocking actions using deterministic precedence rules.
5. **Prepares Structured Actions**: Packages recommended actions into auditable `ActionProposal` objects with explicit risk levels.
6. **Requires Explicit Human Confirmation**: Enforces strict confirmation checks; ambiguous replies (*"maybe"*, *"sounds good"*) are rejected as authorization.
7. **Executes Controlled Simulated Actions**: Executes approved actions strictly in `SIMULATED` mode and appends them to the persistent audit log.
8. **Verifies Completion Deterministically**: Evaluates independent factual evidence against deterministic domain rules (Rules A through E).
9. **Safely Closes Verified Threads**: Transitions intentions to `COMPLETED` only when verified evidence exists, closing open loops.

---

## 5. Key Innovation

> **Threadback does not merely remind users about tasks.**  
> **It reconstructs unfinished intentions from evidence and context.**

Instead of granting generative AI unchecked authority over user state, Threadback establishes a strict division of responsibility:

* **The Agent Layer** is responsible for conversational understanding, natural dialogue, pronoun resolution, and tool orchestration.
* **The Deterministic Backend** is the authoritative source of truth for:
  * evidence records
  * blocker detection
  * next-action scoring and tie-breaking
  * action proposal preparation
  * execution state and audit logging
  * evidence-based verification
  * lifecycle state transitions and closure

### The Central Safety Invariant

```text
EXECUTION_SUCCESS ≠ COMPLETION
```

Executing an action (such as drafting or simulating a follow-up inquiry) does **not** complete an intention. Completion requires independent, verified evidence.

---

## 6. Architecture

Threadback uses a modular, layered architecture:

```text
Evaluator / Web UI (React + TypeScript + Vite)
      ↓ HTTP / JSON
FastAPI Agent Orchestrator (/api/agent/chat, /demo-reset)
      ↓ MCP Client (Streamable HTTP)
Threadback MCP Server (/mcp) — 9 Canonical Tools
      ↓ Direct Invocations
Deterministic Domain Services (Analysis, NextAction, Prep, Execution, Verification, Lifecycle)
      ↓ Aggregate Repository Pattern
SQLite Persistence Repository (Persistent Intent Memory, WAL Mode)
```

### The 9 Canonical MCP Tools

Threadback exposes exactly nine canonical tools conforming to the Model Context Protocol (MCP protocol `2025-11-25` over Streamable HTTP for Alexa+ parity):

| # | MCP Tool Name | Phase | Modality | Description |
|---|---|---|---|---|
| 1 | `discover_unfinished_threads` | Discovery | Read-Only | Finds active, blocked, or waiting open intent threads. |
| 2 | `get_thread_context` | Reconstruction | Read-Only | Retrieves commitments, evidence, and dependencies. |
| 3 | `find_thread_blockers` | Investigation | Read-Only | Identifies active blocking dependencies. |
| 4 | `analyze_thread` | Evaluation | Read-Only | Evaluates attention levels, confidence scores, and unfinished reasons. |
| 5 | `suggest_next_action` | Next Action | Read-Only | Computes deterministic next-action recommendation. |
| 6 | `prepare_action` | Preparation | State Mutation | Generates reviewable `ActionProposal` with confirmation requirement. |
| 7 | `execute_action` | Simulation | Controlled | Executes approved proposals strictly in `SIMULATED` mode. |
| 8 | `verify_thread_completion` | Verification | Verification | Evaluates Rules A–E against evidence to verify completion. |
| 9 | `close_thread` | Closure | Protected | Closes thread and transitions to `COMPLETED` after verified proof. |

---

## 7. Alexa+ / AWS Positioning

To maintain complete evaluator clarity, Threadback explicitly documents what is implemented versus what is future work:

| Component | Status | Reality |
| :--- | :--- | :--- |
| **Alexa+-Style Conversational Agent** | **Verified / Implemented** | Full spoken-dialogue experience with conversational continuity, pronoun resolution, and natural summaries. |
| **MCP Streamable HTTP Endpoint** | **Verified / Implemented** | Native `/mcp` endpoint running over Streamable HTTP with `2025-11-25` protocol negotiation. |
| **Amazon Bedrock AgentCore Runtime** | **Conditional / Frozen (M9)** | Containerized Docker packaging (`Dockerfile.agentcore`), deploy script, and JWT auth implemented; cloud deployment frozen due to hackathon AWS sandbox IAM `ViewOnlyAccess`. |
| **Official Alexa+ Partner Onboarding** | **Pending / Unverified** | Architected for official Alexa+ add-on manifest (`alexa/skill.json`), but official partner onboarding was unavailable during the hackathon. |

> **Boundary Notice:** Threadback does **not** claim an active production connection to live Alexa+ infrastructure. It implements and demonstrates the complete Alexa+-style conversational experience and MCP protocol compliance locally.

---

## 8. Local Setup & Execution

### Prerequisites

* **Python 3.10+**
* **Node.js 18+** & **npm**

### Terminal 1: Backend Server

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies in editable mode with development tools
pip install -e ".[dev]"

# Start backend server with hot-reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

* Backend URL: `http://localhost:8000`
* Agent Chat API: `http://localhost:8000/api/agent/chat`
* MCP Server: `http://localhost:8000/mcp`
* Interactive API Docs: `http://localhost:8000/docs`

*(Alternatively, run `./scripts/dev-backend.sh` from the repository root).*

### Terminal 2: Frontend Web App

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

* Frontend URL: `http://localhost:5173`

*(Alternatively, run `./scripts/dev-frontend.sh` from the repository root).*

### Deterministic Demo Reset

To return the entire system to its canonical starting state at any time:
* Click the **`Reset Demo`** button in the top navigation bar of the Web UI, or
* Send `POST /api/agent/demo-reset`:
  ```bash
  curl -X POST http://localhost:8000/api/agent/demo-reset \
       -H "Content-Type: application/json" \
       -d '{"conversation_id": "session-default"}'
  ```

---

## 9. Canonical Demo (9-Phase Flow)

For the complete evaluator walkthrough script with exact observation checkpoints, see [docs/demo-script.md](docs/demo-script.md).

```text
Phase 1: Discover      ──> User: "What am I forgetting?"
Phase 2: Reconstruct   ──> User: "Where did I leave off?"
Phase 3: Understand    ──> User: "Why haven't I finished it?"
Phase 4: Decide        ──> User: "What should I do?"
Phase 5: Prepare       ──> User: "Help me finish it." (Safety Pause)
Phase 6: Confirm       ──> User: "Yes, go ahead." (SIMULATED ACTION ≠ COMPLETION)
Phase 7: Evidence      ──> External recommendation letter evidence arrives in memory
Phase 8: Verify        ──> User: "Is it actually finished?" (Deterministic verification)
Phase 9: Close         ──> User: "Close it." (VERIFIED → CLOSED → COMPLETED)
```

---

## 10. Safety Model & Invariants

1. **Strict Confirmation Boundary**: Any prepared action with `requires_confirmation = True` pauses execution. The agent never infers confirmation from ambiguous statements (*"maybe"*, *"what happens next?"*, *"sounds good"*).
2. **Explicit Authorization**: Only explicit affirmative replies (*"Yes"*, *"Go ahead"*, *"Proceed"*, *"Execute it"*) authorize execution.
3. **Simulation Boundary**: Threadback never dispatches real emails, SMS, phone calls, or payments. All action execution is strictly `SIMULATED` and auditable.
4. **Deterministic Verification Required**: The agent cannot declare a thread complete based on conversational sentiment. Completion requires structured factual evidence satisfying Rules A through E.
5. **Protected Closure**: A thread can only transition to `COMPLETED` if a preceding deterministic verification succeeded. Bypassing verification is architecturally prohibited.

---

## 11. Known Limitations

* **Simulated Execution**: All execution is simulated; no real-world external side effects occur.
* **Local SQLite Persistence**: Persistence uses a local SQLite database (WAL mode); distributed cloud storage (e.g., DynamoDB) is future work.
* **AgentCore Deployment**: Cloud deployment to Bedrock AgentCore is frozen/conditional due to IAM permissions (`ViewOnlyAccess`).
* **Single-User Scope**: Evaluator demo runs in a single-user personal context; multi-tenant authentication is not implemented.

---

## 12. Quality Gate & Verification

The repository passes a complete automated test and quality gate:

```bash
# Run complete backend test suite (286 tests)
cd backend
source .venv/bin/activate
pytest tests/ -v

# Run backend lint and formatting checks
ruff check app tests
ruff format --check app tests

# Run frontend lint and production build
cd ../frontend
npm run lint
npm run build
```

### Verified Results

* **Pytest**: 286 passed in ~14s (0 failures, 0 errors).
* **Ruff Lint**: 0 errors across all 67 backend source and test files.
* **Ruff Format**: 0 formatting deviations.
* **Frontend Lint (oxlint)**: 0 errors, 0 warnings.
* **Frontend Build**: Vite production bundle compiled cleanly with 0 TypeScript errors.

---

## 13. Documentation Sitemap

* **Evaluator Walkthrough**: [docs/evaluator-guide.md](docs/evaluator-guide.md)
* **Devpost Submission Copy**: [docs/devpost-content.md](docs/devpost-content.md)
* **Submission Materials**: [docs/hackathon-submission.md](docs/hackathon-submission.md)
* **Live Demo Script**: [docs/demo-script.md](docs/demo-script.md)
* **Submission Checklist**: [docs/final-submission-checklist.md](docs/final-submission-checklist.md)
* **M12 Hackathon Readiness**: [docs/m12-hackathon-readiness.md](docs/m12-hackathon-readiness.md)
* **M11 Alexa+ Experience**: [docs/m11-alexa-experience.md](docs/m11-alexa-experience.md)
* **M10 Intent Memory & Closure**: [docs/m10-intent-memory-closure.md](docs/m10-intent-memory-closure.md)
* **M9 Final Technical Audit**: [docs/m9-final-report.md](docs/m9-final-report.md)
* **Architecture Design**: [docs/architecture.md](docs/architecture.md)
* **Deterministic Analysis Engine**: [docs/analysis-engine.md](docs/analysis-engine.md)
* **Next Action Engine**: [docs/next-action-engine.md](docs/next-action-engine.md)
* **Action Preparation Policy**: [docs/action-preparation.md](docs/action-preparation.md)
* **Action Execution Policy**: [docs/action-execution.md](docs/action-execution.md)
* **Agent Orchestration**: [docs/agent-orchestration.md](docs/agent-orchestration.md)
