from lib.core.clickhouse_store import ClickHouseStore
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import Base, PostgresStore, engine
from lib.initializers.weight_loss_agent_setup import initialize_weight_loss_agent_data


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

    # Initialize weight loss agent data
    import asyncio
    postgres_store = app.state.postgres_store
    asyncio.create_task(initialize_weight_loss_agent_data(postgres_store))
