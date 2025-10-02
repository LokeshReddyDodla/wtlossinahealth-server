from typing import Any, Dict

import pandas as pd

from lib.schemas.cgm_stats import HypoEvent
from lib.utils.cgm.events import execute_query


def fetch_hypo_stats(
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
            "total_hypo_duration": 0,
            "average_hypo_duration": 0,
            "hypo_events": [],
            "hypo_events_count": 0,
        }

    return process_hypo_events(df, threshold=70)


def process_hypo_events(df: pd.DataFrame, threshold: int) -> Dict[str, Any]:
    hypo_events = []
    current_hypo_event = None

    for _, row in df.iterrows():
        if row["glucose"] < threshold:
            if current_hypo_event is None:
                current_hypo_event = {
                    "start_time": row["device_timestamp"],
                    "lowest_glucose": row["glucose"],
                }
            else:
                current_hypo_event["lowest_glucose"] = min(
                    current_hypo_event["lowest_glucose"],
                    row["glucose"],
                )
        else:
            if current_hypo_event is not None:
                duration_minutes = (
                    row["device_timestamp"] - current_hypo_event["start_time"]
                ).total_seconds() / 60
                hypo_events.append(
                    HypoEvent(
                        **current_hypo_event,
                        end_time=row["device_timestamp"],
                        duration_minutes=duration_minutes,
                    )
                )
                current_hypo_event = None

    if current_hypo_event is not None:
        duration_minutes = (
            df.iloc[-1]["device_timestamp"] - current_hypo_event["start_time"]
        ).total_seconds() / 60
        hypo_events.append(
            HypoEvent(
                **current_hypo_event,
                end_time=df.iloc[-1]["device_timestamp"],
                duration_minutes=duration_minutes,
            )
        )

    total_hypo_duration_minutes = sum(
        event.duration_minutes for event in hypo_events
    )
    average_hypo_duration_minutes = (
        total_hypo_duration_minutes / len(hypo_events) if hypo_events else 0
    )
    hypo_events_count = len(hypo_events)

    return {
        "total_hypo_duration_minutes": total_hypo_duration_minutes,
        "average_hypo_duration_minutes": average_hypo_duration_minutes,
        "hypo_events": hypo_events,
        "hypo_events_count": hypo_events_count,
    }
