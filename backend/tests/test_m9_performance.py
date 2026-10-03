"""
M9 Latency and Performance Benchmark Suite for Threadback Remote MCP.

Measures round-trip response latencies over live Streamable HTTP MCP
with OAuth 2.1 authentication against the Alexa+ target (< 500 ms):
1. initialize latency
2. tools/list latency
3. read-only tool latency (discover_unfinished_threads, get_thread_context, find_thread_blockers)
4. analyze_thread latency
5. suggest_next_action latency
6. prepare_action latency
7. execute_action latency
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator

import pytest
from app.security.jwt_validator import create_test_token
from mcp.client.session import ClientSession
from mcp.client.streamable_http import httpx2, streamable_http_client

PERF_SECRET_KEY = "test-perf-secret-key-32-bytes-minimum-length!!"


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def perf_mcp_server() -> AsyncIterator[tuple[str, str]]:
    port = _find_free_port()
    env = os.environ.copy()
    env["AUTH_ENABLED"] = "true"
    env["AUTH_SECRET_KEY"] = PERF_SECRET_KEY

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
        env=env,
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
        pytest.fail("Live server failed to accept connections within 5 seconds")

    token = create_test_token(sub="perf-tester", secret_key=PERF_SECRET_KEY)
    endpoint = f"http://127.0.0.1:{port}/mcp"

    yield endpoint, token

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_round_trip_latencies(perf_mcp_server: tuple[str, str]) -> None:
    """
    Execute all operations sequentially and measure round-trip latencies.
    Verifies that all operations complete and report their measured timing.
    """
    endpoint, token = perf_mcp_server
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})

    timings_ms: dict[str, float] = {}

    async with streamable_http_client(endpoint, http_client=http_client) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize
            t0 = time.perf_counter()
            init_res = await session.initialize()
            timings_ms["initialize"] = (time.perf_counter() - t0) * 1000
            assert init_res is not None

            # 2. tools/list
            t0 = time.perf_counter()
            tools_res = await session.list_tools()
            timings_ms["tools/list"] = (time.perf_counter() - t0) * 1000
            assert len(tools_res.tools) in (7, 9)

            # 3. discover_unfinished_threads
            t0 = time.perf_counter()
            disc_res = await session.call_tool("discover_unfinished_threads", {})
            timings_ms["discover_unfinished_threads"] = (
                time.perf_counter() - t0
            ) * 1000
            assert not disc_res.is_error

            # 4. get_thread_context
            t0 = time.perf_counter()
            ctx_res = await session.call_tool(
                "get_thread_context", {"thread_id": "thread-university-application"}
            )
            timings_ms["get_thread_context"] = (time.perf_counter() - t0) * 1000
            assert not ctx_res.is_error

            # 5. find_thread_blockers
            t0 = time.perf_counter()
            blk_res = await session.call_tool(
                "find_thread_blockers", {"thread_id": "thread-university-application"}
            )
            timings_ms["find_thread_blockers"] = (time.perf_counter() - t0) * 1000
            assert not blk_res.is_error

            # 6. analyze_thread
            t0 = time.perf_counter()
            anl_res = await session.call_tool(
                "analyze_thread", {"thread_id": "thread-university-application"}
            )
            timings_ms["analyze_thread"] = (time.perf_counter() - t0) * 1000
            assert not anl_res.is_error

            # 7. suggest_next_action
            t0 = time.perf_counter()
            sug_res = await session.call_tool(
                "suggest_next_action", {"thread_id": "thread-university-application"}
            )
            timings_ms["suggest_next_action"] = (time.perf_counter() - t0) * 1000
            assert not sug_res.is_error

            # 8. prepare_action
            t0 = time.perf_counter()
            prep_res = await session.call_tool(
                "prepare_action", {"thread_id": "thread-client-report"}
            )
            timings_ms["prepare_action"] = (time.perf_counter() - t0) * 1000
            assert not prep_res.is_error
            proposal_id = prep_res.structured_content["proposal"]["id"]

            # 9. execute_action
            t0 = time.perf_counter()
            exec_res = await session.call_tool(
                "execute_action",
                {
                    "proposal_id": proposal_id,
                    "confirmed": True,
                    "execution_mode": "SIMULATED",
                },
            )
            timings_ms["execute_action"] = (time.perf_counter() - t0) * 1000
            assert not exec_res.is_error

    # Print measured latency table
    print("\n--- Threadback M9 MCP Round-Trip Latency Report ---")
    for operation, ms in timings_ms.items():
        status = "PASS (<500ms)" if ms < 500.0 else "EXCEEDS_TARGET"
        print(f"  {operation:<30}: {ms:6.2f} ms [{status}]")
        # Alexa+ requirement: all operations should be comfortably below 500 ms
        assert ms < 500.0, (
            f"Operation {operation} exceeded 500ms target with {ms:.2f}ms"
        )
