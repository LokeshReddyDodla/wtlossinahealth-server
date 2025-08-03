from lib.schemas.cgm_stats import HypoStats, RapidDropStats
from lib.utils.cgm.events import CGMEventsProcessor, execute_query


class HypoStatsFetcher(CGMEventsProcessor):
    def __init__(self, buffer: int = 5):
        super().__init__(threshold=70, buffer=buffer)

    def fetch(
        self, clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> HypoStats:
        query = f"""
        SELECT
            time AS Device_Timestamp,
            glucose_level AS Glucose_Level
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{patient_id}'
            AND time >= '{start_date_str}'
            AND time <= '{end_date_str}'
        ORDER BY time
        """
        df = execute_query(clickhouse_store, query)
        if df.empty:
            return HypoStats(
                total_hypo_duration=0,
                average_hypo_duration=0,
                hypo_events_count=0,
                hypo_events=[],
                rapid_drop_stats=RapidDropStats(
                    total_drop_duration=0,
                    average_drop_duration=0,
                    drop_events_count=0,
                    drop_events=[],
                ),
            )

        processed_events = self.process_events(df, event_type="hypo")
        rapid_drops = self.process_rapid_drops(df)

        return HypoStats(
            total_hypo_duration=processed_events["total_hypo_duration"],
            average_hypo_duration=processed_events["average_hypo_duration"],
            hypo_events_count=processed_events["hypo_events_count"],
            hypo_events=processed_events["hypo_events"],
            rapid_drop_stats=rapid_drops,
        )
