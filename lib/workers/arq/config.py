"""ARQ queue and Redis configuration."""

from arq.connections import RedisSettings
from decouple import config


class Queues:
    """Queue names for task routing."""

    DEFAULT = "arq:queue:default"
    REPORTS = "arq:queue:reports"
    VECTORS = "arq:queue:vectors"
    LIBREVIEW = "arq:queue:libreview"
    INSTANT = "arq:queue:instant"


def get_arq_redis_settings() -> RedisSettings:
    """Get Redis connection settings from environment."""
    host = config("ARQ_REDIS_HOST")
    port = int(config("ARQ_REDIS_PORT", default=6379))
    password = config("ARQ_REDIS_PASSWORD")
    database = int(config("ARQ_REDIS_DB", default=1))

    return RedisSettings(
        host=host,
        port=port,
        password=password,
        database=database,
        conn_timeout=30,
        conn_retries=5,
        conn_retry_delay=1,
    )
