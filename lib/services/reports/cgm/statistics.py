"""CGM summary statistics calculations."""

from datetime import datetime
from typing import Dict, List

import pandas as pd

from lib.schemas.cgm_stats import AGPPoint, CGMSummaryStats
from lib.utils.validation_utils import validate_float

from .queries import (
    generate_daily_avg_query,
    generate_hourly_agp_points_query,
    generate_summary_stats_query,
)


class CGMStatistics:
    """Static methods for calculating CGM summary statistics."""

    @staticmethod
    def fetch_summary_stats(
        clickhouse_store, patient_id: str, start_date_str: str, end_date_str: str
    ) -> CGMSummaryStats:
        """Fetch and calculate CGM summary statistics."""
        query = generate_summary_stats_query(patient_id, start_date_str, end_date_str)
        result = clickhouse_store.client.execute(query)

        average_glucose = validate_float(result[0][0] if result else 0.0)
        glucose_stddev = validate_float(result[0][1] if result else 0.0)

        highest_glucose = validate_float(result[0][2] if result else 0.0)
        highest_glucose_date = (
            result[0][3] if result and result[0][3] else datetime.min
        )

        lowest_glucose = validate_float(result[0][4] if result else 0.0)
        lowest_glucose_date = (
            result[0][5] if result and result[0][5] else datetime.min
        )

        gmi = validate_float(3.31 + 0.02392 * average_glucose)
        gmi_mmol = validate_float(gmi * 10.93)

        glucose_variability_percent = validate_float(
            (glucose_stddev / average_glucose) * 100 if average_glucose else 0.0
        )

        coefficient_of_variation_percent = glucose_variability_percent
        std_dev_glucose_mgdl = validate_float(glucose_stddev)

        agp_points = CGMStatistics.fetch_agp_points(
            clickhouse_store, patient_id, start_date_str, end_date_str
        )

        return CGMSummaryStats(
            average_glucose_mgdl=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability_percent=glucose_variability_percent,
            coefficient_of_variation_percent=coefficient_of_variation_percent,
            std_dev_glucose_mgdl=std_dev_glucose_mgdl,
            highest_glucose_mgdl=highest_glucose,
            highest_glucose_date=highest_glucose_date,
            lowest_glucose_mgdl=lowest_glucose,
            lowest_glucose_date=lowest_glucose_date,
            agp_points=agp_points,
        )

    @staticmethod
    def fetch_daily_average_glucose(
        clickhouse_store, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Dict[datetime, float]:
        """Fetch daily average glucose levels as a dictionary."""
        query = generate_daily_avg_query(
            patient_id,
            start_date.strftime("%Y-%m-%dT00:00:00"),
            end_date.strftime("%Y-%m-%dT23:59:59"),
        )
        results = clickhouse_store.client.execute(query)
        return {
            row[0]: validate_float(row[1])
            for row in results
            if row and row[1] is not None
        }

    @staticmethod
    def fetch_agp_points(
        clickhouse_store, patient_id: str, start_date_str: str, end_date_str: str
    ) -> List[AGPPoint]:
        """Fetch AGP (Ambulatory Glucose Profile) points."""
        query = generate_hourly_agp_points_query(patient_id, start_date_str, end_date_str)
        agp_result = clickhouse_store.client.execute(query)

        return [
            AGPPoint(
                hour=row[1],
                percentile_10_mgdl=validate_float(row[2]),
                percentile_25_mgdl=validate_float(row[3]),
                median_mgdl=validate_float(row[4]),
                percentile_75_mgdl=validate_float(row[5]),
                percentile_90_mgdl=validate_float(row[6]),
            )
            for row in agp_result
            if row
        ]
