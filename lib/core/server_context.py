from dataclasses import dataclass

import asyncpg
from lib.core.influx_store import InfluxStore
from lib.core.mongo_store import MongoStore
import structlog

from lib.core.cache_store import CacheStore


@dataclass
class Context:
    """
    Context class represents essential connectors for each request.
    :param logger: structlog logger
    :param request_id: string request ID
    :param cachestore: CacheStore connector
    :param postgres_store: Datastore connector instance
    :param ds_connection: Datastore connection instance
    :param mongo_store: MongoDB connector instance
    :param influx_store: InfluxDB connector instance
    """

    logger: structlog.stdlib.AsyncBoundLogger
    request_id: str
    cache_store: CacheStore
    secret_store: CacheStore
    session_store: CacheStore
    otp_store: CacheStore
    config_store: CacheStore
    rate_limit_store: CacheStore
    address_mapping_store: CacheStore
    postgres_store: asyncpg.pool.Pool
    mongo_store: MongoStore
    influx_store: InfluxStore