from typing import Any, Dict

import pandas as pd

from lib.schemas.cgm_stats import HyperEvent
from lib.utils.cgm.events import execute_query


def fetch_hyper_stats(
    clickhouse_store, patient_id, start_date_str, end_date_str
):
    query = f"""
    SELECT
        time AS device_timestamp,
        glucose_level AS glucose
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
        return {
            "total_hyper_duration": 0,
            "average_hyper_duration": 0,
            "hyper_events": [],
            "hyper_events_count": 0,
        }

    return process_hyper_events(df, threshold=180)


def process_hyper_events(df: pd.DataFrame, threshold: int) -> Dict[str, Any]:
    hyper_events = []
    current_hyper_event = None

    for _, row in df.iterrows():
        if row["glucose"] > threshold:
            if current_hyper_event is None:
                current_hyper_event = {
                    "start_time": row["device_timestamp"],
                    "peak_glucose": row["glucose"],
                }
            else:
                current_hyper_event["peak_glucose"] = max(
                    current_hyper_event["peak_glucose"],
                    row["glucose"],
                )
        else:
            if current_hyper_event is not None:
                duration_minutes = (
                    row["device_timestamp"] - current_hyper_event["start_time"]
                ).total_seconds() / 60
                hyper_events.append(
                    HyperEvent(
                        **current_hyper_event,
                        end_time=row["device_timestamp"],
                        duration_minutes=duration_minutes,
                    )
                )
                current_hyper_event = None

    if current_hyper_event is not None:
        duration_minutes = (
            df.iloc[-1]["device_timestamp"] - current_hyper_event["start_time"]
        ).total_seconds() / 60
        hyper_events.append(
            HyperEvent(
                **current_hyper_event,
                end_time=df.iloc[-1]["device_timestamp"],
                duration_minutes=duration_minutes,
            )
        )

    total_hyper_duration = sum(
        event.duration_minutes for event in hyper_events
    )
    average_hyper_duration = (
        total_hyper_duration / len(hyper_events) if hyper_events else 0
    )
    hyper_events_count = len(hyper_events)

    return {
        "total_hyper_duration": total_hyper_duration,
        "average_hyper_duration": average_hyper_duration,
        "hyper_events": hyper_events,
        "hyper_events_count": hyper_events_count,
    }
