"""Ponto de entrada ASGI da API."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Monta a API; rotas funcionais entram nos módulos seguintes."""
    return FastAPI(title="Fall API")


app = create_app()
