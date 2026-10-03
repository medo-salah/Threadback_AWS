# Threadback — Devpost Submission Content

## Project Name
**Threadback**

---

## Elevator Pitch
**People don't forget tasks. They forget intentions.**  
Threadback is an intent-recovery agent that reconstructs unfinished human commitments from conversational context and factual evidence, guides users through blockers, and safely verifies completion before closing open loops.

---

## About the Project

### The Problem
Traditional productivity tools and digital voice assistants represent commitments as flat, static checklists. When commitments stall, these tools lack the context to understand *why* the loop remains open or *where* the human left off. Reminding a user every morning to "Submit university application" does not help when the true obstacle is an unsubmitted recommendation letter from a professor. Users eventually abandon task managers due to notification fatigue and lost context.

### The Core Insight
Humans do not forget tasks—they forget **intentions**. Intentions are fluid, complex commitments that evolve through conversation, encounter external blockers, and require factual proof to resolve.

### The Solution: An Intent Recovery Agent
Threadback models human commitments through a structured, 9-stage lifecycle:

```text
Conversation → Intent → Commitment → Dependency → Unfinished State → Next Action → Evidence → Verification → Closure
```

Threadback combines a natural-language conversational agent with a deterministic domain engine:
1. **Discovers Unfinished Intentions**: Finds open loops across persistent memory.
2. **Reconstructs Context**: Answers *"Where did I leave off?"* by reviewing commitments, deadlines, and recent evidence.
3. **Identifies Root Blockers**: Uncovers why progress stalled (e.g., missing recommendation letters).
4. **Recommends & Prepares Next Actions**: Deterministically scores and prepares structured `ActionProposal` objects.
5. **Enforces Explicit Confirmation**: Demands clear human authorization before simulating actions.
6. **Controlled Simulated Execution**: Safely simulates follow-up actions and records audit events without external side effects.
7. **Deterministic Verification**: Evaluates independent factual evidence against strict domain rules.
8. **Safe Lifecycle Closure**: Transitions verified intentions to `COMPLETED`.

### The Core Invariant
Threadback enforces the invariant: **`EXECUTION_SUCCESS ≠ COMPLETION`**. Simulating an action (e.g., drafting a follow-up message) does not mark an intention complete. Completion requires verifiable factual evidence (e.g., admissions portal confirmation).

---

## How It Was Built

Threadback was engineered as a modular, local-first system:

* **Backend & API**: Python 3.10+ with **FastAPI** powering the REST and agent orchestrator endpoints.
* **Model Context Protocol (MCP)**: Native integration using the official MCP Python SDK (`mcp`). Exposes **9 canonical domain tools** over **Streamable HTTP** at `/mcp`, implementing MCP protocol `2025-11-25` for Alexa+ parity.
* **Deterministic Core Engines**:
  * *Analysis Engine*: Evaluates attention levels, confidence scores, and unfinished reasons.
  * *Next Action Engine*: Computes prioritized recommendations with deterministic tie-breaking.
  * *Action Preparation Service*: Generates structured `ActionProposal` objects with safety preconditions.
  * *Execution Service*: Enforces confirmation validation and records simulated events in the audit log.
  * *Verification Service*: Enforces Rules A through E to deterministically prove completion.
  * *Lifecycle Closure Service*: Enforces 7 closure rules before permitting transition to `COMPLETED`.
* **Persistent Intent Memory**: **SQLite** database using WAL (Write-Ahead Logging) mode, foreign key constraints, and aggregate repository abstractions.
* **Conversational Agent Orchestrator**: Multi-turn dialogue manager supporting pronoun resolution (`"it"`, `"where was I"`) and confirmation safety. Supports both deterministic mock execution and Amazon Bedrock integration via **Strands Agents**.
* **Frontend Web App**: **React 19 + TypeScript + Vite**, featuring ambient styling, real-time MCP tool activity telemetry, confirmation cards, and an interactive lifecycle timeline.

---

## Challenges We Overcame

1. **Separating Intelligence from State Authority**: Ensuring the generative agent understands natural language while preventing it from hallucinating state changes or fabricating task completion. We solved this by making the deterministic domain engine the sole authoritative source of truth.
2. **Strict Confirmation Safety**: Distinguishing genuine affirmative commands (`"Yes"`, `"Go ahead"`) from inquisitive or ambiguous statements (`"maybe"`, `"what would that do?"`). We built a dedicated confirmation safety analyzer that rejects non-explicit authorizations.
3. **Enforcing `EXECUTION_SUCCESS ≠ COMPLETION`**: Ensuring that executing an action (simulated follow-up) leaves the intention open until independent evidence proves fulfillment.
4. **Repeatable Lifecycle Closure**: Enforcing that a thread cannot be closed without a prior successful verification record, eliminating state bypasses.
5. **MCP Protocol Compliance**: Implementing the MCP Streamable HTTP transport and protocol negotiation for Alexa+ compatibility.
6. **Cloud Access Boundaries**: When AWS sandbox credentials had `ViewOnlyAccess` (preventing live Bedrock AgentCore resource creation), we maintained architectural integrity by preserving AgentCore packaging (`Dockerfile.agentcore`, deploy script) while validating full functionality locally.

---

## What We Accomplished

* **286 automated tests** with 100% pass rate covering all domain engines, persistence, and conversational flows.
* **9 canonical MCP tools** operating cleanly over Streamable HTTP.
* Complete **9-phase canonical University Application demo** that is 100% deterministic and repeatable.
* **Persistent SQLite Intent Memory** that preserves threads, evidence, proposals, and verification records across restarts.
* Single-click **Deterministic Demo Reset** allowing seamless evaluator retesting.
* Evaluator-ready web frontend with zero lint errors and clean build.

---

## What's Next (Future Work)

* **Verified Remote AgentCore Deployment**: Deploying the containerized MCP service to live Amazon Bedrock AgentCore Runtime when IAM permissions allow.
* **Official Alexa+ Partner Onboarding**: Completing official developer onboarding and certification for Alexa+ add-on manifest integration.
* **Real-World Integrations**: Moving beyond simulated execution to controlled, user-authorized integrations with real communication and calendar APIs.
* **Cloud Persistence**: Migrating local SQLite to distributed cloud storage (e.g., Amazon DynamoDB or Aurora) for multi-device synchronization.
