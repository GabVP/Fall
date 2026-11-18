"""Ponto de entrada ASGI da API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp

from fall.api.correlation import RequestCorrelation
from fall.api.errors import (
    http_exception_response,
    internal_error_response,
    request_validation_response,
)
from fall.config import ConfigurationError, Settings, load_settings
from fall.observability import Component, Event, configure_logging


_logger = logging.getLogger(__name__)


class _CorrelatedAPI(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # A camada externa também acompanha respostas do ServerErrorMiddleware.
        return RequestCorrelation(super().build_middleware_stack())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API; rotas funcionais entram nos módulos seguintes."""
    if settings is None:
        try:
            settings = load_settings()
        except ConfigurationError as error:
            raise SystemExit(str(error)) from None
        configure_logging(Component.API)
    documentation = settings.documentation
    environment = settings.environment

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _logger.info(Event.API_STARTED, extra={"environment": environment})
        yield

    app = _CorrelatedAPI(
        title="Fall API",
        openapi_url="/openapi.json" if documentation.schema else None,
        docs_url="/docs" if documentation.swagger else None,
        redoc_url="/redoc" if documentation.redoc else None,
        lifespan=lifespan,
        telemetry={"tracing": False, "logs": False, "metrics": False, "auto_configure": False},
    )
    app.add_exception_handler(HTTPException, http_exception_response)
    app.add_exception_handler(RequestValidationError, request_validation_response)
    app.add_exception_handler(Exception, internal_error_response)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
