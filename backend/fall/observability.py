"""Configura a saída operacional dos processos Fall."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import StrEnum
from logging.config import dictConfig
from uuid import UUID

from fall.config import Environment


request_id_context: ContextVar[UUID | None] = ContextVar("fall_request_id", default=None)
run_id_context: ContextVar[UUID | None] = ContextVar("fall_run_id", default=None)


class Component(StrEnum):
    API = "api"
    WORKER = "worker"


class Event(StrEnum):
    API_STARTED = "api_started"
    REQUEST_FINISHED = "request_finished"
    WORKER_STARTED = "worker_started"
    WORKER_FAILED = "worker_failed"


_LEVELS = (
    (logging.CRITICAL, "CRITICAL"),
    (logging.ERROR, "ERROR"),
    (logging.WARNING, "WARNING"),
    (logging.INFO, "INFO"),
)


class _OperationalFormatter(logging.Formatter):
    def __init__(self, component: Component) -> None:
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        level = next((name for limit, name in _LEVELS if record.levelno >= limit), "DEBUG")
        event = record.msg.value if isinstance(record.msg, Event) else "runtime_event"
        fields: dict[str, str | int] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": level,
            "component": self.component.value,
            "event": event,
        }
        environment = getattr(record, "environment", None)
        if isinstance(environment, Environment):
            fields["environment"] = environment.value
        status_code = getattr(record, "status_code", None)
        if type(status_code) is int and 100 <= status_code <= 599:
            fields["status_code"] = status_code
        request_id = request_id_context.get()
        if isinstance(request_id, UUID):
            fields["request_id"] = request_id.hex
        run_id = run_id_context.get()
        if isinstance(run_id, UUID):
            fields["run_id"] = run_id.hex
        return json.dumps(fields)


def configure_logging(component: Component) -> None:
    """Aplica a mesma política de campos à aplicação e ao servidor."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"operational": {"()": _OperationalFormatter, "component": component}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "operational"},
                "discard": {"class": "logging.NullHandler"},
            },
            "root": {"level": "INFO", "handlers": ["console"]},
            "loggers": {
                "uvicorn": {"level": "INFO", "handlers": [], "propagate": True},
                "uvicorn.access": {"handlers": ["discard"], "propagate": False},
            },
        }
    )
    logging.captureWarnings(True)
