import os
from fastapi import FastAPI
from socketio import ASGIApp

from app.import_routes import import_routes
from lib.core.logging import setup_logging
from lib.initializers.cache_setup import initialize_caches
from lib.initializers.db_setup import (
    create_db_and_tables,
    initialize_databases,
)
from lib.initializers.middleware_setup import setup_middlewares
from lib.services.socketio_service import sio


# -----------------------------------------------------------------------------
# App factory
# -----------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        swagger_ui_parameters={
            "persistAuthorization": os.getenv("ENV") == "dev"
        }
    )

    # logging
    setup_logging(app)
    app.state.logger = __import__("structlog").get_logger("rest_server")

    # middleware
    setup_middlewares(app)

    # routes
    import_routes(app)

    return app


app = create_app()

# socket.io wrapper
socket_app = ASGIApp(
    sio,
    other_asgi_app=app,
    socketio_path="/ws",
)


# -----------------------------------------------------------------------------
# Lifecycle events
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    # infra
    initialize_caches(app)
    initialize_databases(app)

    # schema
    await create_db_and_tables()

    # external services
    await app.state.qdrant_store.connect()

    # AI Foundation — ensure MongoDB indexes for memory store
    try:
        from lib.core.container import container
        from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
        memory_store: MongoMemoryStore = container.resolve(MongoMemoryStore)
        await memory_store.ensure_indexes()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to init AI Foundation indexes: {e}")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await app.state.postgres_store.close()
    app.state.mongo_store.client.close()
    await app.state.qdrant_store.close()
