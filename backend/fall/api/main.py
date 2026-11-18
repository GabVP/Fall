"""Ponto de entrada ASGI da API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fall.config import Settings, load_settings
from fall.observability import Component, Event, configure_logging


_logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API; rotas funcionais entram nos módulos seguintes."""
    selected_settings = settings if settings is not None else load_settings()
    if settings is None:
        configure_logging(Component.API)
    documentation = selected_settings.documentation

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _logger.info(Event.API_STARTED, extra={"environment": selected_settings.environment})
        yield

    return FastAPI(
        title="Fall API",
        openapi_url="/openapi.json" if documentation.schema else None,
        docs_url="/docs" if documentation.swagger else None,
        redoc_url="/redoc" if documentation.redoc else None,
        lifespan=lifespan,
        telemetry={"tracing": False, "logs": False, "metrics": False, "auto_configure": False},
    )
