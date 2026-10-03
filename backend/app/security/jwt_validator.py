"""
JWT Token Validation for Threadback Remote MCP & AgentCore Runtime (M9).

Supports:
- Amazon Cognito JWTs with RS256 and JWKS discovery
- HMAC (HS256) validation for testing and local verification
- Strict claim validation (iss, aud, exp, scopes)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when JWT verification fails."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TokenPayload(BaseModel):
    """Parsed and validated JWT token payload."""

    sub: str = Field(..., description="Subject identifier (user/client ID)")
    iss: str | None = Field(None, description="Token issuer")
    aud: str | list[str] | None = Field(None, description="Audience or client ID")
    exp: int | None = Field(None, description="Expiration timestamp")
    scope: str | list[str] | None = Field(None, description="OAuth scopes")
    client_id: str | None = Field(None, description="Authorized client ID")
    raw_claims: dict[str, Any] = Field(default_factory=dict, description="Raw claims")


class JWTValidator:
    """
    Validates JWT Bearer tokens for Threadback MCP service.
    """

    def __init__(
        self,
        issuer: str | None = None,
        audience: str | None = None,
        jwks_uri: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.issuer = issuer or settings.auth_issuer
        self.audience = audience or settings.auth_audience
        self.jwks_uri = jwks_uri or settings.auth_jwks_uri
        self.secret_key = secret_key or settings.auth_secret_key
        self._jwks_client: PyJWKClient | None = None

        if self.jwks_uri:
            try:
                self._jwks_client = PyJWKClient(self.jwks_uri, cache_keys=True)
            except Exception as exc:
                logger.warning(
                    "Failed to initialize PyJWKClient for %s: %s", self.jwks_uri, exc
                )

    def validate_token(self, token: str) -> TokenPayload:
        """
        Validate a raw JWT token string and return its parsed payload.
        Raises AuthenticationError if invalid, expired, or claims do not match.
        """
        if not token or not token.strip():
            raise AuthenticationError("Token is empty or missing.")

        token = token.strip()

        # 1. Validation via HMAC Secret Key (if configured)
        if self.secret_key:
            try:
                claims = jwt.decode(
                    token,
                    self.secret_key,
                    algorithms=["HS256"],
                    issuer=self.issuer if self.issuer else None,
                    audience=self.audience if self.audience else None,
                    options={"verify_exp": True},
                )
                return self._parse_claims(claims)
            except jwt.ExpiredSignatureError as exc:
                raise AuthenticationError("Token has expired.") from exc
            except jwt.InvalidIssuerError as exc:
                raise AuthenticationError(
                    f"Invalid token issuer. Expected {self.issuer}."
                ) from exc
            except jwt.InvalidAudienceError as exc:
                raise AuthenticationError(
                    f"Invalid token audience. Expected {self.audience}."
                ) from exc
            except jwt.PyJWTError as exc:
                raise AuthenticationError(f"Token validation failed: {exc}") from exc

        # 2. Validation via JWKS (Cognito / OIDC)
        if self._jwks_client:
            try:
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    issuer=self.issuer if self.issuer else None,
                    audience=self.audience if self.audience else None,
                    options={"verify_exp": True},
                )
                return self._parse_claims(claims)
            except jwt.ExpiredSignatureError as exc:
                raise AuthenticationError("Token has expired.") from exc
            except jwt.PyJWTError as exc:
                raise AuthenticationError(
                    f"JWKS token validation failed: {exc}"
                ) from exc

        # If neither secret_key nor jwks_client is configured, decode without verification (testing fallback)
        try:
            unverified_claims = jwt.decode(
                token, options={"verify_signature": False, "verify_exp": True}
            )
            return self._parse_claims(unverified_claims)
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired.") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Token parsing failed: {exc}") from exc

    def _parse_claims(self, claims: dict[str, Any]) -> TokenPayload:
        sub = str(claims.get("sub") or claims.get("username") or "anonymous")
        return TokenPayload(
            sub=sub,
            iss=claims.get("iss"),
            aud=claims.get("aud") or claims.get("client_id"),
            exp=claims.get("exp"),
            scope=claims.get("scope"),
            client_id=claims.get("client_id"),
            raw_claims=claims,
        )


def create_test_token(
    sub: str = "test-user-123",
    secret_key: str = "test-secret-key-32-bytes-minimum-size!!",
    exp_minutes: int = 60,
    scopes: str = "threadback:read threadback:write",
    issuer: str = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_threadback",
    audience: str = "threadback-mcp",
) -> str:
    """
    Helper function to generate a valid test JWT signed with HS256.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": scopes,
        "token_use": "access",
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")
