# Threadback

> **People don't forget tasks. They forget intentions.**

[![Milestone](https://img.shields.io/badge/milestone-M15%20Frozen-7c6af7)](#)
[![Track](https://img.shields.io/badge/track-AWS%20Hackathon%20%7C%20Alexa%2B-a78bfa)](#)
[![Status](https://img.shields.io/badge/status-M0--M15%20Complete%20%26%20Frozen-10b981)](#)
[![Tests](https://img.shields.io/badge/tests-401%20passed-success)](#)
[![MCP](https://img.shields.io/badge/MCP%20Tools-9%20canonical-blue)](#)

---

## 1. Elevator Pitch

**Threadback** is an intent-recovery agent that reconstructs unfinished human commitments from conversational context and factual evidence, guides users through blockers, and safely verifies completion before closing open loops.

Built natively on the **Model Context Protocol (MCP)** (protocol `2025-11-25` over Streamable HTTP at `/mcp`), Threadback exposes **9 canonical domain tools** that empower AI assistants—such as **Amazon Alexa+** and **Amazon Bedrock** agents—to discover neglected intentions, calculate "Why Now" attention urgency, simulate counterfactual "What-If" decisions, and safely drive open loops to verified resolution without hallucinating state completion.

---

## 2. Built With

Threadback is built with a focused, production-grade local-first stack designed for full compliance with the hackathon's required track tools:

* **Model Context Protocol (MCP)**: Native integration using the official MCP Python SDK (`mcp`), serving exactly 9 canonical tools over **Streamable HTTP** at `/mcp` conforming to protocol specification version `2025-11-25`.
* **Amazon Bedrock & AWS Strands Agents (`strands-agents`)**: High-level agent orchestration combining `BedrockModel` (Claude 3.5 Sonnet) with `MCPClient`. Threadback includes a native Amazon Bedrock + Strands Agents provider architecture, with a deterministic local provider used for reliable offline evaluation.
* **Python 3.10+ & FastAPI**: Asynchronous ASGI backend hosting REST APIs, conversation state management, and Starlette-mounted Streamable HTTP MCP server adapters.
* **Persistent SQLite Intent Memory**: Write-Ahead Logging (WAL) SQLite repository persisting intent threads, commitments, dependencies, evidence, and audit ledgers across restarts.
* **React 19, TypeScript & Vite**: Evaluator web app featuring real-time MCP activity telemetry drawers, confirmation gates, an interactive 9-phase lifecycle timeline, and an **Intent Copilot** dashboard.
* **Amazon Bedrock AgentCore Packaging (Container & Manifest)**: ARM64 container specification (`Dockerfile.agentcore`), runtime configuration (`agentcore/runtime-config.json`), and automated ECR deployment script (`agentcore/deploy.sh`).
* **Amazon Alexa+ Add-on Manifest**: Add-on configuration (`alexa/skill.json`) and experience capability mapping (`alexa/capabilities.json`) targeting the Alexa+ conversational assistant paradigm.

---

## 3. The Problem

Traditional task managers, to-do lists, and voice reminders fail at human follow-through because they treat commitments as flat, static checklists. When life intervenes, a checkbox cannot capture *why* an effort stalled, *where* the human left off, or *what external party* is blocking progress. 

When a user intends to submit a university application, the obstacle is rarely forgetting the deadline; it is that a professor has not yet submitted a required recommendation letter. Sending a generic reminder every morning does not unblock the work—it produces notification fatigue. When commitments fall behind, humans abandon their lists because they lose the surrounding intent, context, blockers, evidence, and unfinished state.

---

## 4. Core Lifecycle

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

## 5. What Threadback Does

### Core Lifecycle Capabilities (M0–M12)

1. **Discovers Unfinished Intentions**: Finds open loops across persistent memory (`discover_unfinished_threads`).
2. **Reconstructs Context**: Answers *"Where did I leave off?"* by reviewing commitments, deadlines, and recent evidence (`get_thread_context`).
3. **Identifies Root Blockers**: Uncovers why progress stalled, pinpointing external dependencies (`find_thread_blockers`).
4. **Evaluates Intent Health**: Assesses attention levels, confidence scores, and unfinished reasons (`analyze_thread`).
5. **Recommends Next Actions**: Evaluates prioritized unblocking actions using deterministic precedence rules (`suggest_next_action`).
6. **Prepares Structured Actions**: Packages recommended actions into auditable `ActionProposal` objects with explicit risk levels (`prepare_action`).
7. **Enforces Explicit Confirmation**: Demands clear human authorization before executing actions; rejects ambiguous replies (*"maybe"*, *"sounds good"*).
8. **Controlled Simulated Execution**: Executes operational proposals in `SIMULATED` mode; dispatches internal Threadback state mutations (`PERSISTENT_MUTATION`) without external side effects (`execute_action`).
9. **Deterministic Verification & Safe Closure**: Evaluates factual evidence against Rules A–E (`verify_thread_completion`) and closes only verified threads (`close_thread`).

### Advanced Intent Intelligence & Copilot (M13–M15)

* **M13 — Persistent Intent Memory**: Tracks original goal vs. evolving current goal, records an auditable `IntentEvolution` log, runs scheduled intent radar scans, deterministically scores inactivity decay and deadline urgency, and supports explicit `DEFERRED`, `WAITING`, and `ABANDONED` lifecycle transitions.
* **M14 — Proactive Intent Intelligence**: Features an Attention Radar that strictly separates impending deadline **Urgency** from high-need **Attention**, provides explainable **Why Now** deterministic reasoning, computes multi-horizon state change diffs, detects conservative cross-thread conflicts (time collisions, exclusive resource contention, deadline impossibilities, and goal exclusions), and automatically identifies unblocked **Resumable Candidates**.
* **M15 — Intent Copilot**: Provides conversational decision support—enabling users to ask *"What should I do first?"*, *"What if I postpone this?"*, *"I have 30 minutes. What can I finish?"*, or *"Can I close anything?"*. Executes counterfactual **What-If Simulations** (strictly labeled `SIMULATION — NO STATE CHANGED` with zero database mutation), reconstructs resume context, assists with safe verification-gated closure, and presents structured **Intent Decision Cards**.

---

## 6. Key Innovation

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

## 7. Architecture

Threadback uses a modular, layered architecture enforcing strict domain encapsulation:

```text
Evaluator / Web UI (React 19 + TypeScript + Vite)
      ↓ HTTP / JSON
FastAPI Agent Orchestrator (/api/agent/chat, /demo-reset)
      ↓ MCP Client (Streamable HTTP)
Threadback MCP Server (/mcp) — Exactly 9 Canonical Tools (Protocol 2025-11-25)
      ↓ Direct Invocations
Application & Domain Services (Analysis, NextAction, Prep, Execution, Verification, Lifecycle, Copilot)
      ↓ Aggregate Repository Pattern
SQLite Persistence Repository (Persistent Intent Memory, WAL Mode, Threadback.db)
```

**Persistence Boundary**: The Agent and Model Provider layers act purely as orchestrators. They **never** write directly to SQLite or bypass domain services. All persistent mutations flow through authoritative domain and lifecycle services.

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
| 7 | `execute_action` | Execution | Controlled | Executes operational proposals in `SIMULATED` mode; dispatches internal Threadback state mutations (`PERSISTENT_MUTATION`). |
| 8 | `verify_thread_completion` | Verification | Verification | Evaluates Rules A–E against evidence to verify completion. |
| 9 | `close_thread` | Closure | Protected | Closes thread and transitions to `COMPLETED` after verified proof. |

---

## 8. Track Tool & Cloud Positioning

To maintain complete evaluator clarity, Threadback explicitly documents what is implemented versus what is future work:

| Component | Status | Reality |
| :--- | :--- | :--- |
| **Model Context Protocol (MCP)** | **Implemented & Verified** | Native `/mcp` server running over Streamable HTTP with `2025-11-25` protocol negotiation and exactly 9 canonical tools. |
| **Amazon Bedrock + Strands Agents** | **Integration-Ready** | Native provider architecture using `strands-agents` and Amazon Bedrock Claude 3.5 Sonnet, paired with a deterministic local mock provider for reliable offline evaluation. |
| **Amazon Bedrock AgentCore Runtime** | **Integration-Ready (Cloud Provisioning Blocked by Sandbox IAM)** | Containerized ARM64 packaging (`Dockerfile.agentcore`), runtime configuration (`agentcore/runtime-config.json`), and deploy script (`agentcore/deploy.sh`) implemented; live cloud deployment was frozen due to hackathon AWS sandbox IAM `ViewOnlyAccess`. |
| **Amazon Alexa+ Add-on & Manifest** | **Integration-Ready (Pending Partner Access)** | Configured Add-on manifest (`alexa/skill.json`) and conversational capability mapping (`alexa/capabilities.json`); live onboarding pending Amazon preview partner toolkit access. |
| **External Action Execution** | **Simulated by Design** | High-stakes safety model: operational external actions (emails, SMS, portal submissions) are simulated and audit-logged, preventing real-world side effects. |

> **Boundary Notice:** Threadback does **not** claim an active production connection to live Alexa+ infrastructure or an active cloud AgentCore deployment. It implements and demonstrates the complete Alexa+-style conversational experience, local Bedrock/Strands provider architecture, and MCP protocol compliance locally.

---

## 9. Local Setup & Execution

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

## 10. Canonical Demo & Intent Copilot Walkthrough

For the complete evaluator walkthrough script with exact observation checkpoints, see [docs/demo-script.md](docs/demo-script.md).

```text
Phase 1: Discover      ──> User: "What am I forgetting?"
Phase 2: Reconstruct   ──> User: "Where did I leave off?"
Phase 3: Understand    ──> User: "Why haven't I finished it?"
Phase 4: Decide        ──> User: "What should I do?"
Phase 5: What-If       ──> User: "What if I postpone it?" (SIMULATION — NO STATE CHANGED)
Phase 6: Time Budget   ──> User: "I have 30 minutes. What can I realistically finish?"
Phase 7: Prepare       ──> User: "Help me finish it." (Safety Pause)
Phase 8: Confirm       ──> User: "Yes, go ahead." (SIMULATED ACTION ≠ COMPLETION)
Phase 9: Evidence      ──> External recommendation letter evidence arrives in memory
Phase 10: Verify       ──> User: "Is it actually finished?" (Deterministic verification)
Phase 11: Close        ──> User: "Close it." (VERIFIED → CLOSED → COMPLETED)
```

---

## 11. Safety Model & Invariants

Threadback enforces three core safety pillars:

1. **Simulated External Action**: Operational actions never dispatch real emails, SMS, phone calls, or payments. All external action execution is strictly `SIMULATED` and recorded in an auditable ledger.
2. **Persistent Internal Mutation**: Internal Threadback state mutations (such as goal revisions, deferrals, and event logs) persist durably to SQLite via domain services only after explicit user confirmation.
3. **Verified Completion (`EXECUTION_SUCCESS ≠ COMPLETION`)**: An agent cannot declare an intention complete based on conversational sentiment or execution success. Completion requires deterministic verification proof satisfying Rules A through E before transitioning to `COMPLETED`.
4. **Strict Confirmation Boundary**: Any prepared action with `requires_confirmation = True` pauses execution. The agent never infers authorization from ambiguous statements (*"maybe"*, *"what happens next?"*, *"sounds good"*).
5. **Protected Closure**: A thread can only transition to `COMPLETED` if a preceding deterministic verification succeeded. Bypassing verification is architecturally prohibited.

---

## 12. Known Limitations

* **Simulated External Execution**: All operational actions are simulated; no real-world external side effects occur.
* **Local SQLite Persistence**: Persistence uses a local SQLite database (WAL mode); distributed cloud storage (e.g., DynamoDB) is future work.
* **AgentCore Cloud Deployment**: Cloud deployment to Bedrock AgentCore is frozen/conditional due to sandbox IAM permissions (`ViewOnlyAccess`).
* **Single-User Scope**: Evaluator demo runs in a single-user personal context; multi-tenant authentication is future work.

---

## 13. Quality Gate & Verification

The repository passes a complete automated test and quality gate:

```bash
# Run complete backend test suite (401 tests)
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

* **Pytest**: **401 passed** in ~26s across M0–M15 (0 failures, 0 errors).
* **Ruff Lint**: 0 errors across all 87 backend source and test files.
* **Ruff Format**: 0 formatting deviations (all 87 files verified).
* **Frontend Lint (oxlint)**: 0 errors, 0 warnings.
* **Frontend Build**: Vite production bundle compiled cleanly with 0 TypeScript errors.

---

## 14. Documentation Sitemap

* **Evaluator Walkthrough**: [docs/evaluator-guide.md](docs/evaluator-guide.md)
* **Devpost Submission Copy**: [docs/devpost-content.md](docs/devpost-content.md)
* **Submission Materials**: [docs/hackathon-submission.md](docs/hackathon-submission.md)
* **Live Demo Script**: [docs/demo-script.md](docs/demo-script.md)
* **Submission Checklist**: [docs/final-submission-checklist.md](docs/final-submission-checklist.md)
* **M15 Intent Copilot & Experience**: [docs/action-execution.md](docs/action-execution.md)
* **M13 Persistent Intent Memory**: [docs/m13-persistent-intent-intelligence.md](docs/m13-persistent-intent-intelligence.md)
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

---

## 15. License

This project is licensed under the [MIT License](LICENSE).

