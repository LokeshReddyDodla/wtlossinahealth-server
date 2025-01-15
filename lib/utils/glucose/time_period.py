from datetime import datetime
from datetime import time as datetime_time
from typing import Any, Dict

from lib.schemas.glucose_stats import TimePeriodStats
from lib.utils.glucose.queries import (generate_glucose_readings_by_date_query,
                                       generate_time_period_stats_query)


class GlucoseTimePeriodStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> Dict[str, TimePeriodStats]:
        query = generate_time_period_stats_query(
            patient_id, start_date_str, end_date_str
        )
        results = clickhouse_store.client.execute(query)

        time_period_stats = {}
        for row in results:
            time_period = row[0]
            if time_period != "unknown":
                time_period_stats[time_period] = TimePeriodStats(
                    from_time=row[1],
                    to_time=row[2],
                    average_glucose=row[3],
                    highest_glucose=row[4],
                    lowest_glucose=row[5],
                    out_of_range_percentage=row[6],
                )

        return time_period_stats
