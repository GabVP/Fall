"""Ponto de entrada do worker, ainda sem tarefas financeiras."""

import asyncio
import logging
from uuid import uuid4

from fall.config import ConfigurationError, Settings, load_settings
from fall.observability import Component, Event, configure_logging, run_id_context


_logger = logging.getLogger(__name__)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    """Mantém o processo disponível até receber uma parada."""
    token = run_id_context.set(uuid4())
    try:
        _logger.info(Event.WORKER_STARTED, extra={"environment": settings.environment})
        await stop.wait()
    finally:
        run_id_context.reset(token)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
    configure_logging(Component.WORKER)
    try:
        asyncio.run(run(settings, asyncio.Event()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
