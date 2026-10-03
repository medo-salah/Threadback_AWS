# Threadback — M9 Local & Remote MCP Verification Report

## 1. Overview

Milestone M9 requires verification of Threadback's Streamable HTTP Model Context Protocol (MCP) server with OAuth 2.1 authentication, ensuring:
1. Exact behavioral parity with the local deterministic domain engines (M3–M7).
2. Enforcement of all safety invariants (controlled simulated execution, explicit confirmation, no real external side effects).
3. Local latency benchmarking against the Amazon Alexa+ published target (< 500 ms).

---

## 2. Verification Classification

We strictly distinguish local verification from cloud verification:

```text
M9 — CONDITIONAL

LOCAL AUTHENTICATED MCP VERIFICATION: Complete & Verified
AGENTCORE REMOTE MCP VERIFICATION: Pending (Blocked by AWS IAM ViewOnlyAccess)
ALEXA+ ONBOARDING: Prepared (Blocked by Partner/Toolkit Access)
```

| Verification Domain | Status | Notes |
| :--- | :---: | :--- |
| **Local Authenticated MCP Verification** | **COMPLETE** | Verified over live local Streamable HTTP uvicorn server with OAuth 2.1 Bearer authentication. |
| **Local/Remote Behavioral Parity** | **COMPLETE** | Verified parity across all 7 tools between local engine and authenticated HTTP server. |
| **Safety Invariants Enforcement** | **COMPLETE** | Confirmation requirements, simulated execution, and idempotency verified. |
| **Local Latency Benchmarks** | **COMPLETE** | Measured locally; all 7 tools complete in under 40 ms. |
| **AgentCore Cloud Verification** | **PENDING** | Cloud verification not performed because cloud deployment is blocked by IAM `ViewOnlyAccess`. |
| **Alexa+ Simulator Verification** | **PENDING** | Cloud simulator testing not performed because Alexa+ MCP Toolkit access is partner-restricted. |

---

## 3. Local Authenticated MCP Verification Sequence & Results

All 7 deterministic tools were verified over a live local Streamable HTTP server with valid OAuth 2.1 Bearer authentication (`test_m9_parity.py`):

> Tested against the local authenticated Streamable HTTP server. AgentCore cloud verification remains pending because the current AWS credential has ViewOnlyAccess.

| Step | Operation / Tool | Inputs | Verification Outcome | Parity with Local Engine |
| :---: | :--- | :--- | :---: | :---: |
| 1 | `initialize` | Client protocol handshake | **PASS** | Validates active protocol version `2025-11-25` |
| 2 | `tools/list` | List advertised capabilities | **PASS** | Advertises exactly the 7 canonical tools |
| 3 | `discover_unfinished_threads` | `{}` | **PASS** | Exact match with `ThreadService.list_threads()` |
| 4 | `get_thread_context` | `{"thread_id": "thread-university-application"}` | **PASS** | Exact match with `ThreadService.get_thread()` |
| 5 | `find_thread_blockers` | `{"thread_id": "thread-university-application"}` | **PASS** | Exact match with `ThreadService.find_blockers()` |
| 6 | `analyze_thread` | `{"thread_id": "thread-university-application"}` | **PASS** | Exact match with `AnalysisService.analyze()` |
| 7 | `suggest_next_action` | `{"thread_id": "thread-university-application"}` | **PASS** | Exact match with `NextActionService.suggest_action()` |
| 8 | `prepare_action` | `{"thread_id": "thread-client-report"}` | **PASS** | Exact match with `ActionPreparationService.prepare_action()` |
| 9 | `execute_action` | `{"proposal_id": "...", "confirmed": true, "execution_mode": "SIMULATED"}` | **PASS** | Exact match with `ExecutionService.execute_action()` |

---

## 4. Safety Invariant Verification

The authenticated MCP server maintains all critical safety invariants established in M7 and M8:

1. **Deterministic Source of Truth:**
   The MCP server dispatches all requests directly to the authoritative domain engines. An LLM or external agent cannot invent threads, fabricate evidence, create synthetic blockers, or forge action proposals.
2. **Confirmation Boundary:**
   Invoking `execute_action` with `confirmed=False` on an action proposal that requires confirmation is strictly rejected (`execution_status = "REJECTED"`). User confirmation is never inferred.
3. **Controlled Simulation Only:**
   The execution engine only accepts `execution_mode = "SIMULATED"`. No real emails, SMS, phone calls, calendar events, or payments are dispatched.
4. **Proposal Validation & Idempotency:**
   Non-existent proposal IDs are rejected. Re-executing an already executed proposal returns `ALREADY_EXECUTED` without duplicate audit events.
5. **No Bearer Tokens in Query Strings:**
   Passing `?access_token=...` or `?token=...` in query parameters returns HTTP 401 `invalid_request` per Section 8 constraints.

---

## 5. Local Round-Trip Performance Benchmarks

> **Latency Scope Notice:** Local authenticated Streamable HTTP benchmarks are below the published Alexa+ <500 ms target. AgentCore cloud latency remains unverified until remote deployment is available.

Tested against the local authenticated server over Streamable HTTP (`test_m9_performance.py`):

| Operation | Local Measured Latency | Published Alexa+ Target | Local Benchmark Status |
| :--- | :---: | :---: | :---: |
| `initialize` | **6.83 ms** | < 500 ms | Within target (local benchmark) |
| `tools/list` | **6.08 ms** | < 500 ms | Within target (local benchmark) |
| `discover_unfinished_threads` | **38.59 ms** | < 500 ms | Within target (local benchmark) |
| `get_thread_context` | **14.86 ms** | < 500 ms | Within target (local benchmark) |
| `find_thread_blockers` | **4.51 ms** | < 500 ms | Within target (local benchmark) |
| `analyze_thread` | **11.27 ms** | < 500 ms | Within target (local benchmark) |
| `suggest_next_action` | **5.23 ms** | < 500 ms | Within target (local benchmark) |
| `prepare_action` | **7.41 ms** | < 500 ms | Within target (local benchmark) |
| `execute_action` | **6.50 ms** | < 500 ms | Within target (local benchmark) |

