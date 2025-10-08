from lib.schemas.cgm_stats import HyperStats, RapidSpikeStats
from lib.utils.cgm.events import CGMEventsProcessor, execute_query


class HyperStatsFetcher(CGMEventsProcessor):
    def __init__(self, buffer: int = 5):
        super().__init__(threshold=180, buffer=buffer)

    def fetch(
        self, clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> HyperStats:
        query = f"""
        SELECT
            time AS device_timestamp,
            glucose_level AS glucose_mgdl
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
            return HyperStats(
                total_hyper_duration_minutes=0,
                average_hyper_duration_minutes=0,
                hyper_events_count=0,
                hyper_events=[],
                rapid_spike_stats=RapidSpikeStats(
                    total_spike_duration_minutes=0,
                    average_spike_duration_minutes=0,
                    spike_events_count=0,
                    spike_events=[],
                ),
            )

        processed_events = self.process_events(df, event_type="hyper")
        rapid_spikes = self.process_rapid_spikes(df)

        return HyperStats(
            total_hyper_duration_minutes=processed_events[
                "total_hyper_duration_minutes"
            ],
            average_hyper_duration_minutes=processed_events[
                "average_hyper_duration_minutes"
            ],
            hyper_events_count=processed_events["hyper_events_count"],
            hyper_events=processed_events["hyper_events"],
            rapid_spike_stats=rapid_spikes,
        )
