# Threadback — Architecture Notes
# M2: MCP Server Foundation added
# =============================================================================

## Current Architecture (M2)

```
┌────────────────────────────────────────────┐
│               Future Client                 │
│          Alexa+ / MCP Inspector             │
│         (M8 simulation / M9 Alexa+)         │
└──────────────────┬─────────────────────────┘
                   │
                   │ MCP / Streamable HTTP
                   │ Protocol: 2025-11-25
                   ▼
┌────────────────────────────────────────────┐
│           Threadback Backend               │
│              FastAPI + uvicorn             │
│                                            │
│   ┌─────────────┐   ┌──────────────────┐  │
│   │  GET /health │   │  POST /mcp/mcp   │  │
│   │  (M1)        │   │  Streamable HTTP │  │
│   └─────────────┘   │  MCPServer 2.2.0 │  │
│                      │  (M2)            │  │
│                      └────────┬─────────┘  │
│                               │            │
│                      ┌────────▼─────────┐  │
│                      │  Empty Tool Layer │  │
│                      │  (M2 Foundation)  │  │
│                      └──────────────────┘  │
└────────────────────────────────────────────┘

              Future phases:

┌────────────────────────────────────────────┐
│         Thread Domain + Database           │  ← M3
│   IntentThread · Evidence · Dependency     │
│   PostgreSQL + optional pgvector           │
└──────────────────┬─────────────────────────┘
                   │
┌──────────────────▼─────────────────────────┐
│         Intent & Evidence Engine           │  ← M4
│   Thread Discovery · Confidence Scoring    │
└──────────────────┬─────────────────────────┘
                   │
┌──────────────────▼─────────────────────────┐
│            MCP Thread Tools                │  ← M5
│   discover_unfinished_threads              │
│   get_thread_context                       │
│   analyze_thread                           │
│   find_thread_blockers                     │
│   suggest_next_action                      │
│   prepare_action                           │
│   execute_action                           │
│   verify_thread_completion                 │
└──────────────────┬─────────────────────────┘
                   │
┌──────────────────▼─────────────────────────┐
│          Agent Orchestration               │  ← M6
│   ModelProvider abstraction                │
│   LocalProvider | BedrockProvider          │
└────────────────────────────────────────────┘
```

---

## Key Architecture Decisions

### MCP Transport (M2)
- **Streamable HTTP** at `/mcp/mcp` (the sub-path is `/mcp` within the mounted Starlette app)
- Protocol version: **2025-11-25** (Streamable HTTP, Alexa+ parity)
- Legacy SSE-only transport is excluded as primary

### MCP SDK Version (M2)
- Using **MCP Python SDK 2.2.0** (MCP 2.x, where FastMCP was renamed to MCPServer)
- `MCPServer` from `mcp.server.mcpserver`
- No custom JSON-RPC implementation

### Lifespan Management (M2)
The MCP `StreamableHTTPSessionManager` requires an async task group.
FastAPI's `lifespan` context manager calls `session_manager.run()` on startup.
This is the pattern recommended by the official SDK docs.

### httpx2 Decision (M2 verified)
`httpx2` is maintained by Tom Christie (original httpx author) + Pydantic team.
Source: `github.com/pydantic/httpx2`. It is the legitimate httpx successor.
MCP SDK 2.2.0 itself requires `httpx2>=2.5.0`. This is correct and appropriate.
Standard `httpx` remains installed as a transitive dependency.

### Model Provider Abstraction
The agent layer will sit behind a `ModelProvider` protocol.
No Bedrock imports are allowed in core business logic.

### Action Safety
All consequential actions require `requires_confirmation = True`
before `execute_action` fires.

### Evidence Traceability
Every inference surfaced to the user must link to at least one
`Evidence` record with an explicit confidence score.

---

## MCP Tool Groups (M5)

```
READ   → discover_unfinished_threads
         get_thread_context
         analyze_thread
         find_thread_blockers

PLAN   → suggest_next_action
         prepare_action

WRITE  → execute_action
         verify_thread_completion
```

---

## Future Dependency Points

| Milestone | Component to Add |
|-----------|-----------------|
| M3        | PostgreSQL, SQLAlchemy/SQLModel |
| M4        | Evidence engine, confidence scoring |
| M5        | 8 MCP thread tools (registered in `app/mcp/server.py`) |
| M6        | LLM provider abstraction |
| M8        | React conversational UI |
| M9        | AWS Bedrock, Strands (optional) |

---

## File Structure (M2)

```text
backend/
└── app/
    ├── __init__.py
    ├── config.py            ← Centralized settings
    ├── main.py              ← FastAPI + lifespan + MCP mount
    ├── routers/
    │   ├── __init__.py
    │   └── health.py        ← GET /health
    └── mcp/
        ├── __init__.py
        └── server.py        ← MCPServer instance + build_mcp_app()
```
