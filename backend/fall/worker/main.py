"""Ponto de entrada do worker, ainda sem tarefas financeiras."""

import asyncio

from fall.config import Settings, load_settings


async def run(settings: Settings, stop: asyncio.Event) -> None:
    """Mantém o processo disponível até receber uma parada."""
    print(f"Fall worker started ({settings.environment.value}); no jobs registered", flush=True)
    await stop.wait()


def main() -> None:
    settings = load_settings()
    try:
        asyncio.run(run(settings, asyncio.Event()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
