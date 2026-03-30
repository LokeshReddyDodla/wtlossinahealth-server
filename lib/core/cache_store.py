from typing import List, Optional, Union

import redis
from decouple import config

# Read redis host from env
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1:6379")
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}/0" if REDIS_PASSWORD else f"redis://{REDIS_HOST}/0"


class CacheStore:
    def __init__(self, namespace: str) -> None:
        redis_client = redis.from_url(REDIS_URL)
        namespace = namespace.strip()
        if not namespace:
            raise ValueError("Invalid namespace")
        self.__namespace = namespace

        if not redis_client.ping():
            raise ConnectionError("Unable to connect to redis")

        self.__client: redis.Redis = redis_client

    def _get_client(self) -> redis.Redis:
        """Protected method to access client safely"""
        return self.__client

    def _get_namespace(self) -> str:
        """Protected method to access namespace safely"""
        return self.__namespace

    def is_connected(self) -> bool:
        return self.__client.ping()

    def get_key(self, key: str) -> Optional[bytes]:
        key = f"{self.__namespace}:{key.strip()}"
        return self.__client.get(key)

    def set_key(
        self,
        key: str,
        value: str,
        expire: Optional[int] = 300,
        nx: bool = False,
    ) -> Optional[bool]:
        key = f"{self.__namespace}:{key.strip()}"

        if nx:
            return self.__client.set(
                name=key,
                value=value,
                ex=expire,
                nx=True,
            )

        if expire is not None:
            return self.__client.setex(
                name=key,
                time=expire,
                value=value,
            )

        return self.__client.set(name=key, value=value)

    def incr_key(self, key: str) -> int:
        """Atomically increment a key and return the new value."""
        key = f"{self.__namespace}:{key.strip()}"
        return self.__client.incr(key)

    def expire_key(self, key: str, seconds: int) -> bool:
        """Set TTL on an existing key without changing its value."""
        key = f"{self.__namespace}:{key.strip()}"
        return self.__client.expire(key, seconds)

    def delete_key(self, key: str) -> Optional[int]:
        key = f"{self.__namespace}:{key.strip()}"
        return self.__client.delete(key)

    def get_keys_with_prefix(self, prefix: str) -> List[str]:
        """
        Retrieves all keys that start with the specified prefix.
        """
        full_prefix = f"{self.__namespace}:{prefix}*"
        keys = []
        cursor = 0
        while True:
            cursor, partial_keys = self.__client.scan(
                cursor, match=full_prefix
            )
            keys.extend(partial_keys)
            if cursor == 0:
                break
        return keys
