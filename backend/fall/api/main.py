"""Ponto de entrada ASGI da API."""

from fastapi import FastAPI

from fall.bootstrap import build_runtime
from fall.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a API; rotas funcionais entram nos módulos seguintes."""
    runtime = build_runtime(settings)
    app = FastAPI(
        title="Fall API",
        openapi_url="/openapi.json" if runtime.settings.api_docs_enabled else None,
    )
    app.state.runtime = runtime
    return app
