"""Verifica a saída emitida pelo logging do Fall e pelo servidor HTTP."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import UUID


_LOGGING_PROBE = """
import asyncio
import logging

from fall.config import Environment, Settings
from fall.observability import Component, configure_logging, run_id_context
from fall.worker.main import run

configure_logging(Component.WORKER)
configure_logging(Component.WORKER)

async def check_workers():
    stop = asyncio.Event()
    settings = Settings(Environment.TEST)

    async def start_worker():
        await run(settings, stop)
        assert run_id_context.get() is None

    workers = [asyncio.create_task(start_worker()) for _ in range(2)]
    await asyncio.sleep(0)
    stop.set()
    await asyncio.gather(*workers)

asyncio.run(check_workers())

try:
    raise RuntimeError("exception-sentinel")
except RuntimeError:
    logging.getLogger("fall.worker").exception(
        {"token": "message-sentinel"},
        extra={"context": {"payload": "extra-sentinel"}, "environment": "profile-sentinel"},
    )
"""


_SERVER_PROBE = """
import asyncio
import logging
import warnings

import httpx
import uvicorn
from fastapi import Request

from fall.api.main import create_app

failed_request_ids = []

async def fail(request: Request):
    failed_request_ids.append(request.state.request_id)
    logging.getLogger("dependency").warning(
        "User input %s", await request.body(),
        extra={"token": request.headers["authorization"]},
    )
    warnings.warn("warning-sentinel", stacklevel=1)
    raise RuntimeError("exception-sentinel")

def app_factory():
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(logging.StreamHandler())
    logger.propagate = False
    app = create_app()
    app.add_api_route("/{item}", fail, methods=["POST"])
    return app

async def check_server():
    server = uvicorn.Server(uvicorn.Config(app_factory, factory=True, port=0))
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("test server failed to start")
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/path-sentinel?secret=query-sentinel",
                content="body-sentinel",
                headers={"authorization": "Bearer token-sentinel"},
            )
            assert response.status_code == 500
            assert failed_request_ids == [response.headers["X-Request-ID"]]
            print(response.headers["X-Request-ID"])
    finally:
        server.should_exit = True
        await server_task

asyncio.run(check_server())
"""


def test_reconfiguring_worker_logging_keeps_one_record_per_event() -> None:
    records, output = _run_probe(_LOGGING_PROBE)

    assert not output
    assert len(records) == 3
    first, second, error = records
    for worker in (first, second):
        assert worker["component"] == "worker"
        assert worker["event"] == "worker_started"
        assert worker["environment"] == "test"
        assert UUID(worker["run_id"]).version == 4
    assert first["run_id"] != second["run_id"]
    assert error["level"] == "ERROR"
    assert error["event"] == "runtime_event"
    assert set(error) == {"timestamp", "level", "component", "event"}
    assert datetime.fromisoformat(error["timestamp"]).utcoffset() == UTC.utcoffset(None)


def test_uvicorn_output_omits_request_and_exception_values() -> None:
    records, response_request_id = _run_probe(_SERVER_PROBE)

    assert all(record["component"] == "api" for record in records)
    assert any(record["event"] == "api_started" for record in records)
    assert any(record["level"] == "ERROR" for record in records)
    completed, = [record for record in records if record["event"] == "request_finished"]
    assert completed["status_code"] == 500
    assert completed["request_id"] == response_request_id
    assert UUID(completed["request_id"]).version == 4
    warnings = [record for record in records if record["level"] == "WARNING"]
    assert warnings and all(record["request_id"] == completed["request_id"] for record in warnings)


def _run_probe(probe: str) -> tuple[list[dict[str, str | int]], str]:
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=os.environ | {"FALL_ENVIRONMENT": "test", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "-sentinel" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    return [json.loads(line) for line in result.stderr.splitlines()], result.stdout.strip()
