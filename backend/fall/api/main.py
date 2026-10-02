"""Ponto de entrada ASGI da API."""

from fastapi import FastAPI

from fall.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API; rotas funcionais entram nos módulos seguintes."""
    selected_settings = settings if settings is not None else load_settings()
    documentation = selected_settings.documentation
    return FastAPI(
        title="Fall API",
        openapi_url="/openapi.json" if documentation.schema else None,
        docs_url="/docs" if documentation.swagger else None,
        redoc_url="/redoc" if documentation.redoc else None,
    )
