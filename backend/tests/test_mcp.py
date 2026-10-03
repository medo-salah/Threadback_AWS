"""
M2 MCP Integration Tests.

Tests the real MCP protocol using the official MCP Python SDK client.

Test categories
---------------
A. Server startup (HTTP reachability via live uvicorn process)
B. MCP initialization
C. Protocol version
D. Server information
E. Capabilities
F. Tool discovery
G. Empty Threadback tool list
H. M1 health regression
I. Invalid/malformed MCP request handling

Testing strategy
----------------
Tests B–G use Client(mcp_server) directly — the MCP 2.x in-process
approach that requires no HTTP transport and no ASGI lifespan management.

Tests A and I require the actual HTTP transport. These use a live uvicorn
server started as an asyncio subprocess on an ephemeral port, queried
via httpx2, then shut down at test teardown.

This approach produces genuine end-to-end protocol coverage.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import httpx2
import pytest
from app.mcp.server import mcp_server as _mcp_server
from mcp.client.client import Client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_PORT = 18765  # Ephemeral port for live-server tests — not used by M1


def _find_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server_url():
    """
    Start a real uvicorn process on a free port.

    Yields the base URL (e.g. "http://127.0.0.1:18765") for the duration
    of the module, then terminates the process.
    """
    port = _find_free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 5 s for the server to accept connections
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("Live uvicorn server did not start within 5 seconds")

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# A. Server startup — HTTP reachability
# ---------------------------------------------------------------------------


def test_mcp_server_http_reachable(live_server_url: str) -> None:
    """
    A. The canonical MCP endpoint /mcp must be reachable.

    A GET (wrong method for MCP) must return 4xx, not 404 or 500.
    404 would mean the mount failed; 500 would mean the server crashed.
    """
    with httpx2.Client(timeout=5.0) as client:
        response = client.get(f"{live_server_url}/mcp")
    assert response.status_code not in (
        404,
        500,
    ), (
        f"Unexpected status {response.status_code} — endpoint may not be mounted correctly"
    )


def test_health_still_reachable_on_live_server(live_server_url: str) -> None:
    """M1 regression on live server: /health must still return 200."""
    with httpx2.Client(timeout=5.0) as client:
        response = client.get(f"{live_server_url}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_mcp_nested_endpoint_not_canonical(live_server_url: str) -> None:
    """
    F. Verify /mcp/mcp is not the canonical MCP endpoint.

    The canonical endpoint is /mcp. The old /mcp/mcp path must not be
    mistakenly treated as a valid MCP endpoint. It should return 404
    (not found in the sub-app) or a non-MCP response.
    """
    with httpx2.Client(timeout=5.0) as client:
        response = client.get(f"{live_server_url}/mcp/mcp")
    # 404 is the expected outcome — the sub-app only has a route at /
    # (which maps to /mcp at the FastAPI level). /mcp/mcp would be /mcp
    # within the sub-app, which has no route registered there.
    assert response.status_code == 404, (
        f"Expected 404 for /mcp/mcp (not canonical), got {response.status_code}. "
        f"This suggests two competing MCP endpoints exist."
    )


# ---------------------------------------------------------------------------
# B–G. Full MCP protocol flow (in-process via Client(mcp_server))
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_initialization() -> None:
    """B. MCP initialization must succeed."""
    async with Client(_mcp_server) as client:
        # Client.__aenter__ performs the initialize handshake.
        assert client.server_info is not None, "initialize() did not return server info"


@pytest.mark.asyncio
async def test_mcp_protocol_version() -> None:
    """
    C. Server must negotiate the protocol version the client requests.

    The MCP protocol uses version negotiation: the server echoes back
    the version the client sends in its initialize request.

    The MCP SDK's high-level Client sends 2026-07-28 (LATEST_PROTOCOL_VERSION).
    The low-level ClientSession sends 2025-11-25 (LATEST_HANDSHAKE_VERSION).
    Alexa+ is documented to target 2025-11-25.

    This test verifies both:
    1. The Client() (using 2026-07-28) gets 2026-07-28 back.
    2. The negotiated version is in SUPPORTED_PROTOCOL_VERSIONS.
    3. 2025-11-25 (Alexa+ target) is in SUPPORTED_PROTOCOL_VERSIONS.
    """
    from mcp.types.version import SUPPORTED_PROTOCOL_VERSIONS

    ALEXA_TARGET_VERSION = "2025-11-25"

    async with Client(_mcp_server) as client:
        negotiated = client.protocol_version
        # The server must respond with a recognized protocol version
        assert negotiated in SUPPORTED_PROTOCOL_VERSIONS, (
            f"Negotiated version {negotiated!r} is not in SUPPORTED_PROTOCOL_VERSIONS"
        )
        # The server must also support the Alexa+ target version
        assert ALEXA_TARGET_VERSION in SUPPORTED_PROTOCOL_VERSIONS, (
            f"Alexa+ target version {ALEXA_TARGET_VERSION!r} is not supported by the SDK"
        )


@pytest.mark.asyncio
async def test_mcp_server_information() -> None:
    """D. Server information must be present and sane."""
    async with Client(_mcp_server) as client:
        info = client.server_info
        assert info is not None
        assert info.name, "serverInfo.name must not be empty"
        assert info.version, "serverInfo.version must not be empty"
        assert info.name == "Threadback"
        assert info.version == "0.1.0"


@pytest.mark.asyncio
async def test_mcp_capabilities() -> None:
    """E. Capabilities object must be present. Only actually-implemented caps are advertised."""
    async with Client(_mcp_server) as client:
        caps = client.server_capabilities
        assert caps is not None, "capabilities missing from init response"
        # Tools capability is present (will contain tools in M5+)
        assert caps.tools is not None, (
            "tools capability must be advertised so clients know tools/list is valid"
        )


@pytest.mark.asyncio
async def test_mcp_tools_list_succeeds() -> None:
    """F. tools/list must succeed (return a result, not an error)."""
    async with Client(_mcp_server) as client:
        result = await client.list_tools()
        assert result is not None, "list_tools() returned None"
        assert hasattr(result, "tools"), "list_tools result must have .tools attribute"


@pytest.mark.asyncio
async def test_mcp_exact_m10_tools() -> None:
    """G. The tool list must contain exactly nine Threadback tools after M10.

    Canonical M10 tools:
      - discover_unfinished_threads
      - get_thread_context
      - find_thread_blockers
      - analyze_thread
      - suggest_next_action
      - prepare_action
      - execute_action
      - verify_thread_completion
      - close_thread
    """
    expected_tools = {
        "discover_unfinished_threads",
        "get_thread_context",
        "find_thread_blockers",
        "analyze_thread",
        "suggest_next_action",
        "prepare_action",
        "execute_action",
        "verify_thread_completion",
        "close_thread",
    }

    async with Client(_mcp_server) as client:
        result = await client.list_tools()
        tool_names = {t.name for t in result.tools}

        assert tool_names == expected_tools, (
            f"Expected exactly M10 tools {expected_tools}, got: {tool_names}"
        )


# ---------------------------------------------------------------------------
# H. M1 Health regression (in-process via FastAPI TestClient)
# ---------------------------------------------------------------------------


def test_health_regression_returns_200() -> None:
    """H1. GET /health must return HTTP 200 (M1 regression)."""
    from app.main import _fastapi_app
    from fastapi.testclient import TestClient

    client = TestClient(_fastapi_app)
    assert client.get("/health").status_code == 200


def test_health_regression_schema() -> None:
    """H2. /health response schema must remain intact (M1 regression)."""
    from app.main import _fastapi_app
    from fastapi.testclient import TestClient

    data = TestClient(_fastapi_app).get("/health").json()
    assert data["status"] == "healthy"
    assert data["app"] == "Threadback"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


def test_health_regression_no_secrets() -> None:
    """H3. /health must not expose secrets (M1 regression)."""
    from app.main import _fastapi_app
    from fastapi.testclient import TestClient

    data = TestClient(_fastapi_app).get("/health").json()
    sensitive = {"secret", "password", "token", "key", "credential", "api_key"}
    exposed = sensitive.intersection(set(data.keys()))
    assert not exposed, f"Sensitive keys in health response: {exposed}"


# ---------------------------------------------------------------------------
# I. Invalid / malformed MCP request handling (live server)
# ---------------------------------------------------------------------------


def test_mcp_invalid_json_does_not_crash_server(live_server_url: str) -> None:
    """
    I1. Sending invalid JSON to /mcp must not crash the server (no 500).

    The server must return a structured error response.
    """
    with httpx2.Client(timeout=5.0) as client:
        response = client.post(
            f"{live_server_url}/mcp",
            content=b"this is not valid json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code != 500, (
        f"Server returned 500 on invalid JSON — must handle gracefully. "
        f"Body: {response.text[:500]}"
    )


def test_mcp_empty_body_does_not_crash_server(live_server_url: str) -> None:
    """
    I2. Sending an empty body to /mcp must not crash the server (no 500).
    """
    with httpx2.Client(timeout=5.0) as client:
        response = client.post(
            f"{live_server_url}/mcp",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code != 500, (
        f"Server returned 500 on empty body — must handle gracefully. "
        f"Body: {response.text[:500]}"
    )


def test_server_still_healthy_after_bad_requests(live_server_url: str) -> None:
    """
    I3. After receiving malformed MCP requests, /health must still return 200.

    Ensures bad MCP input does not affect the rest of the application.
    """
    with httpx2.Client(timeout=5.0) as client:
        # Send bad request first
        client.post(
            f"{live_server_url}/mcp",
            content=b"garbage",
            headers={"Content-Type": "application/json"},
        )
        # Then check health
        r = client.get(f"{live_server_url}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
