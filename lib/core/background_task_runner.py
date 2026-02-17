from concurrent.futures import ThreadPoolExecutor
import asyncio
from typing import Callable


class BackgroundTaskRunner:
    def __init__(self, max_workers: int = 5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def run(self, func: Callable, *args, **kwargs) -> None:
        """
        Run a synchronous or asynchronous function in the background.

        Args:
            func (Callable): The function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.
        """
        if asyncio.iscoroutinefunction(func):
            # For asynchronous functions, schedule them on the event loop
            asyncio.create_task(self._run_async(func, *args, **kwargs))
        else:
            # For synchronous functions, use the ThreadPoolExecutor
            self.executor.submit(func, *args, **kwargs)

    async def _run_async(self, func: Callable, *args, **kwargs) -> None:
        """
        Helper method to run asynchronous functions.

        Args:
            func (Callable): The async function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.
        """
        await func(*args, **kwargs)

    def shutdown(self, wait: bool = True):
        """
        Shut down the executor, optionally waiting for tasks to complete.

        Args:
            wait (bool): Whether to wait for the executor to finish.
        """
        self.executor.shutdown(wait=wait)
