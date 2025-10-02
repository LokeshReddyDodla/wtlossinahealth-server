import math
from datetime import datetime
from typing import List

import pandas as pd

from lib.schemas.cgm_stats import AGPPoint, CGMSummaryStats
from lib.utils.cgm.queries import (
    generate_hourly_agp_points_cgm_query,
    generate_daily_avg_cgm_query,
    generate_summary_stats_cgm_query,
)
from lib.utils.validation_utils import validate_float


class CGMSummaryStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> CGMSummaryStats:
        query = generate_summary_stats_cgm_query(
            patient_id, start_date_str, end_date_str
        )
        result = clickhouse_store.client.execute(query)

        average_glucose = validate_float(result[0][0] if result else 0.0)
        glucose_stddev = validate_float(result[0][1] if result else 0.0)

        highest_glucose = validate_float(result[0][2] if result else 0.0)
        highest_glucose_date = result[0][3] if result else datetime.min

        lowest_glucose = validate_float(result[0][4] if result else 0.0)
        lowest_glucose_date = result[0][5] if result else datetime.min

        gmi = validate_float(3.31 + 0.02392 * average_glucose)
        gmi_mmol = validate_float(gmi * 10.93)
        glucose_variability = validate_float(
            (glucose_stddev / average_glucose) * 100
            if average_glucose
            else 0.0
        )

        coefficient_of_variation = validate_float(
            (glucose_stddev / average_glucose) * 100
            if average_glucose
            else 0.0
        )

        standard_deviation = validate_float(glucose_stddev)

        agp_points = CGMSummaryStatsFetcher.fetch_agp_points(
            clickhouse_store, patient_id, start_date_str, end_date_str
        )

        return CGMSummaryStats(
            average_glucose=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability=glucose_variability,
            coefficient_of_variation=coefficient_of_variation,
            standard_deviation=standard_deviation,
            highest_glucose=highest_glucose,
            highest_glucose_date=highest_glucose_date,
            lowest_glucose=lowest_glucose,
            lowest_glucose_date=lowest_glucose_date,
            agp_points=agp_points,
        )

    @staticmethod
    def fetch_daily_average_glucose(
        clickhouse_store, patient_id, start_date, end_date
    ):
        query = generate_daily_avg_cgm_query(
            patient_id,
            start_date.strftime("%Y-%m-%dT00:00:00"),
            end_date.strftime("%Y-%m-%dT23:59:59"),
        )
        results = clickhouse_store.client.execute(query)
        # Convert results into a dictionary mapping date to average glucose
        return {row[0]: row[1] for row in results}

    @staticmethod
    def fetch_agp_points(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> List[AGPPoint]:
        query = generate_hourly_agp_points_cgm_query(
            patient_id, start_date_str, end_date_str
        )
        agp_result = clickhouse_store.client.execute(query)
        agp_points = [
            AGPPoint(
                hour=row[1],
                percentile_10=row[2],
                percentile_25=row[3],
                median=row[4],
                percentile_75=row[5],
                percentile_90=row[6],
            )
            for row in agp_result
        ]

        return agp_points
