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

    # Gamification — seed achievements catalog
    try:
        from lib.core.container import container
        from lib.services.gamification.achievement_seeder import AchievementSeeder
        from lib.core.postgres_store import PostgresStore
        seeder = AchievementSeeder(container.resolve(PostgresStore))
        await seeder.seed()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to seed achievements: {e}")

    # Product Bot — ensure conversation indexes
    try:
        from lib.core.container import container
        analytics_col = container.resolve("product_bot_conversations_collection")
        await analytics_col.create_index([("session_id", 1), ("created_at", -1)], name="session_time_idx")
        await analytics_col.create_index([("created_at", -1)], name="created_idx")
        await analytics_col.create_index("created_at", name="analytics_ttl_idx", expireAfterSeconds=90 * 24 * 3600)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to init product bot indexes: {e}")

    # Profile Agent — validate config against schema and ensure Mongo index.
    try:
        from lib.services.profile_agent.introspection import assert_valid_config
        assert_valid_config()
        from lib.core.container import container
        from lib.services.profile_agent import ProfileAgentService
        svc: ProfileAgentService = container.resolve(ProfileAgentService)
        await svc.ensure_indexes()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed profile_agent init: {e}")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    # Flush buffered Langfuse events before exit, or the last batch is lost.
    try:
        import logging
        from lib.ai_foundation.models.gateway import ModelGateway
        from lib.core.container import container
        container.resolve(ModelGateway).flush()
    except Exception:
        logging.getLogger(__name__).warning("Langfuse flush on shutdown failed", exc_info=True)
    await app.state.postgres_store.close()
    app.state.mongo_store.client.close()
    await app.state.qdrant_store.close()
