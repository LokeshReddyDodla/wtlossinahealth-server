import time

from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_fixed)


def retry_request(func, *args, max_retries=3, delay=2, **kwargs):
    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_fixed(delay),
        retry=retry_if_exception_type(Exception),  # retries on any exception
        reraise=True,  # raises the last exception after all retries
    )
    def wrapped_func():
        print("==> Retrying request")
        return func(*args, **kwargs)

    return wrapped_func()
