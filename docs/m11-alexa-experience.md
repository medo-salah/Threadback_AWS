# Milestone M11 — Alexa+ Experience & Hackathon Readiness

## Status: COMPLETE

**Previous State:** M10 Complete / Frozen.
**Primary Theme:** Alexa+-style natural conversational experience, conversation state continuity, confirmation safety, and hackathon demo readiness across the existing 9 canonical MCP tools.

---

## 1. M11 Objective

The objective of M11 is to make the Threadback system **hackathon-demo ready and Alexa+-experience ready** without introducing unsupported cloud assumptions or altering the frozen M10 deterministic architecture.

M11 delivers:
1. **Alexa+-Style Conversational Interaction**: Natural spoken dialogue without exposing technical identifiers, database keys, or MCP tool names.
2. **Conversational Intent Routing**: Seamless mapping from natural-language requests to the existing 9 canonical MCP tools.
3. **Conversational Continuity & State**: Pronoun and relative reference resolution ("it", "that", "this", "the blocker") anchored to active thread context across multi-turn conversation.
4. **Strict Confirmation Safety**: Preservation of the M6/M7 confirmation boundary where tentative or inquisitive responses ("maybe", "sounds good", "what happens if you do it?") are rejected as authorization.
5. **Deterministic Verification & Closure**: Completion is verified strictly via factual evidence; the agent cannot hallucinate completion or bypass verification.
6. **Canonical 9-Phase Demo Walkthrough**: A complete, predictable narrative for the University Application scenario.
7. **Development Observability**: Lightweight structured logging tracing `conversation → agent decision → selected MCP tool → tool result → next agent decision`.
8. **Preserved Boundaries**: Clear demarcation between local SQLite persistence/simulated execution and future remote AgentCore / Alexa+ deployment.

---

## 2. Conversational Intent Routing

The agent routes natural conversational inputs to deterministic MCP tool sequences:

| Phase / Intent | Example User Utterance | Conceptual Flow | MCP Tools Orchestrated | Spoken Alexa+ Response |
| :--- | :--- | :--- | :--- | :--- |
| **1. Discovery** | *"What am I forgetting?"* | `discover_unfinished_threads` → `analyze_thread` | `discover_unfinished_threads`, `analyze_thread` | Summarizes unfinished intentions; highlights urgent blocked thread. |
| **2. Context Reconstruction** | *"Where did I leave off?"* | Identify target → `discover_unfinished_threads` → `get_thread_context` → `analyze_thread` | `discover_unfinished_threads`, `get_thread_context`, `analyze_thread` | Explains current status, commitments, and blockers in plain language. |
| **3. Blocker Investigation** | *"Why haven't I finished it?"* | Identify target → `find_thread_blockers` → `analyze_thread` | `find_thread_blockers`, `analyze_thread` | Explains specific missing dependency (e.g. recommendation letter). |
| **4. Next Action** | *"What should I do?"* | Identify target → `suggest_next_action` | `suggest_next_action` | Explains recommended next step and clarifies confirmation requirement. |
| **5. Action Preparation** | *"Help me finish it."* | Identify target → `suggest_next_action` → `prepare_action` | `suggest_next_action`, `prepare_action` | Prepares ActionProposal, pauses execution, and requests explicit user confirmation. |
| **6. Confirmation** | *"Yes, go ahead."* | Validate explicit confirmation → `execute_action` | `execute_action` | Executes proposal in `SIMULATED` mode; records audit event. |
| **7. Evidence Arrival** | External evidence arrival | Persisted evidence added to thread | Repository update | New evidence recorded in Intent Memory. |
| **8. Verification** | *"Is it actually finished?"* | Identify target → `verify_thread_completion` | `verify_thread_completion` | Reports deterministic verification status (`VERIFIED` or `NOT_VERIFIED`). |
| **9. Closure** | *"Close it."* | `verify_thread_completion` → `close_thread` | `verify_thread_completion`, `close_thread` | Verifies evidence, closes thread, transitions to `COMPLETED`. |

---

## 3. Conversation State Management & Continuity

### 3.1 Pronoun and Reference Resolution
The agent maintains `session.active_thread_id` and `session.pending_thread_id` across turns.
When a user uses conversational references:
* *"it"*
* *"that"*
* *"this"*
* *"the application"*
* *"the blocker"*
* *"leave off"*

The agent resolves the reference to the currently active thread without silently switching context.

### 3.2 Ambiguity & Disambiguation
If multiple unfinished threads exist and no active thread context has been established:
* The agent does **NOT** guess or silently pick a thread.
* The agent returns a clarification prompt:
  > *"I found multiple unfinished intentions (such as your University Application, Client Q3 Report, and Dentist Appointment). Which one would you like to discuss?"*

### 3.3 Unknown Intentions
If the user references an intention not present in the system:
* The agent returns a polite request for clarification:
  > *"I couldn't find an unfinished intention matching that. Can you give me a little more context?"*

---

## 4. Confirmation Safety Policy

Threadback strictly enforces the M6/M7 confirmation policy.

### 4.1 Rejection of Ambiguous Confirmation
The following utterances are **NEVER** treated as authorization:
* *"maybe"*
* *"what happens if you do it?"*
* *"sounds good"*
* *"okay, what would that do?"*
* *"tell me more"*
* *"what if?"*

When an action proposal is pending confirmation and an ambiguous response is received:
1. Execution is **NOT** invoked (`execute_action` is blocked).
2. The proposal remains pending on standby.
3. The agent clearly re-prompts for explicit authorization:
   > *"Action execution requires explicit authorization before proceeding. I have a prepared action proposal on standby. Execution will be strictly SIMULATED — no actual email or external communication will be sent. Would you like me to proceed with the simulation? Please answer 'Yes' or 'Go ahead' to authorize."*

### 4.2 Explicit Confirmation
Execution proceeds **ONLY** when explicit, affirmative authorization is provided:
* *"Yes"*
* *"Go ahead"*
* *"Execute it"*
* *"Proceed"*
* *"Yes, go ahead"*

### 4.3 Simulation Boundary
All execution remains strictly in `SIMULATED` mode (`execution_mode="SIMULATED"`). Threadback never issues external network requests, emails, SMS, calendar invites, or payments.

---

## 5. Canonical 9-Phase Demo Walkthrough

The canonical demonstration follows the University Application scenario:

```text
Phase 1: Discover
User:   "What am I forgetting?"
Agent:  Discovers unfinished intentions and highlights the University Application.
Tools:  discover_unfinished_threads, analyze_thread

Phase 2: Reconstruct
User:   "Where did I leave off?"
Agent:  Reconstructs commitments, status (BLOCKED), and recent evidence.
Tools:  discover_unfinished_threads, get_thread_context, analyze_thread

Phase 3: Understand Blocker
User:   "Why haven't I finished it?"
Agent:  Explains the recommendation-letter dependency from Ahmed.
Tools:  find_thread_blockers, analyze_thread

Phase 4: Next Action
User:   "What should I do?"
Agent:  Recommends drafting a follow-up request to Ahmed.
Tools:  suggest_next_action

Phase 5: Prepare Action
User:   "Help me finish it."
Agent:  Prepares an ActionProposal and pauses for confirmation.
Tools:  suggest_next_action, prepare_action

Phase 6: Confirm Action
User:   "Yes, go ahead."
Agent:  Executes simulated follow-up action; logs audit event.
Tools:  execute_action (SIMULATED)

Phase 7: New Evidence
System: Structured evidence received: recommendation letter confirmed.
Memory: Evidence appended to persistent repository.

Phase 8: Verify Completion
User:   "Is it actually finished?"
Agent:  Deterministically checks evidence and reports VERIFIED.
Tools:  verify_thread_completion

Phase 9: Close Thread
User:   "Close it."
Agent:  Verifies preconditions and transitions thread to COMPLETED.
Tools:  verify_thread_completion, close_thread
```

---

## 6. Observability

To aid development, debugging, and demo inspection, Threadback includes structured observability logging tracing the full agent lifecycle:

```text
[AGENT_OBSERVABILITY] conv=conv-demo-1 decision='suggest_and_prepare_action' tool=suggest_next_action result_status=NONE next_decision='prepare_action'
[AGENT_OBSERVABILITY] conv=conv-demo-1 decision='proposal_prepared_awaiting_confirmation' tool=prepare_action result_status=proposal-xxx next_decision='request_explicit_confirmation'
[AGENT_OBSERVABILITY] conv=conv-demo-1 decision='execute_confirmed_action' tool=execute_action result_status=EXECUTED next_decision='report_simulated_execution'
```

---

## 7. Alexa+ Spoken Interaction Principles

1. **Concise Spoken Responses**: Formatted for natural text-to-speech reading without awkward data dumps.
2. **Omission of Raw Internal Identifiers**: Phrases avoid technical strings like `thread-university-application`, `proposal-774f...`, or `dependency_id` in normal spoken dialogue.
3. **Conversational Follow-ups**: Responses conclude with natural next steps (e.g. *"Would you like me to prepare a recommended next action?"*).
4. **Clear Distinctions**: The interface and agent responses clearly differentiate a **SIMULATED ACTION** (intention still active) from **VERIFIED / COMPLETED** (closure verified by evidence).

---

## 8. Preserved Boundaries & Current Limitations

1. **Local SQLite Persistence**: Thread memory, proposals, audit events, and verification records are persisted in local SQLite. Remote cloud databases (DynamoDB, PostgreSQL) are out of scope.
2. **Strict Simulated Execution**: Real external communication (SMTP, SES, Twilio, Google Calendar) is intentionally not implemented.
3. **M9 AgentCore Deployment Limitation**: Cloud deployment through Bedrock AgentCore Runtime remains **CONDITIONAL / FROZEN** due to AWS IAM ViewOnly permissions.
4. **Alexa+ Integration Limitation**: Official Alexa+ developer toolkit/partner onboarding remains pending access.
