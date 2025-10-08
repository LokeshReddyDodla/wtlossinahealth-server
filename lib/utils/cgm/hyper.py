from typing import Any, Dict

import pandas as pd

from lib.schemas.cgm_stats import HyperEvent
from lib.utils.cgm.events import execute_query


def fetch_hyper_stats(
    clickhouse_store, patient_id, start_date_str, end_date_str
) -> Dict[str, Any]:
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
        return {
            "total_hyper_duration_minutes": 0,
            "average_hyper_duration_minutes": 0,
            "hyper_events": [],
            "hyper_events_count": 0,
        }

    return process_hyper_events(df, threshold=180)


def process_hyper_events(df: pd.DataFrame, threshold: int) -> Dict[str, Any]:
    hyper_events = []
    current_hyper_event = None

    for _, row in df.iterrows():
        if row["glucose_mgdl"] > threshold:
            if current_hyper_event is None:
                current_hyper_event = {
                    "start_time": row["device_timestamp"],
                    "peak_glucose": row["glucose_mgdl"],
                }
            else:
                current_hyper_event["peak_glucose"] = max(
                    current_hyper_event["peak_glucose"],
                    row["glucose_mgdl"],
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

    total_hyper_duration_minutes = sum(
        event.duration_minutes for event in hyper_events
    )
    average_hyper_duration_minutes = (
        total_hyper_duration_minutes / len(hyper_events) if hyper_events else 0
    )
    hyper_events_count = len(hyper_events)

    return {
        "total_hyper_duration_minutes": total_hyper_duration_minutes,
        "average_hyper_duration_minutes": average_hyper_duration_minutes,
        "hyper_events": hyper_events,
        "hyper_events_count": hyper_events_count,
    }
