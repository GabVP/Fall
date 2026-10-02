"""Verifica os pontos de entrada sem acessar serviços externos."""

import asyncio

from fastapi.testclient import TestClient

from fall.api.main import create_app
from fall.worker.main import run


def test_api_starts_and_publishes_its_schema() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Fall API"


def test_worker_starts_and_stops_without_external_services(capsys) -> None:
    stop = asyncio.Event()
    stop.set()

    asyncio.run(run(stop))

    assert capsys.readouterr().out == "Fall worker started; no jobs registered\n"
