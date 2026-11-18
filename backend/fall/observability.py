"""Configura a saída operacional dos processos Fall."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from logging.config import dictConfig

from fall.config import Environment


class Component(StrEnum):
    API = "api"
    WORKER = "worker"


class Event(StrEnum):
    API_STARTED = "api_started"
    WORKER_STARTED = "worker_started"


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
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": level,
            "component": self.component.value,
            "event": event,
        }
        environment = getattr(record, "environment", None)
        if isinstance(environment, Environment):
            fields["environment"] = environment.value
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
