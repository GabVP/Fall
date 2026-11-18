"""Exercita a correlação pela interface HTTP da API."""

import asyncio
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from fall.api.main import create_app
from fall.config import Environment, Settings
from fall.observability import request_id_context


def test_concurrent_requests_keep_independent_server_ids() -> None:
    async def exercise_requests() -> None:
        app = create_app(Settings(environment=Environment.TEST))
        second_request_entered = asyncio.Event()
        first_request_entered = asyncio.Event()

        @app.get("/probe/{name}")
        async def probe(request: Request, name: str) -> JSONResponse:
            current = request_id_context.get()
            assert current is not None
            if name == "first":
                first_request_entered.set()
                await second_request_entered.wait()
            else:
                await first_request_entered.wait()
                second_request_entered.set()
            assert request_id_context.get() == current
            assert request.state.request_id == current.hex
            return JSONResponse({"id": current.hex}, headers={"X-Request-ID": "override"})

        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    client.get("/probe/first", headers={"X-Request-ID": "supplied"}),
                    client.get("/probe/second", headers={"X-Request-ID": "supplied"}),
                ),
                timeout=3,
            )

        first, second = [response.headers["X-Request-ID"] for response in responses]
        assert first != second
        assert "supplied" not in (first, second)
        for response in responses:
            assert response.status_code == 200
            request_id = response.headers["X-Request-ID"]
            assert UUID(request_id).version == 4
            assert response.json()["id"] == request_id
        assert request_id_context.get() is None

    asyncio.run(exercise_requests())


def test_server_error_and_missing_route_have_ids_and_restore_context() -> None:
    async def exercise_requests() -> None:
        app = create_app(Settings(environment=Environment.TEST))
        failed_request_ids = []

        @app.get("/probe")
        async def fail(request: Request) -> None:
            failed_request_ids.append(request.state.request_id)
            raise RuntimeError("probe error")

        transport = ASGITransport(app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            failure = await client.get("/probe")
            assert request_id_context.get() is None
            missing = await client.get("/absent")
            assert request_id_context.get() is None

        assert failure.status_code == 500
        assert failed_request_ids == [failure.headers["X-Request-ID"]]
        assert missing.status_code == 404
        assert missing.headers["X-Request-ID"] != failure.headers["X-Request-ID"]
        assert UUID(missing.headers["X-Request-ID"]).version == 4

    asyncio.run(exercise_requests())
