"""
ASGI Authentication Middleware for Threadback Remote MCP & AgentCore (M9).

Authentication Responsibility Boundary:
- Production AgentCore Runtime: AWS AgentCore manages CUSTOM_JWT authentication
  at the runtime gateway layer using Amazon Cognito discovery.
- Threadback Local Middleware: Provides local authenticated development,
  testing, and defense-in-depth token validation.
- Alexa+ Discovery Flow: Returns 401 Unauthorized WITHOUT WWW-Authenticate
  per official Alexa+ MCP account-linking specifications.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.security.jwt_validator import AuthenticationError, JWTValidator


class MCPAuthenticationMiddleware:
    """
    ASGI middleware enforcing Bearer token authentication on the /mcp endpoint
    for local testing and defense-in-depth.
    Complies with Alexa+ requirement of 401 WITHOUT WWW-Authenticate for discovery.
    """

    def __init__(
        self,
        app: ASGIApp,
        validator: JWTValidator | None = None,
        auth_enabled: bool | None = None,
        include_www_authenticate: bool = False,
    ) -> None:
        self.app = app
        self.validator = validator or JWTValidator()
        self.auth_enabled = (
            auth_enabled if auth_enabled is not None else settings.auth_enabled
        )
        self.include_www_authenticate = include_www_authenticate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Always permit metadata and health endpoints without authentication
        if (
            path.startswith("/.well-known")
            or path == "/health"
            or path.startswith("/docs")
            or path == "/openapi.json"
        ):
            await self.app(scope, receive, send)
            return

        # If auth is disabled (e.g. local dev / M0-M8 baseline), pass through
        if not self.auth_enabled:
            await self.app(scope, receive, send)
            return

        # Only protect /mcp and /api endpoints if auth is enabled
        if not (path.startswith("/mcp") or path.startswith("/api")):
            await self.app(scope, receive, send)
            return

        # Section 8 Constraint: Strictly forbid tokens in query parameters
        query_string = scope.get("query_string", b"").decode("latin-1")
        if query_string:
            params = parse_qs(query_string)
            if "token" in params or "access_token" in params or "bearer" in params:
                await self._send_json_error(
                    send,
                    status_code=401,
                    error="invalid_request",
                    error_description="Bearer tokens must not be passed in query parameters.",
                )
                return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth_header_bytes = headers.get(b"authorization")

        if not auth_header_bytes:
            await self._send_unauthorized(
                send,
                error="unauthorized",
                error_description="Authorization header missing. Bearer token required.",
            )
            return

        try:
            auth_header = auth_header_bytes.decode("utf-8")
        except UnicodeDecodeError:
            await self._send_unauthorized(
                send,
                error="invalid_token",
                error_description="Authorization header is not valid UTF-8.",
            )
            return

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            await self._send_unauthorized(
                send,
                error="invalid_request",
                error_description="Authorization header format must be 'Bearer <token>'.",
            )
            return

        token = parts[1]

        # Validate token
        try:
            payload = self.validator.validate_token(token)
            # Store validated user payload in scope
            scope["state"] = scope.get("state", {})
            scope["state"]["user"] = payload
            scope["state"]["auth_claims"] = payload.raw_claims
            await self.app(scope, receive, send)
        except AuthenticationError as exc:
            await self._send_unauthorized(
                send,
                error="invalid_token",
                error_description=exc.message,
            )

    async def _send_unauthorized(
        self,
        send: Send,
        error: str,
        error_description: str,
    ) -> None:
        body = json.dumps(
            {
                "error": error,
                "error_description": error_description,
                "resource": settings.threadback_mcp_url,
            }
        ).encode("utf-8")

        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        # Alexa+ documentation states unauthenticated MCP requests should return
        # 401 Unauthorized WITHOUT WWW-Authenticate in the MCP account-linking flow.
        if self.include_www_authenticate:
            www_authenticate = (
                f'Bearer error="{error}", error_description="{error_description}", '
                f'resource="{settings.threadback_mcp_url}"'
            )
            headers.append((b"www-authenticate", www_authenticate.encode("latin-1")))

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    async def _send_json_error(
        self,
        send: Send,
        status_code: int,
        error: str,
        error_description: str,
    ) -> None:
        body = json.dumps(
            {
                "error": error,
                "error_description": error_description,
            }
        ).encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
