from .queries import generate_duration_stats_query


class SleepDurationStatistics:
    @staticmethod
    def fetch(
        clickhouse_store,
        patient_id: str,
        start_datetime: str,
        end_datetime: str,
        days_covered: int,
    ) -> dict:
        query = generate_duration_stats_query(patient_id, start_datetime, end_datetime)
        result = clickhouse_store.client.execute(query)
        row = result[0] if result else (0, 0, 0, 0)

        total_duration = row[0] or 0
        per_day_avg_duration = total_duration / days_covered if days_covered > 0 else 0

        return {
            "total_duration": row[0],
            "average_duration": row[1],
            "per_day_average_duration": per_day_avg_duration,
            "longest_sleep": row[2],
            "shortest_sleep": row[3],
        }
