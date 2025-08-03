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
    df = pd.DataFrame(data, columns=["Device_Timestamp", "Glucose_Level"])
    df["Device_Timestamp"] = pd.to_datetime(df["Device_Timestamp"])
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
            if (
                event_type == "hyper" and row["Glucose_Level"] > threshold
            ) or (event_type == "hypo" and row["Glucose_Level"] < threshold):
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

    def process_rapid_spikes(self, df: pd.DataFrame) -> RapidSpikeStats:
        spikes = []
        current_spike = None

        for i in range(1, len(df)):
            time_diff = (
                df.iloc[i]["Device_Timestamp"]
                - df.iloc[i - 1]["Device_Timestamp"]
            ).total_seconds() / 60
            glucose_diff = (
                df.iloc[i]["Glucose_Level"] - df.iloc[i - 1]["Glucose_Level"]
            )

            if glucose_diff > 20 and time_diff <= 15:
                if current_spike is None:
                    current_spike = {
                        "start_time": df.iloc[i - 1]["Device_Timestamp"],
                        "initial_glucose_level": df.iloc[i - 1][
                            "Glucose_Level"
                        ],
                        "peak_glucose_level": df.iloc[i]["Glucose_Level"],
                        "peak_glucose_time": df.iloc[i]["Device_Timestamp"],
                    }
                else:
                    if (
                        df.iloc[i]["Glucose_Level"]
                        > current_spike["peak_glucose_level"]
                    ):
                        current_spike["peak_glucose_level"] = df.iloc[i][
                            "Glucose_Level"
                        ]
                        current_spike["peak_glucose_time"] = df.iloc[i][
                            "Device_Timestamp"
                        ]
            else:
                if current_spike is not None:
                    duration = (
                        df.iloc[i - 1]["Device_Timestamp"]
                        - current_spike["start_time"]
                    ).total_seconds() / 60
                    if duration >= 60:
                        spikes.append(
                            {
                                **current_spike,
                                "end_time": df.iloc[i - 1]["Device_Timestamp"],
                                "duration": duration,
                            }
                        )
                    current_spike = None

        if current_spike is not None:
            duration = (
                df.iloc[-1]["Device_Timestamp"] - current_spike["start_time"]
            ).total_seconds() / 60
            if duration >= 60:
                spikes.append(
                    {
                        **current_spike,
                        "end_time": df.iloc[-1]["Device_Timestamp"],
                        "duration": duration,
                    }
                )

        total_spike_duration = sum(spike["duration"] for spike in spikes)
        average_spike_duration = (
            total_spike_duration / len(spikes) if spikes else 0
        )
        spikes_count = len(spikes)

        return RapidSpikeStats(
            total_spike_duration=total_spike_duration,
            average_spike_duration=average_spike_duration,
            spike_events=spikes,
            spike_events_count=spikes_count,
        )

    def process_rapid_drops(self, df: pd.DataFrame) -> RapidDropStats:
        drops = []
        current_drop = None

        for i in range(1, len(df)):
            time_diff = (
                df.iloc[i]["Device_Timestamp"]
                - df.iloc[i - 1]["Device_Timestamp"]
            ).total_seconds() / 60
            glucose_diff = (
                df.iloc[i - 1]["Glucose_Level"] - df.iloc[i]["Glucose_Level"]
            )

            if glucose_diff > 25 and time_diff <= 30:
                if current_drop is None:
                    current_drop = {
                        "start_time": df.iloc[i - 1]["Device_Timestamp"],
                        "initial_glucose_level": df.iloc[i - 1][
                            "Glucose_Level"
                        ],
                        "lowest_glucose_level": df.iloc[i]["Glucose_Level"],
                        "lowest_glucose_time": df.iloc[i]["Device_Timestamp"],
                    }
                else:
                    if (
                        df.iloc[i]["Glucose_Level"]
                        < current_drop["lowest_glucose_level"]
                    ):
                        current_drop["lowest_glucose_level"] = df.iloc[i][
                            "Glucose_Level"
                        ]
                        current_drop["lowest_glucose_time"] = df.iloc[i][
                            "Device_Timestamp"
                        ]
            else:
                if current_drop is not None:
                    duration = (
                        df.iloc[i - 1]["Device_Timestamp"]
                        - current_drop["start_time"]
                    ).total_seconds() / 60
                    if duration >= 30:
                        drops.append(
                            {
                                **current_drop,
                                "end_time": df.iloc[i - 1]["Device_Timestamp"],
                                "duration": duration,
                            }
                        )
                    current_drop = None

        if current_drop is not None:
            duration = (
                df.iloc[-1]["Device_Timestamp"] - current_drop["start_time"]
            ).total_seconds() / 60
            if duration >= 30:
                drops.append(
                    {
                        **current_drop,
                        "end_time": df.iloc[-1]["Device_Timestamp"],
                        "duration": duration,
                    }
                )

        total_drop_duration = sum(drop["duration"] for drop in drops)
        average_drop_duration = (
            total_drop_duration / len(drops) if drops else 0
        )
        drops_count = len(drops)

        return RapidDropStats(
            total_drop_duration=total_drop_duration,
            average_drop_duration=average_drop_duration,
            drop_events=drops,
            drop_events_count=drops_count,
        )
