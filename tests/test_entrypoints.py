"""Verifica os pontos de entrada sem acessar serviços externos."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from fall.api.main import create_app
from fall.config import Environment, Settings
from fall.worker.main import run


def test_api_starts_and_publishes_its_schema() -> None:
    app = create_app(Settings(environment=Environment.TEST))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Fall API"


def test_production_api_hides_documentation() -> None:
    app = create_app(Settings(environment=Environment.PRODUCTION))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 404


def test_staging_api_exposes_schema_for_contract_checks() -> None:
    app = create_app(Settings(environment=Environment.STAGING))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_staging_api_hides_interactive_documentation(path: str) -> None:
    app = create_app(Settings(environment=Environment.STAGING))
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("environment", "expected_status"),
    [(Environment.DEVELOPMENT, 200), (Environment.TEST, 404)],
)
def test_redoc_availability_depends_on_profile(
    environment: Environment, expected_status: int
) -> None:
    app = create_app(Settings(environment=environment))
    with TestClient(app) as client:
        response = client.get("/redoc")

    assert response.status_code == expected_status


def test_worker_starts_and_stops_without_external_services(capsys) -> None:
    stop = asyncio.Event()
    stop.set()

    asyncio.run(run(Settings(environment=Environment.TEST), stop))

    assert capsys.readouterr().out == "Fall worker started (test); no jobs registered\n"
