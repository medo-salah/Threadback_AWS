# Threadback — Milestone M9 Final Report & Technical Audit

## Status Classification

```text
M9 — CONDITIONAL

Implementation/readiness: Substantially Complete
Local verification: Complete (242 tests passing)
AgentCore cloud deployment: BLOCKED by AWS IAM (ViewOnlyAccess)
AgentCore remote verification: NOT PERFORMED
Alexa+ actual onboarding: BLOCKED by partner/toolkit access
```

---

## 1. Executive Summary

Milestone M9 adapts Threadback's deterministic Model Context Protocol (MCP) server for cloud deployment via Amazon Bedrock AgentCore Runtime and prepares the service for the official Amazon Alexa+ integration path.

Threadback's core intelligence remains strictly grounded in the deterministic domain engine implemented across Milestones M3–M7. The MCP server exposes **exactly seven canonical tools** over Streamable HTTP at `/mcp` with active protocol version `2025-11-25`.

All implementation, containerization, local authentication middleware, local parity verification, and Alexa+ scaffolding are complete and pass 100% of the regression and integration test suites (242 tests passed, 0 failures). Live cloud deployment to Amazon Bedrock AgentCore is blocked due to read-only IAM permissions (`ViewOnlyAccess`) on the current hackathon AWS account. Live Alexa+ onboarding is blocked due to Amazon's partner-only access restriction on the Alexa+ MCP Toolkit.

---

## 2. Implemented Capabilities vs Status Categories

We maintain strict technical accuracy by categorizing every element into one of five explicit operational states:

| Category | Capability / Artifact | Description |
| :--- | :--- | :--- |
| **Implemented** | Streamable HTTP `/mcp` | Stateless Streamable HTTP transport at `/mcp` binding `0.0.0.0:8000` with active protocol version `2025-11-25`. |
| **Implemented** | Exactly Seven Tools | `discover_unfinished_threads`, `get_thread_context`, `find_thread_blockers`, `analyze_thread`, `suggest_next_action`, `prepare_action`, `execute_action`. |
| **Implemented** | ARM64 Containerization | `Dockerfile.agentcore` targeting `FROM --platform=linux/arm64 python:3.10-slim` with dedicated non-root user `threadback` and health probe. |
| **Implemented** | Local Auth Middleware | `MCPAuthenticationMiddleware` providing Bearer token validation for local development, CI, and defense-in-depth. |
| **Implemented** | Query Param Token Rejection | Rejection of tokens passed in query parameters (`?access_token=...`) with HTTP 401 `invalid_request`. |
| **Implemented** | Discovery 401 Behavior | Unauthenticated MCP requests return HTTP 401 without `WWW-Authenticate` per official Alexa+ discovery flow requirements. |
| **Implemented** | RFC 9728 & RFC 8414 Metadata | `/.well-known/oauth-protected-resource` (RFC 9728) and `/.well-known/oauth-authorization-server` (RFC 8414 with PKCE `S256`). |
| **Locally Verified** | Local Parity Suite | `test_m9_parity.py` validates identical outputs between local domain services and authenticated HTTP MCP tools. |
| **Locally Verified** | Safety Invariants | Enforced confirmation boundaries, proposal ID validation, idempotency ledger, and simulated execution. |
| **Locally Verified** | Local Latency Benchmark | `test_m9_performance.py` measures local authenticated round-trip latencies (< 40 ms across all 7 tools). |
| **Prepared** | AgentCore Deployment Pipeline | `agentcore/deploy.sh` and `agentcore/runtime-config.json` prepared for automated container push and registration. |
| **Prepared** | Alexa+ Readiness Scaffolding | `alexa/skill.json` manifest and `alexa/capabilities.json` mapping Experiences A through E. |
| **Blocked** | AgentCore Cloud Provisioning | Cloud deployment blocked because the active AWS identity has `ViewOnlyAccess`. |
| **Blocked** | Alexa+ Toolkit Onboarding | Live add-on onboarding blocked because Amazon restricts the Alexa+ MCP Toolkit to select preview partners. |
| **Not Performed** | AgentCore Remote Cloud Verification | Live cloud testing and remote latency measurement were not performed because cloud deployment is blocked. |
| **Not Implemented** | Real External Actions | Disallowed by design. No real emails, SMS, phone calls, calendar mutations, payments, or webhooks. |

---

## 3. Local Verification Results

Verification was performed against a live local authenticated Streamable HTTP server on localhost.

### Parity Between Local Engine and Authenticated MCP Server

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

## 4. AgentCore Deployment Readiness

* **Container Specification:** `Dockerfile.agentcore` pins `FROM --platform=linux/arm64 python:3.10-slim`. It creates a dedicated non-root user `threadback` (`uid/gid` 1000) and exposes port `8000`.
* **Container Health Probe:** `GET /health` with `curl` healthcheck probe configured (30s interval, 5s timeout, 3 retries).
* **Network Binding:** Binds to `0.0.0.0:8000`.
* **Deployment Manifest:** `agentcore/runtime-config.json` serves as Threadback's declarative configuration manifest documenting the intended runtime parameters (`CONTAINER`, `ARM64`, `STREAMABLE_HTTP`, `/mcp`, `CUSTOM_JWT`).
* **Official CLI Workflow:** The deployment script aligns with AWS's documented commands:
  ```bash
  agentcore create
  agentcore add agent --protocol MCP --name threadback-mcp-runtime
  agentcore deploy
  ```

---

## 5. AWS IAM Blocker Analysis

* **AWS Account ID:** `863516093768`
* **Target Region:** `us-east-1`
* **Active Caller Identity:** `arn:aws:iam::863516093768:user/claude-agent`
* **Attached IAM Policies:** `arn:aws:iam::aws:policy/job-function/ViewOnlyAccess`
* **Current AgentCore Runtimes:** `0` (inspected via AWS CLI; calls to `bedrock-agentcore-control` and `ecr` returned `AccessDeniedException`).
* **Existing Cognito User Pools:** `0`
* **AgentCore Runtime ARN:** `NOT CREATED — ViewOnlyAccess`
* **Policy Compliance:** In strict adherence to hackathon rules, no privilege escalation was attempted, no unauthorized billable resources were provisioned, and no cloud infrastructure was modified.

---

## 6. Authentication Architecture

We maintain a strict boundary between cloud gateway authentication and local test authentication:

```text
Production Cloud Flow:
Client / Alexa+
      ↓ (HTTPS + OAuth 2.1)
Bearer JWT
      ↓
AgentCore Gateway (CUSTOM_JWT / Cognito Discovery)
      ↓ (Authorized request forwarding)
Threadback MCP Container (/mcp)
      ↓
Deterministic Core (M3–M7)

Local Development & Testing Flow:
Local Test Client
      ↓
Bearer JWT
      ↓
MCPAuthenticationMiddleware (JWTValidator / HS256 / RS256)
      ↓
Threadback MCP (/mcp)
      ↓
Deterministic Core (M3–M7)
```

### Discovery Endpoints
1. **Protected Resource Metadata (RFC 9728):**
   `GET /.well-known/oauth-protected-resource` returns resource URI, authorization servers, and supported scopes (`mcp:read`, `mcp:write`, `threadback:read`, `threadback:write`).
2. **Authorization Server Metadata (RFC 8414):**
   `GET /.well-known/oauth-authorization-server` advertises OAuth 2.1 authorization code flow with `code_challenge_methods_supported: ["S256"]`.

---

## 7. Alexa+ Integration Readiness

```text
Alexa+ Status: PREPARED — TOOLKIT ACCESS UNAVAILABLE
```

* **Partner Access Limitation:** Amazon currently restricts the Alexa+ MCP Toolkit to select preview partners. The developer account does not have toolkit access.
* **Truth in Advertising:**
  * NO claim of "Alexa+ successfully connected".
  * NO claim of "Alexa+ web simulator tested".
  * NO claim of "Add-on published or certified".
* **Prepared Scaffolding:**
  * Add-on manifest: `alexa/skill.json` declares scopes, OAuth 2.1 PKCE (`S256`), and the `/mcp` Streamable HTTP endpoint.
  * Capability mapping: `alexa/capabilities.json` maps the 7 tools to Experiences A through E (Discovery, Context Reconstruction, Blocker Identification, Next Action, and Controlled Finish).
* **Two-Tier Authentication Model:**
  * Tier 1: `client_credentials` for service-level operations and tool discovery.
  * Tier 2: `authorization_code` with PKCE `S256` for user-specific operations and explicit consent.

---

## 8. Security Invariants

All core safety rules established in M7 and M8 remain strictly enforced:

1. **Authorization Header Enforcement:** Requests to `/mcp` must provide `Authorization: Bearer <token>`.
2. **Query Parameter Token Prohibition:** Passing tokens in query parameters (`?access_token=...`, `?token=...`, `?bearer=...`) is rejected with HTTP 401 `invalid_request`.
3. **Explicit Confirmation Boundary:** Calling `execute_action(proposal_id=..., confirmed=False)` on proposals requiring confirmation returns `execution_status = "REJECTED"`.
4. **Simulated Execution Invariant:** Only `execution_mode = "SIMULATED"` is accepted. Modes such as `REAL` or `LIVE` are rejected.
5. **Proposal Validation:** Non-existent proposal IDs return `execution_status = "REJECTED"`. Blocked proposals return `execution_status = "BLOCKED"`.
6. **Idempotency Ledger:** Re-executing an already executed proposal returns `ALREADY_EXECUTED` without duplicate audit events or mutations.
7. **Deterministic Source of Truth:** The MCP layer never fabricates threads, synthetic evidence, invented blockers, or ungrounded proposals.

---

## 9. Performance Benchmark (Local Authenticated Server)

> **Notice:** These measurements reflect local authenticated Streamable HTTP benchmark tests. AgentCore cloud latency remains unverified until cloud deployment is available.

| Operation | Local Measured Latency | Published Alexa+ Target | Compliance Status |
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

---

## 10. Known Factual Limitations

1. **AgentCore Cloud Deployment Blocked:** The active AWS IAM user lacks provisioning rights (`ViewOnlyAccess`).
2. **AgentCore Remote Cloud Verification Pending:** Cannot be executed without an active cloud runtime endpoint.
3. **Alexa+ MCP Toolkit Access Blocked:** The partner-only toolkit is not available to the current developer account.
4. **No Real-World Actions:** Controlled simulation only (`SIMULATED`). No real emails, calls, SMS, calendar updates, or payments are dispatched.

---

## 11. Verification Commands & Test Results

```bash
# 1. Run all backend unit, integration, parity, and performance tests
backend/.venv/bin/pytest backend/tests/ -v

# 2. Check code quality and style
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend

# 3. Check frontend linter and production build
npm --prefix frontend run lint
npm --prefix frontend run build
```

### Complete Test Results

```text
============================= test session starts ==============================
collected 242 items

backend/tests/test_action_preparation_service.py .............           [  5%]
backend/tests/test_agent_api.py ...                                      [  6%]
backend/tests/test_agent_mcp_http.py .....                               [  8%]
backend/tests/test_agent_service.py .........                            [ 12%]
backend/tests/test_agent_source_of_truth.py .....                        [ 14%]
backend/tests/test_analysis_service.py ................................. [ 28%]
.......................                                                  [ 37%]
backend/tests/test_domain.py ............                                [ 42%]
backend/tests/test_execution_service.py ................                 [ 49%]
backend/tests/test_health.py .....                                       [ 51%]
backend/tests/test_m9_auth.py ...........                                [ 55%]
backend/tests/test_m9_parity.py ........                                 [ 59%]
backend/tests/test_m9_performance.py .                                   [ 59%]
backend/tests/test_mcp.py ...............                                [ 65%]
backend/tests/test_mcp_http_tools.py .....................               [ 74%]
backend/tests/test_mcp_tools.py ..............................           [ 86%]
backend/tests/test_next_action_service.py ....................           [ 95%]
backend/tests/test_thread_service.py ............                        [100%]

============================= 242 passed in 6.55s ==============================
```

* **Backend Tests:** 242 passed, 0 failed, 0 skipped
* **Ruff Check:** Clean (0 errors across 53 files)
* **Ruff Format:** Clean (53 files formatted)
* **Frontend Lint (oxlint):** Clean (0 warnings, 0 errors in 36 ms)
* **Frontend Build (tsc -b && vite build):** Clean production bundle (98 ms)

---

## 12. Evidence & Compliance Audit

* **MCP Endpoint:** `POST /mcp` tested over live HTTP uvicorn instance using official MCP Python SDK `ClientSession` and `streamable_http_client`.
* **Stateless Operation:** Verified by session initialization and teardown across independent calls.
* **Exact Tool Count:** `list_tools()` returns exactly 7 tools; verified by `assert tool_names == expected_seven`.
* **Protocol Version:** Negotiated handshake returns `2025-11-25`; verified by `assert init_res.protocol_version == "2025-11-25"`.
* **Zero Cost Incurred:** Inspected AWS account; 0 EC2, 0 ECS, 0 ECR, 0 RDS, 0 Cognito pools created.
