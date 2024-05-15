import time

def retry_request(func, max_retries=3, delay=2, *args, **kwargs):
    attempts = 0
    while attempts < max_retries:
        print("==> Retrying request count: %d" % attempts)
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"Attempt {attempts + 1} failed: {e}")
            attempts += 1
            if attempts < max_retries:
                time.sleep(delay)
    raise Exception(f"Failed after {max_retries} attempts")
