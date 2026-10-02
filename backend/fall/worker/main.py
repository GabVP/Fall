"""Ponto de entrada do worker, ainda sem tarefas financeiras."""

import asyncio


async def run(stop: asyncio.Event) -> None:
    """Mantém o processo disponível até receber uma parada."""
    print("Fall worker started; no jobs registered", flush=True)
    await stop.wait()


def main() -> None:
    try:
        asyncio.run(run(asyncio.Event()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
