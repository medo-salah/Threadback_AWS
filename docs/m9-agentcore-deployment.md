# Threadback — M9 Amazon Bedrock AgentCore Runtime Deployment

## 1. Overview & Objective

Milestone M9 adapts Threadback's deterministic Model Context Protocol (MCP) server for deployment to Amazon Bedrock AgentCore Runtime.

This adaptation maintains 100% behavioral parity with the deterministic domain layer validated in Milestones M3–M7, without modifying core business logic, without introducing databases/Redis/Kafka, and without introducing arbitrary external APIs.

---

## 2. Status Classification

```text
M9 — CONDITIONAL

Implementation/readiness: substantially complete
AgentCore cloud deployment: BLOCKED by IAM
Alexa+ actual onboarding: BLOCKED by partner/toolkit access
```

| Capability / Phase | Status | Details |
| :--- | :---: | :--- |
| **Streamable HTTP `/mcp`** | **Complete** | Streamable HTTP endpoint binding `0.0.0.0:${PORT:-8000}` with active protocol version `2025-11-25`. |
| **Stateless MCP Mode** | **Complete** | Session-independent Streamable HTTP transport configured via `MCP_STATELESS=true`. |
| **AgentCore ARM64 Compatibility** | **Complete** | Container pinned to `linux/arm64` via `Dockerfile.agentcore` (`FROM --platform=linux/arm64 python:3.10-slim`). |
| **Intended Runtime Manifest** | **Complete** | Structured `agentcore/runtime-config.json` documenting intended transport, ARM64 architecture, and auth. |
| **Deployment Script** | **Complete** | `agentcore/deploy.sh` incorporating ARM64 architecture verification check and ECR commands. |
| **Local Authenticated MCP** | **Complete** | Tested and verified locally with PyJWT and OAuth 2.1 middleware. |
| **AgentCore Cloud Deployment** | **Blocked — IAM** | Live cloud provisioning blocked: active AWS credential `arn:aws:iam::863516093768:user/claude-agent` has `ViewOnlyAccess`. |
| **AgentCore Remote Verification** | **Not performed** | Cloud verification not performed because cloud deployment is blocked. |
| **Alexa+ Readiness** | **Prepared** | Add-on manifest and conversational experience mapping prepared against published requirements. |
| **Alexa+ Actual Onboarding** | **Blocked — Access** | Blocked due to Amazon restricting the Alexa+ MCP Toolkit to select preview partners. |

---

## 3. Production vs Local Authentication Architecture

In production on Amazon Bedrock AgentCore Runtime, AgentCore itself provides the outer authentication gateway using `CUSTOM_JWT` mode:

```text
Client / Alexa+
      ↓ (HTTPS + OAuth 2.1)
Bearer JWT
      ↓
AgentCore Gateway (CUSTOM_JWT / Cognito Discovery)
      ↓ (Authenticated request forwarding)
Threadback MCP Container (/mcp)
      ↓
Deterministic Domain Core (M3–M7)
```

The Threadback `MCPAuthenticationMiddleware` serves for local testing, CI validation, and optional defense-in-depth token validation. For Alexa+ MCP discovery flow, unauthenticated requests return `401 Unauthorized` without `WWW-Authenticate`.

---

## 4. Container Specification (`Dockerfile.agentcore`)

* **Base Image:** `python:3.10-slim` explicitly targeting `linux/arm64` (`FROM --platform=linux/arm64 python:3.10-slim`).
* **ARM64 Architecture Requirement:**
  Amazon Bedrock AgentCore's MCP container runtime requires `linux/arm64`. `agentcore/deploy.sh` contains an explicit verification step checking `docker inspect --format '{{.Architecture}}'`.
* **Security Constraints:**
  * Runs as dedicated non-root user `threadback` (`uid/gid` created during build).
  * Read-only runtime permissions outside application directory.
  * No root daemon or elevated capabilities required.
* **Network & Port Binding:**
  * Binds to `0.0.0.0:${PORT:-8000}`.
  * Configurable via standard `PORT` environment variable required by container runtimes.
* **Health Check Probe:**
  * Probe endpoint: `GET /health`
  * Interval: 30s, Timeout: 5s, Retries: 3.

---

## 5. AgentCore Deployment Manifest (`agentcore/runtime-config.json`)

Threadback provides `agentcore/runtime-config.json` as a deployment manifest describing the intended AgentCore configuration.

The official AWS CLI workflow utilizes:
```bash
agentcore create
agentcore add agent --protocol MCP
agentcore deploy
```
And `agentcore/runtime-config.json` serves as Threadback's declaratively documented manifest:

```json
{
  "name": "threadback-mcp-server",
  "version": "1.0.0",
  "runtime": {
    "type": "CONTAINER",
    "architecture": "ARM64",
    "port": 8000,
    "healthCheckPath": "/health",
    "environment": {
      "HOST": "0.0.0.0",
      "PORT": "8000",
      "APP_ENV": "production",
      "AUTH_ENABLED": "true",
      "MCP_STATELESS": "true"
    }
  },
  "mcp": {
    "transport": "STREAMABLE_HTTP",
    "path": "/mcp",
    "protocolVersion": "2025-11-25",
    "stateless": true
  },
  "security": {
    "authMode": "CUSTOM_JWT"
  }
}
```

---

## 6. Execution & Deployment Steps

To deploy to Amazon Bedrock AgentCore Runtime when write permissions are granted:

```bash
# 1. Export deployment environment variables
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="<your-aws-account-id>"
export ECR_REPO_NAME="threadback-mcp"
export AGENTCORE_RUNTIME_NAME="threadback-mcp-runtime"

# 2. Run the deployment script
./agentcore/deploy.sh
```
