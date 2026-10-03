# Threadback — M9 Authentication & OAuth 2.1 Specification

## 1. Overview

Milestone M9 specifies the authentication architecture for Threadback's Model Context Protocol (MCP) endpoint (`/mcp`), aligning with AWS Bedrock AgentCore's `CUSTOM_JWT` runtime contract and Amazon Alexa+'s official MCP account linking specifications.

---

## 2. Status Classification

```text
M9 — CONDITIONAL

Implementation/readiness: substantially complete
AgentCore cloud deployment: BLOCKED by IAM
Alexa+ actual onboarding: BLOCKED by partner/toolkit access
```

| Category | Component / Feature | Details |
| :--- | :--- | :--- |
| **Implemented** | OAuth 2.1 Bearer Enforcement | `MCPAuthenticationMiddleware` intercepts `/mcp` and validates `Authorization: Bearer <token>`. |
| **Implemented** | Query Param Token Rejection | Strictly blocks tokens in query parameters (returns HTTP 401 `invalid_request`). |
| **Implemented** | JWT Validation Engine | `JWTValidator` handles RS256/JWKS (Amazon Cognito) and HS256 (local testing). |
| **Implemented** | Protected Resource Metadata | RFC 9728 endpoint at `/.well-known/oauth-protected-resource`. |
| **Implemented** | Authorization Server Metadata | RFC 8414 endpoint at `/.well-known/oauth-authorization-server` advertising PKCE `S256`. |
| **Implemented** | Public Health Endpoint | `GET /health` remains accessible without authentication for cloud probes. |
| **Prepared** | Cognito User Pool Configuration | Issuer, App Client ID, and JWKS URI parameterized in configuration and environment variables. |
| **Blocked** | Live Cognito Pool Creation | Active IAM role has `ViewOnlyAccess`; provisioning new user pools requires admin permissions. |
| **Not Implemented** | Unsupported Auth Schemes | DCR, CIMD, OIDC userinfo, and step-up auth are intentionally excluded per Alexa+ guidance. |

---

## 3. Official Integration Constraints & Guarantees

### 3.1 Strict Prohibition of Query Parameter Tokens (Section 8)
Alexa+ and RFC 6750 explicitly restrict bearer tokens from URI query strings to prevent access token leakage in access logs, proxies, and browser histories.

Any request to `/mcp` containing query parameters such as `?access_token=...`, `?token=...`, or `?bearer=...` is immediately intercepted and rejected with:
```json
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "error": "invalid_request",
  "error_description": "Bearer tokens must not be passed in query parameters."
}
```

### 3.2 Required Header Format & WWW-Authenticate Behavior
Authenticated MCP calls must provide:
```http
Authorization: Bearer <jwt-token>
```

#### Alexa+ WWW-Authenticate Requirement
Current Alexa+ documentation specifies that unauthenticated MCP requests should return:
```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "error": "unauthorized",
  "error_description": "Authorization header missing. Bearer token required.",
  "resource": "http://localhost:8000/mcp"
}
```
**WITHOUT** a `WWW-Authenticate` header in the Alexa+ discovery flow.

`MCPAuthenticationMiddleware` defaults to omitting `WWW-Authenticate` to adhere to the official Alexa+ discovery flow. For general HTTP clients that require `WWW-Authenticate`, `include_www_authenticate=True` can be enabled.

#### AgentCore OAuth Runtime Boundary Notice
AWS Bedrock AgentCore may generate its own OAuth authentication challenge at the cloud runtime boundary. We do not claim that the Threadback application container controls or overrides the AgentCore gateway's production authentication response.

### 3.3 Alexa+ Two-Tier Authentication Model
Amazon Alexa+ defines two distinct authentication tiers for MCP add-ons:

* **Tier 1: Service-Level (`client_credentials`)**
  * **Purpose:** Service-to-service authentication, MCP tool discovery, and non-user-specific operations.
  * **Flow:** Direct client credentials exchange against Amazon Cognito / OAuth server.
* **Tier 2: User-Level (`authorization_code` + PKCE S256)**
  * **Purpose:** User-specific intent recovery, personal context reconstruction, and user consent for action preparation.
  * **Flow:** OAuth 2.1 authorization code grant with PKCE (`S256`), returning a scoped user access token.

Threadback does NOT implement an unnecessary custom OAuth authorization server. Instead, it relies on standard Amazon Cognito / OpenID configuration. Because Alexa+ Toolkit access is currently unavailable and live Cognito provisioning is blocked by IAM permissions, this production configuration is documented and prepared as pending.

---

## 4. Production vs Local Authentication Responsibility

We distinguish the production cloud runtime boundary from the local test harness:

### Production AgentCore Architecture
In production on Amazon Bedrock AgentCore Runtime, AgentCore manages `CUSTOM_JWT` validation directly at the runtime boundary:
```text
Client / Alexa+
      ↓
Bearer JWT
      ↓
AgentCore CUSTOM_JWT Gateway (Cognito JWKS)
      ↓ (Authorized request dispatched to container)
Threadback MCP Container (/mcp)
      ↓
Deterministic Core
```
AgentCore validates the token against Cognito's JWKS and injects verified claims before dispatching requests to the container, eliminating redundant token validation in production.

### Threadback Local Middleware
`MCPAuthenticationMiddleware` operates in local development, CI test suites, and defense-in-depth scenarios, enforcing token validation when AgentCore's outer gateway is not present.

---

## 5. Metadata Endpoints

### 5.1 Protected Resource Metadata (RFC 9728)
`GET /.well-known/oauth-protected-resource`

Allows clients (including Alexa+) to discover the resource URI, supported authorization servers, and required scopes:

```json
{
  "resource": "https://<host>/mcp",
  "authorization_servers": [
    "https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>"
  ],
  "scopes_supported": [
    "mcp:read",
    "mcp:write",
    "threadback:read",
    "threadback:write",
    "openid",
    "email",
    "profile"
  ],
  "bearer_methods_supported": [
    "header"
  ],
  "resource_documentation": "https://<host>/docs"
}
```

### 5.2 Authorization Server Metadata (RFC 8414)
`GET /.well-known/oauth-authorization-server`

Advertises OAuth 2.1 authorization code flow with PKCE `S256`:

```json
{
  "issuer": "https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>",
  "authorization_endpoint": "https://<domain>/oauth2/authorize",
  "token_endpoint": "https://<domain>/oauth2/token",
  "jwks_uri": "https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>/.well-known/jwks.json",
  "response_types_supported": [
    "code"
  ],
  "code_challenge_methods_supported": [
    "S256"
  ],
  "scopes_supported": [
    "mcp:read",
    "mcp:write",
    "openid",
    "email",
    "profile",
    "threadback:read",
    "threadback:write"
  ]
}
```


---

## 5. Security Invariants
* The secret key is never committed to version control.
* In production (`APP_ENV=production`), `AUTH_ENABLED` defaults to `true`.
* For local development and testing, `AUTH_ENABLED=false` or test secrets are used.
