"""Verifica a saída emitida pelo logging do Fall e pelo servidor HTTP."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime


_LOGGING_PROBE = """
import logging

from fall.config import Environment
from fall.observability import Component, Event, configure_logging

configure_logging(Component.WORKER)
configure_logging(Component.WORKER)
logger = logging.getLogger("fall.worker")
logger.info(Event.WORKER_STARTED, extra={"environment": Environment.TEST})

try:
    raise RuntimeError("exception-sentinel")
except RuntimeError:
    logger.exception(
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

async def fail(request: Request):
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
    finally:
        server.should_exit = True
        await server_task

asyncio.run(check_server())
"""


def test_reconfiguring_worker_logging_keeps_one_record_per_event() -> None:
    records = _read_logs(_LOGGING_PROBE)

    assert len(records) == 2
    assert records[0]["component"] == "worker"
    assert records[0]["event"] == "worker_started"
    assert records[0]["environment"] == "test"
    assert records[1]["level"] == "ERROR"
    assert records[1]["event"] == "runtime_event"
    assert set(records[1]) == {"timestamp", "level", "component", "event"}
    assert datetime.fromisoformat(records[1]["timestamp"]).utcoffset() == UTC.utcoffset(None)


def test_uvicorn_output_omits_request_and_exception_values() -> None:
    records = _read_logs(_SERVER_PROBE)

    assert all(record["component"] == "api" for record in records)
    assert any(record["event"] == "api_started" for record in records)
    assert any(record["level"] == "WARNING" for record in records)
    assert any(record["level"] == "ERROR" for record in records)


def _read_logs(probe: str) -> list[dict[str, str]]:
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=os.environ | {"FALL_ENVIRONMENT": "test", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert "-sentinel" not in result.stderr
    assert "Traceback" not in result.stderr
    return [json.loads(line) for line in result.stderr.splitlines()]
