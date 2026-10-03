# Threadback — Hackathon Submission (Devpost)

## Project Name
**Threadback**

---

## Elevator Pitch

**People don't forget tasks. They forget intentions.**  
Threadback is an intent-recovery agent that reconstructs unfinished human commitments from conversational context and factual evidence, guides users through blockers, and safely verifies completion before closing open loops.

---

## About the Project

### The Problem
Modern task managers, calendars, and digital voice assistants fail at human follow-through because they treat commitments as flat, static checkboxes. In reality, human work consists of complex, evolving intentions with dependencies, blockers, and external stakeholders.

When a user intends to submit a graduate school application, the obstacle is rarely forgetting the deadline; it is that Professor Smith has not yet submitted his recommendation letter. Reminding the user every morning at 9:00 AM does not unblock the intention—it produces notification fatigue. When intentions fall behind, humans abandon their lists because traditional tools lose the surrounding context, blockers, evidence, and unfinished state.

### The Core Insight
Humans do not need another list of tasks to ignore. They need an agent that understands the **context of why an intention is open**, where they left off, what specifically is blocking progress, what action would move it forward, and whether the intention has actually been fulfilled.

### What Threadback Does
Threadback transforms open loops into a structured, deterministic 9-stage lifecycle:

```text
Conversation → Intent → Commitment → Dependency → Unfinished State → Next Action → Evidence → Verification → Closure
```

1. **Discovers Unfinished Intentions**: Discovers unfinished intent threads from persisted structured evidence and state to identify neglected commitments requiring attention.
2. **Reconstructs Context**: Explains where the user left off, what commitments were made, and what factual evidence has been recorded.
3. **Identifies Root Blockers**: Uncovers whether an intention is stalled by waiting on external parties or missing requirements.
4. **Recommends Next Actions**: Evaluates prioritized unblocking actions using deterministic precedence rules.
5. **Prepares Structured Actions**: Packages recommended actions into auditable `ActionProposal` objects with explicit risk levels.
6. **Requires Explicit Confirmation**: Enforces strict confirmation checks; ambiguous replies (*"maybe"*, *"sounds good"*) are rejected as authorization.
7. **Executes Controlled Simulated Actions**: Executes approved actions strictly in `SIMULATED` mode and appends them to the persistent audit log.
8. **Deterministically Verifies Completion**: Evaluates independent factual evidence against domain rules rather than relying on LLM sentiment.
9. **Safely Closes Open Loops**: Transitions the intention to completed status only when verified evidence exists.

### Why Conversation Is Central
Intentions live in dialogue. Users think and speak in natural phrases: *"Where did I leave off?"*, *"Why haven't I finished it?"*, or *"Help me finish it."* Threadback provides an Alexa+-style conversational layer that resolves pronouns and relative references (`"it"`, `"that"`, `"the application"`, `"where was I"`) while delegating all decisions to authoritative, deterministic domain engines.

### The IntentThread Concept
At the heart of Threadback is the `IntentThread` domain model. An `IntentThread` groups:
* **Commitments**: Obligations with due dates and statuses.
* **Dependencies**: External prerequisites that may be actively blocking progress.
* **Evidence**: Factual records (documents, messages, portal confirmations) supporting the thread.
* **Action Proposals**: Structured steps prepared to resolve dependencies.
* **Audit Events**: Chronological lifecycle history of all system decisions and user actions.

---

## Key Innovation

> **Threadback does not merely remind users about tasks.**  
> **It reconstructs unfinished intentions from evidence and context.**

Instead of leaving state authority to a generative model, Threadback pairs natural-language conversational interaction with a **deterministic backend engine**. The AI agent is responsible for understanding human intent and picking tools, but the domain state, blocker calculation, next-action scoring, verification rules, and lifecycle transitions are 100% deterministic, auditable, and repeatable.

### The Invariant: `EXECUTION_SUCCESS ≠ COMPLETION`
In typical AI agents, executing a command (e.g. "Send email to professor") causes the agent to mark the task completed. In Threadback, simulating an action only logs an event. The intention remains `BLOCKED` until independent, verifiable evidence (e.g. portal submission confirmation) is received and deterministically validated.

---

## Implementation Status & Verification Boundary

To ensure complete evaluator transparency, Threadback strictly delineates between implemented/verified capabilities and future cloud deployment:

| Layer / Capability | Status | Implementation Reality |
| :--- | :--- | :--- |
| **Deterministic Intelligence Engine** | **Implemented & Verified** | Full rule-based analysis, next-action scoring, proposal preparation, and verification (Rules A–E). |
| **Persistent Intent Memory (SQLite)** | **Implemented & Verified** | WAL-mode SQLite database preserving threads, evidence, proposals, and events across restarts. |
| **9 Canonical MCP Tools** | **Implemented & Verified** | Model Context Protocol over Streamable HTTP at `/mcp` (MCP protocol `2025-11-25` for Alexa+ parity). |
| **Alexa+-Style Conversational Agent** | **Implemented & Verified** | Natural voice-ready dialogue, pronoun continuity, explicit confirmation gate, and structured tool orchestration. |
| **Web Evaluator UI** | **Implemented & Verified** | React 19 + TypeScript + Vite app with real-time MCP activity tracking and 1-click deterministic demo reset. |
| **Amazon Bedrock AgentCore Deployment** | **Conditional / Frozen (M9)** | Containerized Docker packaging (`Dockerfile.agentcore`), deploy script, and JWT auth implemented; live AWS cloud deployment frozen due to hackathon AWS sandbox IAM `ViewOnlyAccess`. |
| **Official Alexa+ Partner Integration** | **Pending / Unverified** | Add-on manifest configured (`alexa/skill.json`), but official partner onboarding was unavailable during the hackathon. |

---

## Technical Stack

* **Backend Framework**: Python 3.10+ with **FastAPI** for HTTP endpoints and background task management.
* **Model Context Protocol (MCP)**: Native integration using the official MCP Python SDK (`mcp`). Exposes **9 canonical tools** over **Streamable HTTP** at `/mcp`.
* **Domain Engine**:
  * *Analysis Engine*: Evaluates unfinished reasons, attention urgency, and confidence scores.
  * *Next Action Engine*: Computes prioritized recommendations with deterministic tie-breaking.
  * *Action Preparation Service*: Constructs structured `ActionProposal` objects with safety preconditions.
  * *Controlled Execution Service*: Validates proposals, enforces confirmation checks, and records simulated execution in the event ledger.
  * *Verification Service*: Enforces Rules A through E to deterministically prove completion.
  * *Lifecycle Closure Service*: Enforces Rules 1 through 7 before allowing status transition to `COMPLETED`.
* **Persistence & Memory**: **SQLite** database using WAL mode, foreign key constraints, and aggregate repository abstractions.
* **Agent Orchestrator**: Multi-turn conversational manager with stateful pronoun resolution and strict confirmation parsing (`is_explicit_confirmation` vs `is_ambiguous_confirmation`).
* **Frontend Demo Interface**: **React 19 + TypeScript + Vite**, featuring ambient dark mode styling, single-click demo scenarios, real-time MCP tool activity tracking, confirmation cards, and an interactive lifecycle timeline.

---

## Demo Scenario: The University Application

Threadback's canonical demonstration showcases the complete 9-phase lifecycle:

1. **Discover**: User asks *"What am I forgetting?"* → Threadback discovers open intentions and highlights the urgent, blocked University Application.
2. **Reconstruct**: User asks *"Where did I leave off?"* → Threadback reconstructs context: application deadline approaching, transcripts received, recommendation letter pending.
3. **Understand**: User asks *"Why haven't I finished it?"* → Threadback identifies the specific blocker: missing recommendation letter from Professor Smith.
4. **Decide**: User asks *"What should I do?"* → Threadback recommends an unblocker action: send a follow-up inquiry to Professor Smith.
5. **Prepare**: User requests *"Help me finish it."* → Threadback prepares a structured action proposal and pauses execution, requesting confirmation.
6. **Confirm**: User authorizes *"Yes, go ahead."* → Threadback validates explicit confirmation and simulates execution. (`SIMULATED ACTION ≠ COMPLETION`).
7. **Evidence**: Factual evidence arrives: admissions portal confirms recommendation letter received and application submitted.
8. **Verify**: User asks *"Is it actually finished?"* → Threadback verifies completion deterministically against Rule D (`VERIFIED` by deterministic completion rules).
9. **Close**: User commands *"Close it."* → Threadback closes the thread, transitioning it to `COMPLETED` and logging the audit event.

---

## Alexa+ Relevance

Threadback was designed around the emerging paradigm of conversational AI assistants such as **Amazon Alexa+**:

1. **Voice-First Paradigm**: The conversational experience does not assume a screen; responses are phrased naturally for speech without technical IDs or database keys.
2. **MCP Architecture**: Threadback implements the official Model Context Protocol over Streamable HTTP, matching the architecture specified for Alexa+ and Bedrock AgentCore.
3. **Safety & Trust**: High-stakes personal actions must not happen by accident. Threadback's confirmation boundary and simulated execution model provide the guardrails necessary for voice-driven agency.

---

## Current Limitations

* **Simulated Execution**: All actions are executed in `SIMULATED` mode; no real emails, SMS, or external API calls are dispatched.
* **Local Storage**: Data persistence utilizes local SQLite rather than a distributed cloud database (e.g., DynamoDB).
* **Cloud Deployment**: AWS Bedrock AgentCore deployment is frozen due to IAM permission boundaries in the hackathon sandbox.
* **Single User Context**: Built for single-user local deployment; multi-tenant identity federation is not yet implemented.
