"""
Threadback FastAPI application entry point.

M1 — health endpoint.
M2 — MCP server at /mcp (Streamable HTTP, protocol 2025-11-25).

MCP Routing Architecture
------------------------
The MCP Starlette sub-app is mounted via a custom ASGI middleware wrapper
rather than FastAPI's app.mount(). This is required because:

  app.mount("/mcp", mcp_sub_app)

uses Starlette's Mount, which strips the /mcp prefix and passes an empty
path "" to the sub-app. The sub-app's route at "/" does not match "", so
Starlette issues a 307 redirect to /mcp/. The MCP SDK client (httpx2) does
not follow redirects by default, so the protocol handshake at /mcp would
fail without custom handling.

The MCPPathAdapter below intercepts all requests whose path begins with
/mcp, rewrites the ASGI scope path to "/" (so the sub-app route at "/"
matches), and dispatches directly to the MCP ASGI app. All other requests
pass through to FastAPI's normal routing.

MCP Lifespan
------------
The MCP StreamableHTTPSessionManager requires an async task group to be
active before handling requests. This is initialized via FastAPI's lifespan
context manager per the official MCP Python SDK documentation.

Future milestones will register additional routers as they are built.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.mcp.server import build_mcp_app, mcp_server
from app.routers import agent, copilot, health, oauth_metadata, proactive
from app.security import MCPAuthenticationMiddleware

# ---------------------------------------------------------------------------
# MCP ASGI app
#
# build_mcp_app() must be called before lifespan so that
# mcp_server.session_manager is available for the lifespan to run.
# ---------------------------------------------------------------------------

_mcp_asgi_app: Starlette = build_mcp_app()


# ---------------------------------------------------------------------------
# MCPPathAdapter — custom ASGI wrapper
#
# Intercepts requests at /mcp (and /mcp/ for resilience) and dispatches
# them to the MCP sub-app with the path rewritten to "/" so the sub-app's
# internal route at "/" matches directly — no 307 redirects.
# ---------------------------------------------------------------------------


class MCPPathAdapter:
    """
    ASGI middleware that routes /mcp to the MCP Starlette sub-app.

    Wraps a FastAPI application and checks every incoming request's path:
      - If the path is /mcp or /mcp/ → dispatch to the MCP sub-app with
        the path rewritten to "/" (and root_path updated accordingly).
      - Otherwise → pass through to the inner FastAPI app unchanged.

    This avoids Starlette's Mount trailing-slash redirect behavior which
    would cause a 307 on POST /mcp, breaking MCP SDK clients.
    """

    def __init__(self, fastapi_app: ASGIApp, mcp_app: ASGIApp) -> None:
        self._fastapi_app = fastapi_app
        self._mcp_app = mcp_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            # Match /mcp exactly or /mcp/ (with trailing slash)
            if path == "/mcp" or path == "/mcp/":
                # Rewrite scope so the MCP sub-app sees path="/"
                mcp_scope: dict[str, Any] = dict(scope)
                mcp_scope["path"] = "/"
                mcp_scope["raw_path"] = b"/"
                root_path = scope.get("root_path", "")
                mcp_scope["root_path"] = root_path + "/mcp"
                await self._mcp_app(mcp_scope, receive, send)
                return

        # All other requests (including lifespan events) go to FastAPI
        await self._fastapi_app(scope, receive, send)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown for the FastAPI application."""
    async with mcp_server.session_manager.run():
        yield


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

_fastapi_app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Threadback — agentic personal-context system. "
        "Discovers unfinished intentions and helps close open loops. "
        "MCP server available at /mcp (Streamable HTTP, protocol 2025-11-25)."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

_fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
#
# M1: health
# Future milestones will register:
#   M5 — MCP thread tools (inside the MCP server, not as REST routes)
#   M7 — /actions (if needed as REST complement)
#   M9 — /aws (if needed)
# ---------------------------------------------------------------------------

_fastapi_app.include_router(health.router)
_fastapi_app.include_router(agent.router)
_fastapi_app.include_router(oauth_metadata.router)
_fastapi_app.include_router(proactive.router)
_fastapi_app.include_router(copilot.router)

# ---------------------------------------------------------------------------
# ASGI application entry point
#
# The MCPPathAdapter wraps FastAPI and intercepts /mcp → MCP sub-app.
# MCPAuthenticationMiddleware guards /mcp and /api with OAuth 2.1 Bearer
# token validation when auth_enabled=True.
# This is the object that uvicorn binds to.
# FastAPI's lifespan (and thus MCP lifespan) is managed within _fastapi_app.
# ---------------------------------------------------------------------------

_mcp_adapter = MCPPathAdapter(_fastapi_app, _mcp_asgi_app)
app = MCPAuthenticationMiddleware(_mcp_adapter)
