"""Exige sessão em todas as requisições, exceto nas operações públicas."""

from uuid import UUID

from starlette.concurrency import run_in_threadpool
from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from fall.api.errors import http_exception_response
from fall.application.sessions import authenticate_session
from fall.integrations.clock import SystemClock
from fall.integrations.session_tokens import OpaqueSessionTokens
from fall.persistence.access import PostgresSessionRepository
from fall.persistence.database import create_database_engine, load_database_url


_PUBLIC_OPERATIONS = {("GET", "/health"), ("POST", "/v1/sessions")}


def _authenticate(token: str, settings) -> UUID | None:
    tokens = OpaqueSessionTokens()
    if tokens.digest(token) is None:
        return None
    engine = create_database_engine(load_database_url(settings.environment))
    try:
        return authenticate_session(
            token, sessions=PostgresSessionRepository(engine), tokens=tokens, clock=SystemClock()
        )
    finally:
        engine.dispose()


class RequireSession:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"], get_route_path(scope)) in _PUBLIC_OPERATIONS:
            await self.app(scope, receive, send)
            return

        authorizations = Headers(scope=scope).getlist("authorization")
        parts = authorizations[0].split() if len(authorizations) == 1 else []
        user_id = None
        if len(parts) == 2 and parts[0].lower() == "bearer":
            user_id = await run_in_threadpool(_authenticate, parts[1], scope["app"].state.settings)
        if user_id is None:
            response = await http_exception_response(
                Request(scope, receive),
                HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"}),
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})["user_id"] = user_id
        scope["state"]["session_token"] = parts[1]
        await self.app(scope, receive, send)
