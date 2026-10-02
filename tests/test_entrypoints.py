"""Verifica os pontos de entrada sem acessar serviços externos."""

import asyncio

from fastapi.testclient import TestClient

from fall.api.main import create_app
from fall.bootstrap import build_runtime
from fall.config import Environment, Settings
from fall.worker.main import run


def test_api_starts_and_publishes_its_schema() -> None:
    app = create_app(Settings(environment=Environment.TEST))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Fall API"
    assert app.state.runtime.settings.environment is Environment.TEST


def test_production_api_hides_documentation() -> None:
    app = create_app(Settings(environment=Environment.PRODUCTION))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 404


def test_worker_starts_and_stops_without_external_services(capsys) -> None:
    stop = asyncio.Event()
    stop.set()

    runtime = build_runtime(Settings(environment=Environment.TEST))
    asyncio.run(run(runtime, stop))

    assert capsys.readouterr().out == "Fall worker started (test); no jobs registered\n"
