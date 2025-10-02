from typing import Any, Dict

import pandas as pd

from lib.schemas.cgm_stats import (
    HyperEvent,
    HypoEvent,
    RapidDropStats,
    RapidSpikeStats,
)


def execute_query(clickhouse_store, query: str) -> pd.DataFrame:
    data = clickhouse_store.client.execute(query)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["device_timestamp", "glucose"])
    df["device_timestamp"] = pd.to_datetime(df["device_timestamp"])
    return df


class CGMEventsProcessor:
    def __init__(self, threshold: int, buffer: int = 0):
        self.threshold = threshold
        self.buffer = buffer

    def process_events(
        self, df: pd.DataFrame, event_type: str
    ) -> Dict[str, Any]:
        events = []
        current_event = None

        threshold = (
            self.threshold + self.buffer
            if event_type == "hyper"
            else self.threshold - self.buffer
        )

        for _, row in df.iterrows():
            if (event_type == "hyper" and row["glucose"] > threshold) or (
                event_type == "hypo" and row["glucose"] < threshold
            ):
                if current_event is None:
                    current_event = {
                        "start_time": row["device_timestamp"],
                        f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose": row[
                            "glucose"
                        ],
                    }
                else:
                    current_event[
                        f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose"
                    ] = (
                        max(
                            current_event[
                                f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose"
                            ],
                            row["glucose"],
                        )
                        if event_type == "hyper"
                        else min(
                            current_event[
                                f"{'peak' if event_type == 'hyper' else 'lowest'}_glucose"
                            ],
                            row["glucose"],
                        )
                    )
            else:
                if current_event is not None:
                    duration_minutes = (
                        row["device_timestamp"] - current_event["start_time"]
                    ).total_seconds() / 60
                    events.append(
                        HyperEvent(
                            **current_event,
                            end_time=row["device_timestamp"],
                            duration_minutes=duration_minutes,
                        )
                        if event_type == "hyper"
                        else HypoEvent(
                            **current_event,
                            end_time=row["device_timestamp"],
                            duration_minutes=duration_minutes,
                        )
                    )
                    current_event = None

        if current_event is not None:
            duration_minutes = (
                df.iloc[-1]["device_timestamp"] - current_event["start_time"]
            ).total_seconds() / 60
            events.append(
                HyperEvent(
                    **current_event,
                    end_time=df.iloc[-1]["device_timestamp"],
                    duration_minutes=duration_minutes,
                )
                if event_type == "hyper"
                else HypoEvent(
                    **current_event,
                    end_time=df.iloc[-1]["device_timestamp"],
                    duration_minutes=duration_minutes,
                )
            )

        total_duration_minutes = sum(
            event.duration_minutes for event in events
        )
        average_duration_minutes = (
            total_duration_minutes / len(events) if events else 0
        )
        events_count = len(events)

        return {
            f"total_{event_type}_duration_minutes": total_duration_minutes,
            f"average_{event_type}_duration_minutes": average_duration_minutes,
            f"{event_type}_events": events,
            f"{event_type}_events_count": events_count,
        }

    def process_rapid_spikes(self, df: pd.DataFrame) -> RapidSpikeStats:
        spikes = []
        current_spike = None

        for i in range(1, len(df)):
            time_diff = (
                df.iloc[i]["device_timestamp"]
                - df.iloc[i - 1]["device_timestamp"]
            ).total_seconds() / 60
            glucose_diff = df.iloc[i]["glucose"] - df.iloc[i - 1]["glucose"]

            if glucose_diff > 20 and time_diff <= 15:
                if current_spike is None:
                    current_spike = {
                        "start_time": df.iloc[i - 1]["device_timestamp"],
                        "initial_glucose": df.iloc[i - 1]["glucose"],
                        "peak_glucose": df.iloc[i]["glucose"],
                        "peak_glucose_time": df.iloc[i]["device_timestamp"],
                    }
                else:
                    if df.iloc[i]["glucose"] > current_spike["peak_glucose"]:
                        current_spike["peak_glucose"] = df.iloc[i]["glucose"]
                        current_spike["peak_glucose_time"] = df.iloc[i][
                            "device_timestamp"
                        ]
            else:
                if current_spike is not None:
                    duration_minutes = (
                        df.iloc[i - 1]["device_timestamp"]
                        - current_spike["start_time"]
                    ).total_seconds() / 60
                    if duration_minutes >= 60:
                        spikes.append(
                            {
                                **current_spike,
                                "end_time": df.iloc[i - 1]["device_timestamp"],
                                "duration_minutes": duration_minutes,
                            }
                        )
                    current_spike = None

        if current_spike is not None:
            duration_minutes = (
                df.iloc[-1]["device_timestamp"] - current_spike["start_time"]
            ).total_seconds() / 60
            if duration_minutes >= 60:
                spikes.append(
                    {
                        **current_spike,
                        "end_time": df.iloc[-1]["device_timestamp"],
                        "duration_minutes": duration_minutes,
                    }
                )

        total_spike_duration_minutes = sum(
            spike["duration_minutes"] for spike in spikes
        )
        average_spike_duration_minutes = (
            total_spike_duration_minutes / len(spikes) if spikes else 0
        )
        spikes_count = len(spikes)

        return RapidSpikeStats(
            total_spike_duration_minutes=total_spike_duration_minutes,
            average_spike_duration_minutes=average_spike_duration_minutes,
            spike_events=spikes,
            spike_events_count=spikes_count,
        )

    def process_rapid_drops(self, df: pd.DataFrame) -> RapidDropStats:
        drops = []
        current_drop = None

        for i in range(1, len(df)):
            time_diff = (
                df.iloc[i]["device_timestamp"]
                - df.iloc[i - 1]["device_timestamp"]
            ).total_seconds() / 60
            glucose_diff = df.iloc[i - 1]["glucose"] - df.iloc[i]["glucose"]

            if glucose_diff > 25 and time_diff <= 30:
                if current_drop is None:
                    current_drop = {
                        "start_time": df.iloc[i - 1]["device_timestamp"],
                        "initial_glucose": df.iloc[i - 1]["glucose"],
                        "lowest_glucose": df.iloc[i]["glucose"],
                        "lowest_glucose_time": df.iloc[i]["device_timestamp"],
                    }
                else:
                    if df.iloc[i]["glucose"] < current_drop["lowest_glucose"]:
                        current_drop["lowest_glucose"] = df.iloc[i]["glucose"]
                        current_drop["lowest_glucose_time"] = df.iloc[i][
                            "device_timestamp"
                        ]
            else:
                if current_drop is not None:
                    duration_minutes = (
                        df.iloc[i - 1]["device_timestamp"]
                        - current_drop["start_time"]
                    ).total_seconds() / 60
                    if duration_minutes >= 30:
                        drops.append(
                            {
                                **current_drop,
                                "end_time": df.iloc[i - 1]["device_timestamp"],
                                "duration_minutes": duration_minutes,
                            }
                        )
                    current_drop = None

        if current_drop is not None:
            duration_minutes = (
                df.iloc[-1]["device_timestamp"] - current_drop["start_time"]
            ).total_seconds() / 60
            if duration_minutes >= 30:
                drops.append(
                    {
                        **current_drop,
                        "end_time": df.iloc[-1]["device_timestamp"],
                        "duration_minutes": duration_minutes,
                    }
                )

        total_drop_duration_minutes = sum(
            drop["duration_minutes"] for drop in drops
        )
        average_drop_duration_minutes = (
            total_drop_duration_minutes / len(drops) if drops else 0
        )
        drops_count = len(drops)

        return RapidDropStats(
            total_drop_duration_minutes=total_drop_duration_minutes,
            average_drop_duration_minutes=average_drop_duration_minutes,
            drop_events=drops,
            drop_events_count=drops_count,
        )
