import json

from app.dependencies import Base, engine
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.import_routes import import_routes
from app.middlewares import create_context
from lib.core.cache_store import CacheStore
from lib.core.postgres_store import get_connection_pool
from lib.core.mongo_store import MongoStore
from lib.core.influx_store import InfluxStore
from lib.core.logger import initialize_logger

# Create all tables
Base.metadata.create_all(bind=engine)

# Create fastAPI app
app = FastAPI()

# Add middlewares
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# add context middleware
app.add_middleware(BaseHTTPMiddleware, dispatch=create_context)


###############################################################################
# Rest server startup hooks
###############################################################################
@app.on_event("startup")
async def startup_event() -> None:
    """
    Initialize modules and attach them to app
    """
    # cachestore
    app.cache_store = CacheStore(namespace="rest_server")
    app.postgres_store = await get_connection_pool()
    app.mongo_store = MongoStore()
    app.influx_store = InfluxStore()

    # TODO delete legacy from here
    app.secret_store = CacheStore(namespace="secrets")
    address_key = "user_address"
    app.address_mapping = app.cache_store.get_dictionary(address_key)

    # logger
    initialize_logger()
    app.logger = structlog.get_logger("rest_server")

    # routers
    import_routes(app)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Cleanup and close connections
    """
    await app.postgres_store.close()
    app.mongo_store.client.close()
    app.influx_store.client.close()