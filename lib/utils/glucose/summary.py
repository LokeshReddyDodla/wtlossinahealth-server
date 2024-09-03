from datetime import datetime
from typing import List

import pandas as pd
from lib.utils.glucose.queries import (
    generate_avg_glucose_reading_by_date_query,
    generate_glucose_stats_query,
)
from lib.schemas.glucose_stats import AGPPoint, GlucoseSummaryStats


class GlucoseSummaryStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> GlucoseSummaryStats:
        query = generate_glucose_stats_query(
            patient_id, from_date_str, to_date_str
        )
        result = clickhouse_store.client.execute(query)

        average_glucose = result[0][0] if result else 0.0
        glucose_stddev = result[0][1] if result else 0.0

        highest_glucose = result[0][2] if result else 0.0
        highest_glucose_date = result[0][3] if result else datetime.min

        lowest_glucose = result[0][4] if result else 0.0
        lowest_glucose_date = result[0][5] if result else datetime.min

        gmi = 3.31 + 0.02392 * average_glucose
        gmi_mmol = gmi * 10.93
        glucose_variability = (
            (glucose_stddev / average_glucose) * 100 if average_glucose else 0
        )

        agp_points = GlucoseSummaryStatsFetcher.fetch_agp_points(
            clickhouse_store, patient_id, from_date_str, to_date_str
        )

        return GlucoseSummaryStats(
            average_glucose=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability=glucose_variability,
            highest_glucose=highest_glucose,
            highest_glucose_date=highest_glucose_date,
            lowest_glucose=lowest_glucose,
            lowest_glucose_date=lowest_glucose_date,
            agp_points=agp_points,
        )

    @staticmethod
    def fetch_daily_average_glucose(
        clickhouse_store, patient_id, from_date, to_date
    ):
        query = generate_avg_glucose_reading_by_date_query(
            patient_id,
            from_date.strftime("%Y-%m-%dT00:00:00"),
            to_date.strftime("%Y-%m-%dT23:59:59"),
        )
        results = clickhouse_store.client.execute(query)
        # Convert results into a dictionary mapping date to average glucose
        return {row[0]: row[1] for row in results}

    @staticmethod
    def fetch_agp_points(
        clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> List[AGPPoint]:
        query = f"""
        SELECT
            formatDateTime(time, '%H:00') AS hour,
            quantile(0.10)(glucose_level) AS tenth_percentile,
            quantile(0.25)(glucose_level) AS twenty_fifth_percentile,
            quantile(0.50)(glucose_level) AS median,
            quantile(0.75)(glucose_level) AS seventy_fifth_percentile,
            quantile(0.90)(glucose_level) AS ninetieth_percentile
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{patient_id}'
            AND time >= '{from_date_str}'
            AND time <= '{to_date_str}'
        GROUP BY hour
        ORDER BY hour
        """
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
