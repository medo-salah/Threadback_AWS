"""
Tests for the health endpoint.

M1 requirement: GET /health must return HTTP 200 with the expected response body.
"""

from __future__ import annotations

from app.main import _fastapi_app
from fastapi.testclient import TestClient

client = TestClient(_fastapi_app)


def test_health_returns_200() -> None:
    """Health endpoint must return HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_schema() -> None:
    """Health response must contain all required fields."""
    response = client.get("/health")
    data = response.json()

    assert data["status"] == "healthy"
    assert data["app"] == "Threadback"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


def test_health_content_type() -> None:
    """Health endpoint must return JSON."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_health_no_secrets_exposed() -> None:
    """Health response must not expose sensitive fields."""
    response = client.get("/health")
    data = response.json()
    sensitive_keys = {"secret", "password", "token", "key", "credential", "api_key"}
    exposed = sensitive_keys.intersection(set(data.keys()))
    assert not exposed, f"Sensitive keys found in health response: {exposed}"


def test_health_is_idempotent() -> None:
    """Multiple health calls must all return healthy status."""
    for _ in range(3):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
