"""
M9 Authentication Tests for Threadback Remote MCP & AgentCore Integration.

Tests:
1. RFC 9728 Protected Resource Metadata endpoint (/.well-known/oauth-protected-resource)
2. RFC 8414 Authorization Server Metadata endpoint (/.well-known/oauth-authorization-server)
3. Health endpoint remains publicly accessible without auth
4. Unauthenticated requests to /mcp with auth_enabled=True rejected with HTTP 401
   (verifying Alexa+ requirement: 401 WITHOUT WWW-Authenticate in discovery flow)
5. Bearer tokens in query parameters are strictly forbidden (Section 8 constraint)
6. Malformed Authorization headers rejected with HTTP 401
7. Invalid JWT signatures rejected with HTTP 401
8. Expired JWT tokens rejected with HTTP 401
9. Valid JWT tokens accepted and decoded
10. Issuer and audience validation enforced
"""

from __future__ import annotations

import httpx
import pytest
from app.main import app
from app.security.jwt_validator import (
    AuthenticationError,
    JWTValidator,
    create_test_token,
)
from app.security.middleware import MCPAuthenticationMiddleware


@pytest.mark.asyncio
async def test_oauth_protected_resource_metadata() -> None:
    """Test RFC 9728 OAuth Protected Resource Metadata endpoint."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        data = response.json()

        assert "resource" in data
        assert data["resource"].endswith("/mcp")
        assert "authorization_servers" in data
        assert isinstance(data["authorization_servers"], list)
        assert len(data["authorization_servers"]) > 0
        assert "scopes_supported" in data
        assert "mcp:read" in data["scopes_supported"]
        assert "mcp:write" in data["scopes_supported"]
        assert "bearer_methods_supported" in data
        assert "header" in data["bearer_methods_supported"]
        assert "query" not in data["bearer_methods_supported"]


@pytest.mark.asyncio
async def test_oauth_authorization_server_metadata() -> None:
    """Test RFC 8414 OAuth Authorization Server Metadata endpoint."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()

        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "response_types_supported" in data
        assert "code" in data["response_types_supported"]
        assert "code_challenge_methods_supported" in data
        # Section 8 mandate: code_challenge_methods_supported must include S256
        assert "S256" in data["code_challenge_methods_supported"]
        assert "token_endpoint_auth_methods_supported" in data
        assert "none" in data["token_endpoint_auth_methods_supported"]


@pytest.mark.asyncio
async def test_health_endpoint_public_without_auth() -> None:
    """Verify that health check endpoint is public even when auth is enabled."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_unauthenticated_mcp_request_returns_401() -> None:
    """
    Unauthenticated request to /mcp must return HTTP 401.
    Per Alexa+ MCP discovery flow specification, 401 must NOT include WWW-Authenticate.
    """
    # Create middleware instance with auth_enabled=True explicitly
    validator = JWTValidator(secret_key="test-secret-key-12345678901234567890")
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True, include_www_authenticate=False
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1}
        )
        assert response.status_code == 401
        # Official Alexa+ spec: WWW-Authenticate must NOT be present
        assert "www-authenticate" not in response.headers
        data = response.json()
        assert data["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_unauthenticated_mcp_request_with_www_authenticate_option() -> None:
    """
    Verify that if include_www_authenticate=True is enabled for general HTTP clients,
    the WWW-Authenticate header is included.
    """
    validator = JWTValidator(secret_key="test-secret-key-12345678901234567890")
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True, include_www_authenticate=True
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1}
        )
        assert response.status_code == 401
        assert "www-authenticate" in response.headers
        assert "Bearer" in response.headers["www-authenticate"]
        data = response.json()
        assert data["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_token_in_query_parameters_strictly_rejected() -> None:
    """
    Section 8 Rule: 'Never put bearer tokens into query parameters.'
    Middleware must reject tokens in query string with HTTP 401 invalid_request.
    """
    validator = JWTValidator(secret_key="test-secret-key-12345678901234567890")
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        # Pass token in query param
        response = await ac.post(
            "/mcp?access_token=sample.token.here",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["error"] == "invalid_request"
        assert "query parameters" in data["error_description"]


@pytest.mark.asyncio
async def test_malformed_auth_header_rejected() -> None:
    """Verify malformed authorization headers are rejected."""
    validator = JWTValidator(secret_key="test-secret-key-12345678901234567890")
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        # Case 1: Missing Bearer prefix
        res1 = await ac.post(
            "/mcp",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert res1.status_code == 401
        assert res1.json()["error"] == "invalid_request"

        # Case 2: Only 'Bearer' without token
        res2 = await ac.post(
            "/mcp",
            headers={"Authorization": "Bearer"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert res2.status_code == 401
        assert res2.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_invalid_signature_rejected() -> None:
    """Verify tokens signed with wrong secret are rejected."""
    validator = JWTValidator(secret_key="correct-key-12345678901234567890")
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True
    )

    # Generate token with wrong secret
    bad_token = create_test_token(
        sub="user-1",
        secret_key="wrong-key-12345678901234567890123",
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.post(
            "/mcp",
            headers={"Authorization": f"Bearer {bad_token}"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    """Verify expired tokens are rejected."""
    secret = "test-secret-key-12345678901234567890"
    validator = JWTValidator(secret_key=secret)
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True
    )

    # Generate expired token
    expired_token = create_test_token(
        sub="user-1",
        secret_key=secret,
        exp_minutes=-60,  # 1 hour in the past
    )

    transport = httpx.ASGITransport(app=secured_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        response = await ac.post(
            "/mcp",
            headers={"Authorization": f"Bearer {expired_token}"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"
        assert "expired" in response.json()["error_description"].lower()


@pytest.mark.asyncio
async def test_issuer_and_audience_validation() -> None:
    """Verify issuer and audience checks in JWTValidator."""
    secret = "test-secret-key-12345678901234567890"
    validator = JWTValidator(
        secret_key=secret,
        issuer="https://auth.threadback.ai",
        audience="threadback-mcp-agentcore",
    )

    # Valid token with matching issuer and audience
    valid_token = create_test_token(
        sub="agentcore-caller",
        secret_key=secret,
        issuer="https://auth.threadback.ai",
        audience="threadback-mcp-agentcore",
    )
    payload = validator.validate_token(valid_token)
    assert payload.sub == "agentcore-caller"

    # Mismatched audience
    bad_aud_token = create_test_token(
        sub="agentcore-caller",
        secret_key=secret,
        issuer="https://auth.threadback.ai",
        audience="wrong-audience",
    )
    with pytest.raises(AuthenticationError, match="audience"):
        validator.validate_token(bad_aud_token)

    # Mismatched issuer
    bad_iss_token = create_test_token(
        sub="agentcore-caller",
        secret_key=secret,
        issuer="https://evil.attacker.com",
        audience="threadback-mcp-agentcore",
    )
    with pytest.raises(AuthenticationError, match="issuer"):
        validator.validate_token(bad_iss_token)


@pytest.mark.asyncio
async def test_valid_token_allows_mcp_access() -> None:
    """Verify valid token passes authentication middleware into the application."""
    from app.mcp.server import mcp_server

    secret = "test-secret-key-12345678901234567890"
    validator = JWTValidator(secret_key=secret)
    secured_app = MCPAuthenticationMiddleware(
        app, validator=validator, auth_enabled=True
    )

    token = create_test_token(sub="alexa-plus-user", secret_key=secret)

    async with mcp_server.session_manager.run():
        transport = httpx.ASGITransport(app=secured_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "text/event-stream",
                },
            )
            # Should NOT return 401
            assert response.status_code != 401
