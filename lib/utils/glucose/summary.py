import math
from datetime import datetime
from typing import List

import pandas as pd
from numpy import NaN

from lib.schemas.glucose_stats import AGPPoint, GlucoseSummaryStats
from lib.utils.glucose.queries import (
    generate_agp_points_query, generate_avg_glucose_reading_by_date_query,
    generate_glucose_stats_query)
from lib.utils.validation_utils import validate_float


class GlucoseSummaryStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> GlucoseSummaryStats:
        query = generate_glucose_stats_query(
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

        glycemic_estimate = validate_float(
            (average_glucose - lowest_glucose)
            / (highest_glucose - lowest_glucose)
            if highest_glucose != lowest_glucose
            else 0.0
        )
        coefficient_of_variation = validate_float(
            (glucose_stddev / average_glucose) * 100
            if average_glucose
            else 0.0
        )

        standard_deviation = validate_float(glucose_stddev)

        agp_points = GlucoseSummaryStatsFetcher.fetch_agp_points(
            clickhouse_store, patient_id, start_date_str, end_date_str
        )

        return GlucoseSummaryStats(
            average_glucose=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability=glucose_variability,
            glycemic_estimate=glycemic_estimate,
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
        query = generate_avg_glucose_reading_by_date_query(
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
        query = generate_agp_points_query(
            patient_id, start_date_str, end_date_str
        )
        agp_result = clickhouse_store.client.execute(query)
        agp_points = [
            AGPPoint(
                hour=row[0],
                median=row[1],
                tenth_percentile=row[2],
                twenty_fifth_percentile=row[3],
                seventy_fifth_percentile=row[4],
                ninetieth_percentile=row[5],
            )
            for row in agp_result
        ]
        return agp_points
