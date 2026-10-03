"""
Pytest configuration and shared fixtures for Threadback.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def reset_global_mcp_state() -> Iterator[None]:
    """Ensure global thread_service and proposal_registry are reset to clean state for each test."""
    from app.mcp.server import proposal_registry, thread_service

    thread_service.reset()
    proposal_registry.clear()
    yield
    thread_service.reset()
    proposal_registry.clear()


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_mcp_endpoint() -> str:
    """
    Start a live uvicorn server running app.main:app on an ephemeral port.
    Yields the canonical Streamable HTTP endpoint URL:
        http://127.0.0.1:{port}/mcp
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

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("Live uvicorn server failed to accept connections within 5 seconds")

    yield f"http://127.0.0.1:{port}/mcp"

    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
