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
            record_type String
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
            end_datetime DateTime
        ) ENGINE = MergeTree()
        ORDER BY (patient_id, start_datetime);
        """
        self.client.execute(create_table_query)

    def create_all_tables(self):
        self.create_cgm_data_table()
        self.create_fitness_data_table()

    def write_data(self, table_name, data):
        if not data:
            return
        columns = ", ".join(data[0].keys())
        values = ", ".join(
            f"({', '.join(map(repr, record.values()))})" for record in data
        )
        query = f"INSERT INTO {table_name} ({columns}) VALUES {values}"
        self.client.execute(query)

    def delete_existing_cgm_data(
        self,
        table_name: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
    ):
        query = f"""
        ALTER TABLE {table_name} DELETE WHERE patient_id = '{patient_id}' AND time BETWEEN '{start_time}' AND '{end_time}'
        """
        self.client.execute(query)

    def delete_existing_fitness_data(
        self,
        table_name: str,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
        source_name: Optional[str] = None,
    ):
        if source_name:
            query = f"""
            ALTER TABLE {table_name} DELETE 
            WHERE patient_id = '{patient_id}' 
            AND start_datetime BETWEEN '{start_time}' AND '{end_time}' 
            AND source_name = '{source_name}'
            """
        else:
            query = f"""
            ALTER TABLE {table_name} DELETE 
            WHERE patient_id = '{patient_id}' 
            AND start_datetime BETWEEN '{start_time}' AND '{end_time}' 
            AND source_name != 'manual'
            """
        self.client.execute(query)

    def query_data(self, query):
        try:
            result = self.client.execute(query)
            return result
        except Exception as e:
            print(f"Error executing query: {e}")
            return []

    def delete_data(self, table_name, condition):
        query = f"ALTER TABLE {table_name} DELETE WHERE {condition}"
        self.client.execute(query)

    def clear_all_data(self, table_name):
        query = f"TRUNCATE TABLE {table_name}"
        self.client.execute(query)


def get_clickhouse_store() -> ClickHouseStore:
    return ClickHouseStore()
