from datetime import datetime
from typing import Optional
import os

from clickhouse_driver import Client

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "aihealth-clickhouse")
CLICKHOUSE_PORT = os.getenv("CLICKHOUSE_PORT", "9000")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = str(os.getenv("CLICKHOUSE_PASSWORD", ""))


class ClickHouseStore:
    def __init__(self):
        self.client = Client(
            host=CLICKHOUSE_HOST,
            port=int(CLICKHOUSE_PORT),
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD.strip(),
            send_receive_timeout=300,
        )
        self.create_database()

    def create_database(self):
        self.client.execute("CREATE DATABASE IF NOT EXISTS aihealth")

    def create_cgm_data_table(self):
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS aihealth.cgm_data (
            patient_id String,
            time DateTime,
            glucose_level Float32,
            record_type LowCardinality(String),
            source LowCardinality(String) DEFAULT 'unknown',
            INDEX idx_record_type record_type TYPE set(100) GRANULARITY 4,
            INDEX idx_source source TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, time, source, record_type);
        """)

    def create_fitness_data_table(self):
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS aihealth.fitness_data (
            patient_id String,
            type LowCardinality(String),
            source_name LowCardinality(String),
            source_platform LowCardinality(String),
            unit LowCardinality(String),
            value Float64,
            start_datetime DateTime,
            end_datetime DateTime64(3),
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, start_datetime, source_name);
        """)

    def create_sleep_data_table(self):
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS aihealth.sleep_data (
            patient_id String,
            type LowCardinality(String),
            source_name LowCardinality(String),
            source_platform LowCardinality(String),
            sleep_duration Float64,
            sleep_start_time DateTime,
            sleep_end_time DateTime64(3),
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, sleep_start_time, source_name);
        """)

    def create_vitals_data_table(self):
        self.client.execute("""
        CREATE TABLE IF NOT EXISTS aihealth.vitals_data (
            patient_id String,
            vital_id String DEFAULT '',
            type LowCardinality(String),
            value Float64,
            time DateTime,
            source_name LowCardinality(String) DEFAULT '',
            source_platform LowCardinality(String) DEFAULT '',
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, time, source_name);
        """)

    def create_all_tables(self):
        self.create_cgm_data_table()
        self.create_fitness_data_table()
        self.create_sleep_data_table()
        self.create_vitals_data_table()

    def migrate_to_optimized_types(self):
        """One-time migration: String→LowCardinality + non-key DateTime→DateTime64(3).

        ORDER BY key columns (time, start_datetime, sleep_start_time) cannot be
        ALTERed — those need table recreation in a maintenance window.
        """
        alterations = [
            # cgm_data (time is ORDER BY key — skip)
            "ALTER TABLE aihealth.cgm_data MODIFY COLUMN record_type LowCardinality(String)",
            "ALTER TABLE aihealth.cgm_data MODIFY COLUMN source LowCardinality(String)",
            # fitness_data (start_datetime is ORDER BY key — skip)
            "ALTER TABLE aihealth.fitness_data MODIFY COLUMN end_datetime DateTime64(3)",
            "ALTER TABLE aihealth.fitness_data MODIFY COLUMN type LowCardinality(String)",
            "ALTER TABLE aihealth.fitness_data MODIFY COLUMN source_name LowCardinality(String)",
            "ALTER TABLE aihealth.fitness_data MODIFY COLUMN source_platform LowCardinality(String)",
            "ALTER TABLE aihealth.fitness_data MODIFY COLUMN unit LowCardinality(String)",
            # sleep_data (sleep_start_time is ORDER BY key — skip)
            "ALTER TABLE aihealth.sleep_data MODIFY COLUMN sleep_end_time DateTime64(3)",
            "ALTER TABLE aihealth.sleep_data MODIFY COLUMN type LowCardinality(String)",
            "ALTER TABLE aihealth.sleep_data MODIFY COLUMN source_name LowCardinality(String)",
            "ALTER TABLE aihealth.sleep_data MODIFY COLUMN source_platform LowCardinality(String)",
            # vitals_data (time is ORDER BY key — skip)
            "ALTER TABLE aihealth.vitals_data MODIFY COLUMN type LowCardinality(String)",
            "ALTER TABLE aihealth.vitals_data MODIFY COLUMN source_name LowCardinality(String)",
            "ALTER TABLE aihealth.vitals_data MODIFY COLUMN source_platform LowCardinality(String)",
        ]
        for stmt in alterations:
            self.client.execute(stmt, settings={"mutations_sync": 2})

    def write_data(self, table_name, data):
        if not data:
            return
        columns = list(data[0].keys())
        values = [tuple(record[c] for c in columns) for record in data]
        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"
        self.client.execute(query, values)

    def delete_vitals_by_vital_id(self, patient_id: str, vital_id: str):
        query = f"""
        ALTER TABLE aihealth.vitals_data
        DELETE WHERE patient_id = '{patient_id}' AND vital_id = '{vital_id}'
        """
        self.client.execute(query, settings={"mutations_sync": 1})

    # -- Vitals query helpers -----------------------------------------------

    def query_vitals(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        types: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        conditions = [f"patient_id = '{patient_id}'"]
        if start_time:
            conditions.append(f"time >= toDateTime('{start_time}')")
        if end_time:
            conditions.append(f"time <= toDateTime('{end_time}')")
        if types:
            type_list = ", ".join(f"'{t}'" for t in types)
            conditions.append(f"type IN ({type_list})")
        where = " AND ".join(conditions)

        count_query = f"SELECT count() FROM aihealth.vitals_data FINAL WHERE {where}"
        total = self.client.execute(count_query)[0][0]

        data_query = f"""
        SELECT vital_id, type, value, time, source_name, source_platform
        FROM aihealth.vitals_data FINAL
        WHERE {where}
        ORDER BY time DESC
        LIMIT {limit} OFFSET {offset}
        """
        rows = self.client.execute(data_query)
        return [
            {
                "vital_id": r[0], "type": r[1], "value": r[2],
                "time": r[3], "source_name": r[4], "source_platform": r[5],
            }
            for r in rows
        ], total

    def query_vitals_summary(
        self,
        patient_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        query = f"""
        SELECT
            toDate(time) AS date,
            type,
            avg(value) AS avg_value,
            min(value) AS min_value,
            max(value) AS max_value,
            count() AS reading_count
        FROM aihealth.vitals_data FINAL
        WHERE patient_id = '{patient_id}'
            AND time >= toDateTime('{start_time}')
            AND time <= toDateTime('{end_time}')
        GROUP BY date, type
        ORDER BY date DESC, type
        """
        rows = self.client.execute(query)
        return [
            {
                "date": str(r[0]), "type": r[1],
                "avg": round(r[2], 1), "min": round(r[3], 1),
                "max": round(r[4], 1), "count": r[5],
            }
            for r in rows
        ]

    def query_vitals_latest(self, patient_id: str) -> list[dict]:
        query = f"""
        SELECT type, value, time, source_name
        FROM aihealth.vitals_data FINAL
        WHERE patient_id = '{patient_id}'
        ORDER BY time DESC
        LIMIT 1 BY type
        """
        rows = self.client.execute(query)
        return [
            {"type": r[0], "value": round(r[1], 2), "time": r[2], "source_name": r[3]}
            for r in rows
        ]

    # -- Generic helpers ----------------------------------------------------

    def query_data(self, query):
        try:
            return self.client.execute(query)
        except Exception as e:
            print(f"Error executing query: {e}")
            return []

    def delete_data(self, table_name, condition):
        query = f"ALTER TABLE {table_name} DELETE WHERE {condition}"
        self.client.execute(query, settings={"mutations_sync": 1})

    def clear_all_data(self, table_name):
        self.client.execute(f"TRUNCATE TABLE {table_name}")


def get_clickhouse_store() -> ClickHouseStore:
    return ClickHouseStore()
