"""
OAuth 2.1 & Protected Resource Metadata Endpoints (M9).
Implements RFC 8414 and RFC 9728 for Alexa+ and AgentCore integration.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.config import settings

router = APIRouter(prefix="/.well-known", tags=["oauth-metadata"])


@router.get("/oauth-protected-resource")
async def get_protected_resource_metadata(request: Request) -> dict[str, Any]:
    """
    RFC 9728 Protected Resource Metadata endpoint.
    Used by Alexa+ and MCP clients to discover authorization servers and scopes.
    """
    host = request.headers.get("host", f"localhost:{settings.port}")
    scheme = (
        "https" if request.url.scheme == "https" or "amazonaws.com" in host else "http"
    )
    base_url = f"{scheme}://{host}"

    return {
        "resource": f"{base_url}/mcp",
        "authorization_servers": [settings.auth_issuer],
        "scopes_supported": [
            "mcp:read",
            "mcp:write",
            "threadback:read",
            "threadback:write",
            "openid",
            "email",
            "profile",
        ],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}/docs",
    }


@router.get("/oauth-authorization-server")
async def get_authorization_server_metadata(request: Request) -> dict[str, Any]:
    """
    RFC 8414 OAuth 2.0 Authorization Server Metadata endpoint.
    Advertises PKCE S256 and OAuth 2.1 authorization code flow for Alexa+.
    """
    issuer = settings.auth_issuer

    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth2/authorize",
        "token_endpoint": f"{issuer}/oauth2/token",
        "jwks_uri": settings.auth_jwks_uri or f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "refresh_token",
            "client_credentials",
        ],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_basic",
            "client_secret_post",
        ],
        "scopes_supported": [
            "mcp:read",
            "mcp:write",
            "openid",
            "email",
            "profile",
            "threadback:read",
            "threadback:write",
        ],
    }
