import asyncio
import threading
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


def run_async_blocking(coro: Coroutine) -> Any:
    try:
        loop = asyncio.get_running_loop()
        # Already in an event loop (e.g., FastAPI, Jupyter) — run in thread-safe way
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    except RuntimeError:
        # No loop is running — safe to create and run one
        return asyncio.run(coro)


def run_async_in_thread(coro: Coroutine) -> None:
    def run():
        try:
            asyncio.run(coro)
        except Exception as e:
            print(f"[run_async_in_thread] Error: {e}")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
