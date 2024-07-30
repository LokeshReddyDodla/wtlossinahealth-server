from datetime import datetime
from typing import Any, Dict, List
import pandas as pd
from lib.utils.glucose.events import (
    HyperStatsFetcher,
    HypoStatsFetcher,
    execute_query,
)
from lib.utils.glucose.range import GlucoseRangeStatsFetcher
from lib.utils.glucose.summary import GlucoseSummaryStatsFetcher
from rest_server.cgm.api_schema import (
    GlucoseLevelStats,
    GlucoseRangeStats,
    GlucoseSummaryStats,
    HyperStats,
    HypoStats,
)


class PeriodicStatsProcessor:
    def __init__(self, clickhouse_store, patient_id):
        self.clickhouse_store = clickhouse_store
        self.patient_id = patient_id

    def fetch_glucose_readings_by_date(
        self, from_date_str: str, to_date_str: str
    ) -> List[Dict[str, Any]]:
        query = f"""
        SELECT
            time AS Device_Timestamp,
            glucose_level AS Glucose_Level
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{self.patient_id}'
            AND time >= '{from_date_str}'
            AND time <= '{to_date_str}'
        ORDER BY time
        """
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        readings = [
            {"Device_Timestamp": row[0], "Glucose_Level": row[1]}
            for row in data
        ]
        return readings

    def fetch_avg_glucose_readings_by_hour(
        self, from_date_str: str, to_date_str: str
    ) -> List[Dict[str, Any]]:
        query = f"""
        SELECT
            formatDateTime(time, '%H:00') AS hour,
            avg(glucose_level) AS avg_glucose_level
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{self.patient_id}'
            AND time >= '{from_date_str}'
            AND time <= '{to_date_str}'
        GROUP BY hour
        ORDER BY hour
        """
        data = self.clickhouse_store.client.execute(query)
        if not data:
            return []

        grouped = [
            {"Device_Timestamp": row[0], "Glucose_Level": row[1]}
            for row in data
        ]
        return grouped

    def process(
        self, periods: List[Dict[str, datetime]], include_readings=False
    ):
        stats = {}

        for period in periods:
            from_date_str = period["from_date"].strftime("%Y-%m-%dT%H:%M:%S")
            to_date_str = period["to_date"].strftime("%Y-%m-%dT%H:%M:%S")

            glucose_summary = GlucoseSummaryStatsFetcher.fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            glucose_range = GlucoseRangeStatsFetcher.fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            hyper_stats = HyperStatsFetcher().fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            hypo_stats = HypoStatsFetcher().fetch(
                self.clickhouse_store,
                self.patient_id,
                from_date_str,
                to_date_str,
            )

            glucose_range_stats = GlucoseRangeStats(
                below_54=glucose_range["below_54"],
                below_70_above_54=glucose_range["below_70_above_54"],
                in_target_70_180=glucose_range["in_target_70_180"],
                above_180_below_250=glucose_range["above_180_below_250"],
                above_250=glucose_range["above_250"],
            )

            glucose_summary_stats = GlucoseSummaryStats(
                average_glucose=glucose_summary["average_glucose"],
                gmi=glucose_summary["gmi"],
                gmi_mmol=glucose_summary["gmi_mmol"],
                glucose_variability=glucose_summary["glucose_variability"],
            )

            hyper_stats = HyperStats(
                total_hyper_duration=hyper_stats["total_hyper_duration"],
                average_hyper_duration=hyper_stats["average_hyper_duration"],
                hyper_events_count=hyper_stats["hyper_events_count"],
                hyper_events=hyper_stats["hyper_events"],
            )

            hypo_stats = HypoStats(
                total_hypo_duration=hypo_stats["total_hypo_duration"],
                average_hypo_duration=hypo_stats["average_hypo_duration"],
                hypo_events_count=hypo_stats["hypo_events_count"],
                hypo_events=hypo_stats["hypo_events"],
            )

            glucose_readings = None

            if "date" in period:
                period_key = period["date"]
                if include_readings:
                    glucose_readings = self.fetch_glucose_readings_by_date(
                        from_date_str, to_date_str
                    )
            elif "week_no" in period:
                period_key = f"Week {period['week_no']}"
                if include_readings:
                    glucose_readings = self.fetch_avg_glucose_readings_by_hour(
                        from_date_str, to_date_str
                    )
            else:
                period_key = "overall"

            stats[period_key] = GlucoseLevelStats(
                glucose_readings=glucose_readings,
                glucose_summary_stats=glucose_summary_stats,
                glucose_range_stats=glucose_range_stats,
                hyper_stats=hyper_stats,
                hypo_stats=hypo_stats,
            )
        return stats
