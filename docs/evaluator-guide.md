# Threadback — Evaluator Guide

**Quick Reference for Hackathon Judges & Evaluators**

---

## 1. What Threadback Is

> **People don't forget tasks. They forget intentions.**

**Threadback** is an intent-recovery agent. While traditional task managers and reminders treat commitments as isolated checkboxes, Threadback reconstructs unfinished human intentions from conversational context and factual evidence, guides users through blockers, and safely verifies completion before closing open loops.

---

## 2. What Makes It Different

| Traditional Assistants / To-Do Apps | Threadback Intent Recovery Agent |
| :--- | :--- |
| Reminds users at fixed times regardless of context. | Reconstructs the context of *why* an intention stalled and where you left off. |
| Treats commitments as simple checkboxes. | Models commitments with dependencies, blockers, evidence, and audit history. |
| AI hallucination can declare tasks completed. | Completion is governed by deterministic evidence rules (**EXECUTION_SUCCESS ≠ COMPLETION**). |
| Takes actions without clear safety boundaries. | Enforces an explicit confirmation gate and executes strictly in `SIMULATED` mode. |

---

## 3. How to Run It

### Terminal 1: Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* Backend API: `http://localhost:8000`
* MCP Server: `http://localhost:8000/mcp`
* API Docs: `http://localhost:8000/docs`

*(Or execute `./scripts/dev-backend.sh`)*

### Terminal 2: Frontend

```bash
cd frontend
npm install
npm run dev
```
* Web UI: `http://localhost:5173`

*(Or execute `./scripts/dev-frontend.sh`)*

---

## 4. How to Reset the Demo

To return to the clean canonical starting state at any time:
* **Option A**: Click the **`Reset Demo`** button in the top navigation bar of the Web UI.
* **Option B**: Send a reset POST request:
  ```bash
  curl -X POST http://localhost:8000/api/agent/demo-reset \
       -H "Content-Type: application/json" \
       -d '{"conversation_id": "session-default"}'
  ```

---

## 5. Canonical Demo (9-Phase Flow)

Run these prompts sequentially in the chat input or click the demo scenario buttons:

| Phase | Spoken User Prompt | Behind the Scenes | What to Observe |
| :--- | :--- | :--- | :--- |
| **1. Discover** | *"What am I forgetting?"* | Calls `discover_unfinished_threads` & `analyze_thread` | Summarizes open intentions; highlights urgent, blocked **University Application**. Context is set. |
| **2. Reconstruct** | *"Where did I leave off?"* | Resolves pronoun reference; calls `get_thread_context` | Displays deadlines, commitments, and current `BLOCKED` status without re-prompting for thread name. |
| **3. Understand** | *"Why haven't I finished it?"* | Calls `find_thread_blockers` | Pinpoints root cause: missing recommendation letter from Professor Smith. |
| **4. Decide** | *"What should I do?"* | Calls `suggest_next_action` | Recommends prioritized unblocker action: send follow-up inquiry to Professor Smith. |
| **5. Prepare** | *"Help me finish it."* | Calls `prepare_action` | **Safety Pause**: Generates `ActionProposal`, displays risk level (`MEDIUM`), asks for explicit authorization. |
| **6. Confirm** | *"Yes, go ahead."* | Validates confirmation; calls `execute_action` | **Simulation Badge**: Executes in `SIMULATED` mode. Note: **SIMULATED ACTION ≠ COMPLETION** (Thread remains `BLOCKED`). |
| **7. Evidence** | *(Evidence Ingested)* | Recommendation letter received via portal | Independent evidence record stored in persistent SQLite memory. |
| **8. Verify** | *"Is it actually finished?"* | Calls `verify_thread_completion` | **Deterministic Verification**: Evaluates Rule D. Returns `VERIFIED` by deterministic completion rules. |
| **9. Close** | *"Close it."* | Calls `verify_thread_completion` & `close_thread` | **Completion Badge**: Thread transitions to `COMPLETED`. 10-step Chronological Lifecycle Timeline displayed. |

---

## 6. Architecture

```text
Evaluator Web UI (React + TypeScript + Vite)
      ↓ HTTP / JSON
FastAPI Agent Orchestrator (/api/agent/chat, /demo-reset)
      ↓ MCP Client (Streamable HTTP)
Threadback MCP Server (/mcp) — Exactly 9 Canonical Tools
      ↓ Invocations
Deterministic Domain Engines (Analysis, Next Action, Preparation, Execution, Verification, Lifecycle)
      ↓ Aggregate Repository
SQLite Persistence (WAL mode, Threadback.db)
```

---

## 7. Safety Model & Central Invariants

1. **`EXECUTION_SUCCESS ≠ COMPLETION`**: Simulating or drafting a follow-up inquiry does not complete an intention. Only verified evidence completes an intention.
2. **Explicit Authorization**: Ambiguous replies (*"maybe"*, *"sounds good"*, *"what would that do?"*) are rejected by the confirmation safety analyzer. Only clear affirmative words (*"Yes"*, *"Go ahead"*) authorize simulation.
3. **Deterministic Verification Required**: The agent cannot hallucinate completion. Completion requires structured factual evidence satisfying Rules A through E.
4. **Strict Simulation**: All actions are executed in `SIMULATED` mode; Threadback never triggers real external side effects.

---

## 8. Alexa+ & MCP Relevance

* **Voice-Ready Conversational Dialogue**: Uses natural spoken phrases without exposing IDs, tool names, or internal schemas.
* **Standard Model Context Protocol (MCP)**: Native integration using the official MCP Python SDK over Streamable HTTP at `/mcp` (MCP protocol `2025-11-25` over Streamable HTTP for Alexa+ parity).
* **Boundary Transparency**: Implemented and verified locally. Remote AWS Bedrock AgentCore deployment is frozen/conditional due to hackathon sandbox IAM permissions; official Alexa+ partner onboarding remains pending.

---

## 9. Limitations

* Execution is strictly `SIMULATED` (no live email/SMS).
* Persistence uses local SQLite (not distributed DynamoDB).
* Single-user evaluation environment (no multi-tenant auth).
* Cloud AgentCore runtime deployment is frozen due to IAM constraints.
