"""
Tests for frontend static file serving, SPA fallback, and API route preservation (M16).

Verifies that:
- GET / serves the React application HTML (index.html)
- GET /assets/... serves static bundles (JS, CSS)
- GET /favicon.svg serves root static assets
- Client-side navigation paths (e.g. /dashboard) fall back to index.html
- Reserved endpoints (GET /health, GET /docs, GET /openapi.json) remain intact
- Unhandled API routes (GET /api/...) return 404 JSON, NOT index.html
"""

from __future__ import annotations

from app.main import _fastapi_app
from fastapi.testclient import TestClient

client = TestClient(_fastapi_app)


def test_root_serves_react_index_html() -> None:
    """GET / must return HTTP 200 with HTML containing React root div."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root"></div>' in response.text
    assert "<title>Threadback</title>" in response.text


def test_root_references_vite_assets() -> None:
    """index.html must reference Vite assets with /assets/ prefix."""
    response = client.get("/")
    assert response.status_code == 200
    assert "/assets/" in response.text


def test_vite_assets_reachable_and_return_200() -> None:
    """Assets referenced in index.html must return HTTP 200."""
    root_response = client.get("/")
    assert root_response.status_code == 200

    # Extract asset link or script path from HTML
    import re

    asset_matches = re.findall(r"/(assets/[a-zA-Z0-9_\-\.]+)", root_response.text)
    assert len(asset_matches) > 0, "No assets found in index.html"

    for asset_path in asset_matches[:3]:
        asset_res = client.get(f"/{asset_path}")
        assert asset_res.status_code == 200, (
            f"Asset /{asset_path} returned {asset_res.status_code}"
        )


def test_favicon_serves_static_file() -> None:
    """GET /favicon.svg must serve the favicon with SVG content type."""
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")


def test_spa_client_routing_fallback() -> None:
    """Unknown non-API paths must fall back to index.html for React SPA routing."""
    response = client.get("/dashboard/view")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root"></div>' in response.text


def test_health_endpoint_still_returns_json() -> None:
    """GET /health must return JSON health status, not index.html."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "Threadback"


def test_api_404_preservation() -> None:
    """GET /api/nonexistent must return 404 JSON, NOT fallback to index.html."""
    response = client.get("/api/nonexistent_test_route")
    assert response.status_code == 404
    assert "application/json" in response.headers.get("content-type", "")
    assert '<div id="root"></div>' not in response.text


def test_docs_and_openapi_still_accessible() -> None:
    """Interactive documentation must still be accessible."""
    docs_res = client.get("/docs")
    assert docs_res.status_code == 200

    openapi_res = client.get("/openapi.json")
    assert openapi_res.status_code == 200
    assert "application/json" in openapi_res.headers["content-type"]
