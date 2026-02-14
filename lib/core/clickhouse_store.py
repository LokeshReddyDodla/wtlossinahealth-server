from datetime import datetime
from typing import Optional

from clickhouse_driver import Client
from decouple import config

# Read ClickHouse URL and credentials from env
CLICKHOUSE_HOST = config("CLICKHOUSE_HOST", default="localhost")
CLICKHOUSE_PORT = config("CLICKHOUSE_PORT", default="9000")
CLICKHOUSE_USER = config("CLICKHOUSE_USER", default="default")
CLICKHOUSE_PASSWORD = str(config("CLICKHOUSE_PASSWORD", default=""))


class ClickHouseStore:
    def __init__(self):
        self.client = Client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD.strip(),
            send_receive_timeout=300,
        )
        self.create_database()

    def create_database(self):
        create_db_query = """
        CREATE DATABASE IF NOT EXISTS aihealth
        """
        self.client.execute(create_db_query)

    def create_cgm_data_table(self):
        create_table_query = """
        CREATE TABLE IF NOT EXISTS aihealth.cgm_data (
            patient_id String,
            time DateTime,
            glucose_level Float32,
            record_type String,
            source String DEFAULT 'unknown',
            INDEX idx_record_type record_type TYPE set(100) GRANULARITY 4,
            INDEX idx_source source TYPE set(100) GRANULARITY 4
        ) ENGINE = MergeTree()
        ORDER BY (patient_id, time);
        """
        self.client.execute(create_table_query)

    def create_fitness_data_table(self):
        create_table_query = """
        CREATE TABLE IF NOT EXISTS aihealth.fitness_data (
            patient_id String,
            type String,
            source_name String,
            source_platform String,
            unit String,
            value Float64,
            start_datetime DateTime,
            end_datetime DateTime,
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = MergeTree()
        ORDER BY (patient_id, start_datetime);
        """
        self.client.execute(create_table_query)

    def create_sleep_data_table(self):
        create_table_query = """
        CREATE TABLE IF NOT EXISTS aihealth.sleep_data (
            patient_id String,
            type String,
            source_name String,
            source_platform String,
            sleep_duration Float64,
            sleep_start_time DateTime,
            sleep_end_time DateTime,
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = MergeTree()
        ORDER BY (patient_id, sleep_start_time);
        """
        self.client.execute(create_table_query)

    def create_all_tables(self):
        self.create_cgm_data_table()
        self.create_fitness_data_table()
        self.create_sleep_data_table()

    def write_data(self, table_name, data):
        if not data:
            return
        columns = list(data[0].keys())
        values = [tuple(record[c] for c in columns) for record in data]
        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"
        self.client.execute(query, values)

    @staticmethod
    def _fmt(dt: datetime) -> str:
        """ClickHouse-safe DateTime format"""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def delete_existing_cgm_data(
        self,
        table_name: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
        source: Optional[str] = None,
    ):
        start = self._fmt(start_time)
        end = self._fmt(end_time)

        source_condition = f"AND source = '{source}'" if source else ""
        query = f"""
        ALTER TABLE {table_name}
        DELETE WHERE
            patient_id = '{patient_id}'
            AND time >= toDateTime('{start}')
            AND time <= toDateTime('{end}')
            {source_condition}
        """
        self.client.execute(query, settings={"mutations_sync": 1})

    def delete_existing_fitness_data(
        self,
        table_name: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
        source_name: Optional[str] = None,
    ):
        start = self._fmt(start_time)
        end = self._fmt(end_time)

        if source_name:
            condition = f"AND source_name = '{source_name}'"
        else:
            condition = "AND source_name != 'manual'"

        query = f"""
        ALTER TABLE {table_name}
        DELETE WHERE
            patient_id = '{patient_id}'
            AND start_datetime >= toDateTime('{start}')
            AND start_datetime <= toDateTime('{end}')
            {condition}
        """

        self.client.execute(query, settings={"mutations_sync": 1})

    def delete_existing_sleep_data(
        self,
        table_name: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
        source_name: Optional[str] = None,
    ):
        start = self._fmt(start_time)
        end = self._fmt(end_time)

        if source_name:
            condition = f"AND source_name = '{source_name}'"
        else:
            condition = "AND source_name != 'manual'"

        query = f"""
        ALTER TABLE {table_name}
        DELETE WHERE
            patient_id = '{patient_id}'
            AND sleep_start_time >= toDateTime('{start}')
            AND sleep_start_time <= toDateTime('{end}')
            {condition}
        """

        self.client.execute(query, settings={"mutations_sync": 1})

    def query_data(self, query):
        try:
            result = self.client.execute(query)
            return result
        except Exception as e:
            print(f"Error executing query: {e}")
            return []

    def delete_data(self, table_name, condition):
        query = f"ALTER TABLE {table_name} DELETE WHERE {condition}"
        self.client.execute(query, settings={"mutations_sync": 1})

    def clear_all_data(self, table_name):
        query = f"TRUNCATE TABLE {table_name}"
        self.client.execute(query)


def get_clickhouse_store() -> ClickHouseStore:
    return ClickHouseStore()
