from typing import Any, Dict
import pandas as pd
from lib.schemas.glucose import HyperEvent, HyperStats, HypoEvent, HypoStats


def execute_query(clickhouse_store, query: str) -> pd.DataFrame:
    data = clickhouse_store.client.execute(query)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["Device_Timestamp", "Glucose_Level"])
    df["Device_Timestamp"] = pd.to_datetime(df["Device_Timestamp"])
    return df


class GlucoseEventsProcessor:
    def __init__(self, threshold: int):
        self.threshold = threshold

    def process_events(
        self, df: pd.DataFrame, event_type: str
    ) -> Dict[str, Any]:
        events = []
        current_event = None

        for _, row in df.iterrows():
            if (
                event_type == "hyper" and row["Glucose_Level"] > self.threshold
            ) or (
                event_type == "hypo" and row["Glucose_Level"] < self.threshold
            ):
                if current_event is None:
                    current_event = {
                        "start_time": row["Device_Timestamp"],
                        f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose_level": row[
                            "Glucose_Level"
                        ],
                    }
                else:
                    current_event[
                        f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose_level"
                    ] = (
                        max(
                            current_event[
                                f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose_level"
                            ],
                            row["Glucose_Level"],
                        )
                        if event_type == "hyper"
                        else min(
                            current_event[
                                f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose_level"
                            ],
                            row["Glucose_Level"],
                        )
                    )
            else:
                if current_event is not None:
                    duration = (
                        row["Device_Timestamp"] - current_event["start_time"]
                    ).total_seconds() / 60
                    events.append(
                        HyperEvent(
                            **current_event,
                            end_time=row["Device_Timestamp"],
                            duration=duration,
                        )
                        if event_type == "hyper"
                        else HypoEvent(
                            **current_event,
                            end_time=row["Device_Timestamp"],
                            duration=duration,
                        )
                    )
                    current_event = None

        if current_event is not None:
            duration = (
                df.iloc[-1]["Device_Timestamp"] - current_event["start_time"]
            ).total_seconds() / 60
            events.append(
                HyperEvent(
                    **current_event,
                    end_time=df.iloc[-1]["Device_Timestamp"],
                    duration=duration,
                )
                if event_type == "hyper"
                else HypoEvent(
                    **current_event,
                    end_time=df.iloc[-1]["Device_Timestamp"],
                    duration=duration,
                )
            )

        total_duration = sum(event.duration for event in events)
        average_duration = total_duration / len(events) if events else 0
        events_count = len(events)

        return {
            f"total_{event_type}_duration": total_duration,
            f"average_{event_type}_duration": average_duration,
            f"{event_type}_events": events,
            f"{event_type}_events_count": events_count,
        }


class HyperStatsFetcher(GlucoseEventsProcessor):
    def __init__(self):
        super().__init__(threshold=180)

    def fetch(
        self, clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> HyperStats:
        query = f"""
        SELECT
            time AS Device_Timestamp,
            glucose_level AS Glucose_Level
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{patient_id}'
            AND time >= '{from_date_str}'
            AND time <= '{to_date_str}'
        ORDER BY time
        """
        df = execute_query(clickhouse_store, query)
        if df.empty:
            return HyperStats(
                total_hyper_duration=0,
                average_hyper_duration=0,
                hyper_events_count=0,
                hyper_events=[],
            )

        processed_events = self.process_events(df, event_type="hyper")
        return HyperStats(
            total_hyper_duration=processed_events["total_hyper_duration"],
            average_hyper_duration=processed_events["average_hyper_duration"],
            hyper_events_count=processed_events["hyper_events_count"],
            hyper_events=processed_events["hyper_events"],
        )


class HypoStatsFetcher(GlucoseEventsProcessor):
    def __init__(self):
        super().__init__(threshold=70)

    def fetch(
        self, clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> HypoStats:
        query = f"""
        SELECT
            time AS Device_Timestamp,
            glucose_level AS Glucose_Level
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{patient_id}'
            AND time >= '{from_date_str}'
            AND time <= '{to_date_str}'
        ORDER BY time
        """
        df = execute_query(clickhouse_store, query)
        if df.empty:
            return HypoStats(
                total_hypo_duration=0,
                average_hypo_duration=0,
                hypo_events_count=0,
                hypo_events=[],
            )

        processed_events = self.process_events(df, event_type="hypo")
        return HypoStats(
            total_hypo_duration=processed_events["total_hypo_duration"],
            average_hypo_duration=processed_events["average_hypo_duration"],
            hypo_events_count=processed_events["hypo_events_count"],
            hypo_events=processed_events["hypo_events"],
        )
