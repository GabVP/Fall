"""Relaciona uma requisição HTTP à resposta e aos registros da API."""

import logging
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fall.observability import Event, request_id_context


_logger = logging.getLogger(__name__)


class RequestCorrelation:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4()
        request_scope = {**scope, "state": {**scope.get("state", {}), "request_id": request_id.hex}}
        status_code = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id.hex
                status_code = message["status"]
            await send(message)

        token = request_id_context.set(request_id)
        try:
            try:
                await self.app(request_scope, receive, send_with_request_id)
            finally:
                _logger.info(Event.REQUEST_FINISHED, extra={"status_code": status_code})
        finally:
            request_id_context.reset(token)
