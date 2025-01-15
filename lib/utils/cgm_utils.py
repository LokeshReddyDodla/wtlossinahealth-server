from datetime import datetime, timedelta

import pandas as pd


class CGMDataUtils:
    def __init__(self, clickhouse_store):
        self.clickhouse_store = clickhouse_store

    async def is_data_available_and_continuous(
        self, patient_id: str, start_datetime: datetime, end_datetime: datetime
    ) -> bool:
        start_date = start_datetime.date()
        end_date = end_datetime.date()

        query = f"""
        SELECT count() as cnt, min(toDate(time)) as min_date, max(toDate(time)) as max_date
        FROM aihealth.cgm_data
        WHERE patient_id = '{patient_id}' AND toDate(time) BETWEEN toDate('{start_date}') AND toDate('{end_date}')
        """
        result = self.clickhouse_store.query_data(query)
        if result and len(result) > 0:
            cnt, min_date, max_date = result[0]
            if cnt > 0 and min_date <= start_date and max_date >= end_date:
                return True
        return False

    # Function to align a date to the nearest previous Saturday
    def align_to_previous_saturday(self, date: datetime) -> datetime:
        days_to_subtract = (date.weekday() + 2) % 7  # 2 = Saturday
        return date - timedelta(days=days_to_subtract)

    # Function to generate all valid 2-week report periods
    def generate_all_report_periods(
        self,
        cgm_data: pd.DataFrame,
        period_length: int = 14,
        min_data_points: int = 10,
    ) -> list[tuple[datetime, datetime]]:
        if cgm_data.empty:
            return []

        # Sort data by timestamp
        cgm_data = cgm_data.sort_values("Device Timestamp")

        # Extract the earliest and latest dates
        earliest_date = cgm_data["Device Timestamp"].min()
        latest_date = cgm_data["Device Timestamp"].max()

        # Initialize variables
        report_periods = []
        current_date = self.align_to_previous_saturday(earliest_date)

        while current_date <= latest_date:
            # Define the report period
            start_date = current_date
            end_date = start_date + timedelta(days=period_length - 1)

            # Filter data for the current period
            period_data = cgm_data[
                (cgm_data["Device Timestamp"] >= start_date)
                & (cgm_data["Device Timestamp"] <= end_date)
            ]

            # Check if the period has sufficient data
            if len(period_data) >= min_data_points:
                report_periods.append((start_date, end_date))

            # Move to the next 2-week period
            current_date += timedelta(days=period_length)

        return report_periods
