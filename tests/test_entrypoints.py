"""Verifica os pontos de entrada sem acessar serviços externos."""

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from fall.api.main import create_app
from fall.config import Environment, Settings
from fall.observability import run_id_context
from fall.worker.main import run, worker_execution


@pytest.mark.parametrize("environment", list(Environment))
def test_health_exposes_only_process_status_without_credentials(environment: Environment) -> None:
    app = create_app(Settings(environment=environment))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_api_starts_and_publishes_its_schema(authenticated_headers) -> None:
    app = create_app(Settings(environment=Environment.TEST))
    with TestClient(app) as client:
        response = client.get("/openapi.json", headers=authenticated_headers)

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Fall API"


def test_api_with_injected_settings_preserves_host_logging() -> None:
    root = logging.getLogger()
    handlers = root.handlers.copy()
    level = root.level

    with TestClient(create_app(Settings(environment=Environment.TEST))):
        assert root.handlers == handlers
        assert root.level == level


def test_production_api_hides_documentation(authenticated_headers) -> None:
    app = create_app(Settings(environment=Environment.PRODUCTION))
    with TestClient(app) as client:
        response = client.get("/openapi.json", headers=authenticated_headers)

    assert response.status_code == 404


def test_staging_api_exposes_schema_for_contract_checks(authenticated_headers) -> None:
    app = create_app(Settings(environment=Environment.STAGING))
    with TestClient(app) as client:
        response = client.get("/openapi.json", headers=authenticated_headers)

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_staging_api_hides_interactive_documentation(path: str, authenticated_headers) -> None:
    app = create_app(Settings(environment=Environment.STAGING))
    with TestClient(app) as client:
        response = client.get(path, headers=authenticated_headers)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("environment", "expected_status"),
    [(Environment.DEVELOPMENT, 200), (Environment.TEST, 404)],
)
def test_redoc_availability_depends_on_profile(
    environment: Environment, expected_status: int, authenticated_headers
) -> None:
    app = create_app(Settings(environment=environment))
    with TestClient(app) as client:
        response = client.get("/redoc", headers=authenticated_headers)

    assert response.status_code == expected_status


def test_worker_starts_and_stops_without_external_services(caplog) -> None:
    caplog.set_level(logging.INFO)
    stop = asyncio.Event()
    stop.set()

    asyncio.run(run(Settings(environment=Environment.TEST), stop))

    assert caplog.record_tuples == [("fall.worker.main", logging.INFO, "worker_started")]


def test_tasks_in_the_same_worker_keep_independent_run_ids() -> None:
    async def exercise() -> None:
        with worker_execution():
            parent_id = run_id_context.get()

            async def task():
                with worker_execution():
                    task_id = run_id_context.get()
                    await asyncio.sleep(0)
                    assert run_id_context.get() == task_id
                assert run_id_context.get() == parent_id
                return task_id

            first_id, second_id = await asyncio.gather(task(), task())
            assert None not in {parent_id, first_id, second_id}
            assert len({parent_id, first_id, second_id}) == 3

        assert run_id_context.get() is None

    asyncio.run(exercise())
