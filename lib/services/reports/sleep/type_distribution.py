from .queries import generate_type_distribution_query


class SleepTypeDistributionStatistics:
    @staticmethod
    def fetch(
        clickhouse_store,
        patient_id: str,
        start_datetime: str,
        end_datetime: str,
        days_covered: int,
    ) -> dict:
        query = generate_type_distribution_query(patient_id, start_datetime, end_datetime)
        rows = clickhouse_store.client.execute(query)

        total_duration = sum(row[1] for row in rows)

        distribution = {
            row[0]: {
                "duration_minutes": row[1],
                "percentage": (row[1] / total_duration) * 100 if total_duration else 0,
                "per_day_average_minutes": row[1] / days_covered if days_covered > 0 else 0,
            }
            for row in rows
        }

        return {
            "total_duration": total_duration,
            "per_day_average_total": total_duration / days_covered if days_covered > 0 else 0,
            "distribution": distribution,
        }
