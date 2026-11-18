"""Ponto de entrada do worker, ainda sem tarefas financeiras."""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fall.config import ConfigurationError, Settings, load_settings
from fall.observability import Component, Event, configure_logging, run_id_context


_logger = logging.getLogger(__name__)


@contextmanager
def worker_execution() -> Iterator[None]:
    """Delimita o identificador de uma execução do worker ou de uma tarefa."""
    token = run_id_context.set(uuid4())
    try:
        yield
    except Exception:
        _logger.error(Event.WORKER_FAILED)
        raise
    finally:
        run_id_context.reset(token)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    """Mantém o processo disponível até receber uma parada."""
    with worker_execution():
        _logger.info(Event.WORKER_STARTED, extra={"environment": settings.environment})
        await stop.wait()


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
    except Exception:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
