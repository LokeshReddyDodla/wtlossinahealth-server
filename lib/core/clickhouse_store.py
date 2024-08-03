from datetime import datetime
from typing import Optional
from clickhouse_driver import Client
from decouple import config

# Read ClickHouse URL and credentials from env
CLICKHOUSE_HOST = config("CLICKHOUSE_HOST", default="localhost")
CLICKHOUSE_PORT = config("CLICKHOUSE_PORT", default="9000")


class ClickHouseStore:
    def __init__(self):
        self.client = Client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT)
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

    def create_all_tables(self):
        self.create_cgm_data_table()

    def write_data(self, table_name, data):
        if not data:
            return
        columns = ", ".join(data[0].keys())
        values = ", ".join(
            f"({', '.join(map(repr, record.values()))})" for record in data
        )
        query = f"INSERT INTO {table_name} ({columns}) VALUES {values}"
        self.client.execute(query)

    def delete_existing_data(
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

    def get_last_uploaded_timestamp(
        self, table_name: str, patient_id: str
    ) -> Optional[datetime]:
        query = f"""
        SELECT max(time) as last_time
        FROM {table_name}
        WHERE patient_id = '{patient_id}'
        """

        result = self.client.execute(query)
        if (
            result
            and isinstance(result, list)
            and len(result) > 0
            and len(result[0]) > 0
        ):
            last_time_str = result[0][0]
            if last_time_str:
                return datetime.fromisoformat(last_time_str)
        return None

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
