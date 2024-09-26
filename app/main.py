from fastapi import FastAPI
from socketio import ASGIApp

from app.import_routes import import_routes
from lib.core.di_container import get_container
from lib.initializers.cache_setup import initialize_caches
from lib.initializers.db_setup import (create_db_and_tables,
                                       initialize_databases)
from lib.initializers.logger_setup import setup_logger
from lib.initializers.middleware_setup import setup_middlewares
from lib.services.socketio_service import sio

# Create fastAPI app
app = FastAPI()

# Add middlewares
setup_middlewares(app)

container = get_container()


###############################################################################
# Rest server startup hooks
###############################################################################
@app.on_event("startup")
async def startup_event() -> None:
    """
    Initialize modules and attach them to app
    """
    # Initialize caches
    initialize_caches(app)

    # Initialize databases
    initialize_databases(app)

    # Initialize logger
    setup_logger(app)

    # Import routes
    import_routes(app)

    # Create tables
    await create_db_and_tables()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Cleanup and close connections
    """
    await app.state.postgres_store.close()
    app.state.mongo_store.client.close()
    app.state.clickhouse_store.client.close()


socket_app = ASGIApp(sio, other_asgi_app=app, socketio_path="/ws")
