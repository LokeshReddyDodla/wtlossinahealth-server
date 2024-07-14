import json

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.import_routes import import_routes
from app.middlewares import create_context
from lib.core.cache_store import CacheStore
from lib.core.postgres_store import PostgresStore, Base, engine
from lib.core.mongo_store import MongoStore
from lib.core.influx_store import InfluxStore
from lib.core.logger import initialize_logger

# Create all tables
async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    # cachestore with different namespaces
    app.cache_store = CacheStore(namespace="rest_server")
    app.secret_store = CacheStore(namespace="secrets")
    app.session_store = CacheStore(namespace="user_sessions")
    app.otp_store = CacheStore(namespace="user_otp")
    app.config_store = CacheStore(namespace="app_config")
    app.rate_limit_store = CacheStore(namespace="rate_limiting")
    app.address_mapping_store = CacheStore(namespace="address_mapping")
    
    # Databases
    app.postgres_store = PostgresStore()
    app.mongo_store = MongoStore()
    app.influx_store = InfluxStore()

    # Logger
    initialize_logger()
    app.logger = structlog.get_logger("rest_server")

    # Routers
    import_routes(app)
    
    # Create tables
    await create_db_and_tables()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Cleanup and close connections
    """
    await app.postgres_store.close()
    app.mongo_store.client.close()
    app.influx_store.client.close()