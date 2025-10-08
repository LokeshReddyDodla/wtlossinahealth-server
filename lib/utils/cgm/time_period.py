from typing import Dict
from pydantic import BaseModel

from lib.schemas.cgm_stats import CGMTimePeriodStats
from lib.utils.cgm.queries import generate_time_period_cgm_stats_query
from lib.utils.validation_utils import validate_float


class GlucoseTimePeriodStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> Dict[str, CGMTimePeriodStats]:
        query = generate_time_period_cgm_stats_query(
            patient_id, start_date_str, end_date_str
        )
        results = clickhouse_store.client.execute(query)

        time_period_stats = {}
        for row in results:
            time_period = row[0]
            if time_period != "unknown":
                time_period_stats[time_period] = CGMTimePeriodStats(
                    from_time=row[1],
                    to_time=row[2],
                    average_glucose_mgdl=validate_float(row[3]),
                    highest_glucose_mgdl=validate_float(row[4]),
                    lowest_glucose_mgdl=validate_float(row[5]),
                    out_of_range_percent=validate_float(row[6]),
                )

        return time_period_stats
