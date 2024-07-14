import redis
from decouple import config
from typing import Optional, Union

# Read redis host from env
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1:6379")
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}/0"


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

    def is_connected(self) -> bool:
        return self.__client.ping()

    def get_key(self, key: str) -> Optional[bytes]:
        key = f"{self.__namespace}_{key.strip()}"
        return self.__client.get(key)

    def set_key(
        self, key: str, value: str, expire: Optional[Union[int, None]] = 300
    ) -> Optional[bool]:
        key = f"{self.__namespace}_{key.strip()}"
        if expire is None:
            expire = 300
        elif not isinstance(expire, int):
            raise ValueError("Expire time must be an integer or None")
        return self.__client.setex(name=key, value=value, time=expire)

    def delete_key(self, key: str) -> Optional[int]:
        key = f"{self.__namespace}_{key.strip()}"
        return self.__client.delete(key)
