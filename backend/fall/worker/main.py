"""Ponto de entrada do worker, ainda sem tarefas financeiras."""

import asyncio

from fall.bootstrap import Runtime, build_runtime


async def run(runtime: Runtime, stop: asyncio.Event) -> None:
    """Mantém o processo disponível até receber uma parada."""
    print(f"Fall worker started ({runtime.settings.environment.value}); no jobs registered", flush=True)
    await stop.wait()


def main() -> None:
    runtime = build_runtime()
    try:
        asyncio.run(run(runtime, asyncio.Event()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
