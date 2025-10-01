from lib.core.clickhouse_store import ClickHouseStore
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import Base, PostgresStore, engine
from lib.core.qdrant_store import QdrantStore


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create tables in ClickHouse
    clickhouse_store = ClickHouseStore()
    clickhouse_store.create_all_tables()


def initialize_databases(app):
    app.state.postgres_store = PostgresStore()
    app.state.mongo_store = MongoStore()
    app.state.clickhouse_store = ClickHouseStore()
    app.state.qdrant_store = QdrantStore()
