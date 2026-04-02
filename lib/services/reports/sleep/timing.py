from .queries import generate_timing_stats_query


class SleepTimingStatistics:
    @staticmethod
    def fetch(
        clickhouse_store,
        patient_id: str,
        start_datetime: str,
        end_datetime: str,
    ) -> dict:
        query = generate_timing_stats_query(patient_id, start_datetime, end_datetime)
        result = clickhouse_store.client.execute(query)
        row = result[0] if result else (None, None, None, None)

        return {
            "earliest_start_time": row[0] or None,
            "latest_end_time": row[1] or None,
            "average_start_time": row[2] or None,
            "average_end_time": row[3] or None,
        }
