# Threadback — Hackathon Submission (Devpost)

## Project Name
**Threadback**

---

## Elevator Pitch

**Tagline (Short Summary / <140 characters):**  
> People don't forget tasks, they forget intentions. Threadback reconstructs unfinished context to safely guide and verify follow-through.

**Elevator Pitch (Field Description):**  
> People don't forget tasks. They forget intentions. Threadback is an intent-recovery agent that reconstructs unfinished human commitments from conversational context and factual evidence, guides users through blockers, simulates counterfactual "What-If" decisions, and safely verifies completion before closing open loops.  
> Built natively on the **Model Context Protocol (MCP)** (protocol `2025-11-25` over Streamable HTTP at `/mcp`), Threadback exposes **9 canonical domain tools** that empower AI assistants—such as **Amazon Alexa+** and **Amazon Bedrock** agents—to discover neglected intentions, calculate "Why Now" attention urgency, simulate counterfactual "What-If" decisions, and safely drive open loops to verified resolution without hallucinating state completion.

---

## Track & Mini Challenge Selection

* **Primary Track**: **Alexa+**  
  * **Mechanism**: Self-hosted Model Context Protocol (MCP) server.  
  * **Protocol Version**: Native `2025-11-25`.  
  * **Transport & Endpoint**: Stateless Streamable HTTP hosted at `/mcp`.  
  * **Tool Catalog**: Exactly 9 canonical domain tools exposed via official Python MCP SDK.  
  * **Rule Alignment**: Complies with the official Alexa+ hackathon rules and developer FAQ, which explicitly state that participants do not require gated preview developer tools and may compete via a self-hosted MCP server or simulated experience.  
  * **Boundaries**: Truthfully implemented and verified as a local self-hosted MCP server. Not published to a live Amazon MCP registry, not a published Alexa+ Add-on, not tested on Echo hardware, and not live in the Alexa+ cloud.

* **AWS Builder Mini Challenge**: **QUALIFIES (Integration-Ready)**  
  * Incorporates Amazon Bedrock Claude 3.5 Sonnet / Claude 3 Haiku invocation via `boto3`, AWS Strands Agents SDK agent orchestration, and containerized Docker packaging for Amazon Bedrock AgentCore (`Dockerfile.agentcore`, deployment specification).  
  * Cloud deployment is truthfully documented as Integration-Ready (provisioning blocked by hackathon sandbox IAM `ViewOnlyAccess`).

* **Open Source Mini Challenge**: **DOES NOT QUALIFY / EVIDENCE NOT FOUND**  
  * The official contest rules require a separate new open-source project or contribution created during the hackathon window alongside the primary track entry. Threadback does not include an external qualifying contribution or secondary open-source repository; therefore, this mini challenge is not claimed.

---

## What We Built During the Hackathon

Threadback was developed through an iterative milestone engineering process. We clearly delineate our foundational baseline from the major user-facing intelligence capabilities built during the hackathon submission window:

### Foundational Architecture (M0–M12 Baseline)
* Core 9-stage intention lifecycle domain model (`Conversation → Intent → Commitment → Dependency → Unfinished State → Next Action → Evidence → Verification → Closure`).
* 9 canonical MCP domain tools implemented with official Python MCP SDK over Streamable HTTP at `/mcp` on protocol `2025-11-25`.
* Initial SQLite persistence layer with Write-Ahead Logging (WAL) and restart durability.
* Deterministic Next-Action scoring and Action Proposal preparation with safety preconditions.
* Confirmation safety gate (requiring explicit human affirmative authorization) and simulated external execution logging.
* Deterministic evidence-based verification engine (Rules A through E) and protected lifecycle closure.
* Evaluator-ready React 19 + TypeScript frontend shell with live MCP telemetry drawer.
* 286 automated tests baseline.

### Significant Intelligence Additions Built During Hackathon (M13–M16)
* **M13 — Persistent Intent Memory & Lifecycle Evolution**:
  * Original goal vs. evolving current goal tracking with immutable `IntentEvolution` audit history.
  * Inactivity decay calculation and automated deadline urgency scoring.
  * Explicit extended lifecycle states: `DEFERRED`, `WAITING`, and `ABANDONED` transitions.
* **M14 — Proactive Intent Intelligence & Attention Engine**:
  * **Attention Radar**: Strictly decouples impending deadline **Urgency** from cognitive **Attention Need**, ending notification fatigue.
  * **Why Now Engine**: Generates explainable, deterministic attention drivers (e.g., blocker duration, deadline pressure, recent unblocking).
  * **Multi-Horizon Change Diff**: Tracks state evolution across 24h, 7d, and 30d horizons.
  * **Cross-Thread Conflict Detection**: Conservative detection of time collisions, exclusive resource contention, deadline impossibilities, and goal exclusions.
  * **Resumable Candidates**: Automatically surfaces stalled intentions that have become actionable due to external changes.
* **M15 — Intent Copilot & Conversational Decision Support**:
  * **Conversational Intent Copilot**: Supports natural queries (*"What should I do first?"*, *"Why is this important?"*, *"I have 30 minutes. What can I realistically finish?"*, *"Can I close anything?"*).
  * **Counterfactual What-If Simulation**: Zero-mutation simulation engine projecting downstream deadline, conflict, and dependency consequences—strictly labeled with the on-screen badge `🔮 SIMULATION — NO STATE CHANGED`.
  * **Time-Budget Planning**: Constraint-based unblocking planner allocating high-leverage actions across 15m, 30m, and 120m windows.
  * **Safe Closure Assistant**: Proactively identifies verification-ready threads, prevents accidental abandonment, and safely guides users to closure.
  * **Interactive Intent Decision Cards**: Rich UI cards presenting structured choices, tradeoffs, and recommended paths.
  * **Conversational Continuity**: Context-aware pronoun resolution (`"it"`, `"where was I"`) and multi-turn state tracking.
* **M16 — Hackathon Pitch & Submission Package**:
  * Expanded automated test suite from 286 to **401 tests** (100% pass rate).
  * Calibrated 3-minute video pitch script (371 spoken words, ~2:45–2:55 runtime, 5–16s safety margin).
  * Complete, synchronized Devpost submission package with transparent cloud boundary disclosures.

---

## About the Project

### 1. The Human Problem
Traditional to-do apps, calendars, and digital assistants fail at human follow-through because they treat human commitments as static checkboxes. In reality, human work consists of complex, evolving intentions with dependencies, blockers, and external stakeholders. When an application stalls because a professor hasn't sent a recommendation letter, an alarm reminding the user to "Submit application" does not help—it causes notification fatigue. When intentions fall behind, humans abandon their lists because traditional tools lose the surrounding context, blockers, evidence, and state.

### 2. What Threadback Does
Threadback is an intent-recovery agent. Instead of storing inert task lists, Threadback reconstructs the living context of open human commitments, diagnoses root blockers, evaluates attention priorities, simulates counterfactual decisions, safely prepares actions, deterministically verifies proof, and safely closes open loops.

### 3. The 9-Stage Intention Lifecycle
Threadback models commitments through a continuous, structured 9-stage lifecycle:
```text
Conversation → Intent → Commitment → Dependency → Unfinished State → Next Action → Evidence → Verification → Closure
```

### 4. M13 Persistent Intent Memory
Intentions change over time. Threadback distinguishes an intention's original goal from its evolving current goal, preserving a chronological `IntentEvolution` audit ledger. It tracks inactivity decay, calculates deadline urgency, and supports explicit state transitions (`DEFERRED`, `WAITING`, `ABANDONED`) with full restart durability in WAL-mode SQLite.

### 5. M14 Proactive Intent Intelligence
Threadback features an **Attention Radar** that separates deadline urgency from cognitive attention need. It delivers deterministic **Why Now** explanations, computes multi-horizon change diffs across sessions, detects cross-thread conflicts (time collisions, shared resource contention, conflicting deadlines), and flags resumable intentions that have become unblocked.

### 6. M15 Intent Copilot & Decision Support
Threadback includes an ambient **Intent Copilot** that helps users make decisions conversationally:
* *"What should I deal with first?"* → Prioritized recommendation based on Attention Radar scoring.
* *"What if I postpone this?"* → Counterfactual **What-If Simulation** projecting downstream consequences without mutating stored state (`SIMULATION — NO STATE CHANGED`).
* *"I have 30 minutes. What can I finish?"* → Constraint-aware time-budget allocation.
* *"Can I close anything?"* → Safe closure assistant surfacing verified intentions ready for completion.

### 7. MCP Implementation
Threadback is built natively on the **Model Context Protocol (MCP)** using the official Python MCP SDK:
* Protocol Version: `2025-11-25`.
* Transport: Streamable HTTP hosted at `/mcp`.
* Exactly 9 canonical domain tools: `discover_unfinished_threads`, `get_thread_context`, `find_thread_blockers`, `analyze_thread`, `suggest_next_action`, `prepare_action`, `execute_action`, `verify_thread_completion`, `close_thread`.

### 8. Safety & Verification Model
Threadback enforces three non-negotiable safety pillars:
1. **`SIMULATED EXTERNAL ACTION`**: Operational actions (emails, applications) are executed in `SIMULATED` mode and recorded to the audit log; no real-world external side effects occur.
2. **`PERSISTENT THREADBACK MUTATION`**: Internal state changes (goal updates, deferrals, status changes) persist durably to SQLite via domain services only after explicit human confirmation.
3. **`VERIFIED COMPLETION (EXECUTION_SUCCESS ≠ COMPLETION)`**: Executing an action does not complete an intention. Completion is strictly verification-gated by independent factual evidence validated against deterministic domain rules (Rules A through E).

### 9. What Was Built During the Hackathon
As detailed above, while the M0–M12 foundation provided the core 9-stage lifecycle and MCP tool scaffolding, the hackathon period delivered the complete intelligence and copilot layers: M13 Persistent Intent Memory, M14 Attention Radar & Why Now reasoning, M15 Intent Copilot with counterfactual What-If simulations and time-budget planning, and M16 test expansion to 401 tests.

### 10. Honest Integration Limitations
* **Simulated Execution**: All operational external actions remain simulated by design.
* **Local Persistence**: Intent memory is stored in durable local SQLite (WAL mode); multi-device cloud synchronization is future work.
* **Bedrock AgentCore Cloud Deployment**: Docker container packaging (`Dockerfile.agentcore`) and deploy automation are Integration-Ready; cloud deployment was frozen due to hackathon sandbox IAM permissions (`ViewOnlyAccess`).
* **Alexa+ Add-on Live Onboarding**: Add-on manifest and capability configurations are Integration-Ready; live onboarding remains pending Amazon preview partner toolkit access.

---

## Built With

* `model-context-protocol` (Official Python MCP SDK)
* `streamable-http` (MCP Transport at `/mcp`, protocol `2025-11-25`)
* `amazon-bedrock` (Anthropic Claude 3.5 Sonnet & Claude 3 Haiku Model Access)
* `strands-agents` (AWS Agent Orchestration SDK)
* `boto3` (AWS SDK for Python)
* `fastapi` & `uvicorn` (ASGI Application Gateway & MCP Mounting)
* `sqlite` (WAL-mode Persistent Intent Memory)
* `react` (React 19 Frontend)
* `typescript`
* `vite`
* `docker` (ARM64 Bedrock AgentCore Container Packaging)

---

## Hackathon Tool & SDK Feedback

In accordance with official hackathon submission requirements, we provide comprehensive technical feedback for every material tool, API, and SDK utilized:

### 1. Model Context Protocol (MCP) Python SDK (`mcp`)
* **What did we use it for?**: Implementing our 9 canonical domain tools, defining tool input schemas via Pydantic reflection, managing JSON-RPC 2.0 message handling, and hosting the stateless Streamable HTTP transport at `/mcp`.
* **What worked well?**: Standardized schema generation from Python types, clean tool registration decorators, and strict protocol validation ensured high reliability.
* **What needs improvement?**: Streamable HTTP transport documentation lacks complete, end-to-end examples with FastAPI and Starlette mounting. Debugging session initialization and protocol version negotiation discrepancies required inspecting SDK source code.
* **How was onboarding from zero to hello world?**: Moderate. Stdio transport was immediate; Streamable HTTP required custom ASGI adapter middleware.
* **Would we build with it again? Why?**: **Yes**. Standardized tool interfaces are essential for cross-platform agent interoperability across Alexa+, Bedrock, and developer IDEs.

### 2. AWS Strands Agents SDK (`strands-agents`)
* **What did we use it for?**: High-level agent orchestration combining `BedrockModel` (Claude 3.5 Sonnet) with `MCPClient` in our Amazon Bedrock provider architecture.
* **What worked well?**: Clean, declarative agent creation (`Agent(model=BedrockModel(...), tools=[MCPClient(...)])`) eliminates boilerplate tool-dispatch plumbing.
* **What needs improvement?**: Error reporting during initialization when credentials or remote MCP endpoints fail can be opaque. Type annotations could be more complete for complex nested tool return objects.
* **How was onboarding from zero to hello world?**: Smooth for standard single-turn tool calling; required custom wrapper logic to enforce Threadback's strict human confirmation pause before execution.
* **Would we build with it again? Why?**: **Yes**. It provides a clean, idiomatic framework for Bedrock-native agent tool calling.

### 3. Amazon Bedrock & Boto3 (`boto3`)
* **What did we use it for?**: Managing AWS sessions, IAM credential resolution, and runtime model invocation access to Anthropic Claude 3.5 Sonnet on Amazon Bedrock.
* **What worked well?**: Robust, enterprise-grade credential resolution chain (environment variables, IAM roles, AWS SSO) and predictable inference latencies.
* **What needs improvement?**: Model access enablement in the AWS Console has regional availability disparities; clearer error messaging when specific model IDs are disabled in an active region would accelerate developer onboarding.
* **How was onboarding from zero to hello world?**: Standard and familiar for experienced AWS developers.
* **Would we build with it again? Why?**: **Yes**. Unmatched enterprise model catalog, privacy guarantees, and IAM compliance.

### 4. Amazon Bedrock AgentCore Packaging (Container & Runtime Specification)
* **What did we use it for?**: Packaging Threadback into a standalone ARM64 container image (`Dockerfile.agentcore`), defining runtime configuration (`agentcore/runtime-config.json`), and authoring deployment automation (`agentcore/deploy.sh`).
* **What worked well?**: Standard Docker multi-architecture contract ensures clean container portability.
* **What needs improvement?**: Absence of a local AgentCore emulator or CLI for offline testing prior to cloud deployment made development reliant on manual specification verification; sandbox IAM `ViewOnlyAccess` prevented deployment testing.
* **How was onboarding from zero to hello world?**: Steep due to preview-only documentation and lack of public tooling.
* **Would we build with it again? Why?**: **Conditional**. We would build with it again once public developer CLI tools and local emulators are released.

---

## Canonical Demo Scenario & Video Pitch Alignment

Threadback's demonstration is fully scripted in [`docs/demo-script.md`](demo-script.md):
* **Duration**: Calibrated for under 3 minutes (exact 371 spoken words, ~2:45–2:55 runtime, 5–16s safety margin).
* **Demonstrated Capabilities**:
  1. **Discover**: Surfacing forgotten, blocked intentions.
  2. **Reconstruct**: Pronoun-aware context retrieval (`"Where did I leave off?"`).
  3. **Intent Intelligence**: Attention Radar separating urgency from attention, explainable Why Now reasoning.
  4. **Intent Copilot**: Counterfactual What-If simulation (`SIMULATION — NO STATE CHANGED`), 30-minute time budgeting.
  5. **Safe Execution**: Human confirmation pause, explicit authorization check, simulated action execution.
  6. **Deterministic Verification**: Independent portal proof arrives, Rule D deterministic validation.
  7. **Safe Closure**: Intent completes with verified audit record.
  8. **MCP Callout**: Visible MCP drawer highlighting Protocol `2025-11-25`, Streamable HTTP, `/mcp`, and 9 canonical tools.
