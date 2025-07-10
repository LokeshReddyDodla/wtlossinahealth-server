import asyncio
from typing import Coroutine, Any


def run_async_task(coro: Coroutine) -> Any:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
    except (RuntimeError, AssertionError):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)
