from typing import Any, Dict
import pandas as pd
from lib.schemas.glucose_stats import HypoEvent
from lib.utils.glucose.events import execute_query


def fetch_hypo_stats(clickhouse_store, patient_id, from_date_str, to_date_str):
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
        if row["Glucose_Level"] < threshold:
            if current_hypo_event is None:
                current_hypo_event = {
                    "start_time": row["Device_Timestamp"],
                    "lowest_glucose_level": row["Glucose_Level"],
                }
            else:
                current_hypo_event["lowest_glucose_level"] = min(
                    current_hypo_event["lowest_glucose_level"],
                    row["Glucose_Level"],
                )
        else:
            if current_hypo_event is not None:
                duration = (
                    row["Device_Timestamp"] - current_hypo_event["start_time"]
                ).total_seconds() / 60
                hypo_events.append(
                    HypoEvent(
                        **current_hypo_event,
                        end_time=row["Device_Timestamp"],
                        duration=duration,
                    )
                )
                current_hypo_event = None

    if current_hypo_event is not None:
        duration = (
            df.iloc[-1]["Device_Timestamp"] - current_hypo_event["start_time"]
        ).total_seconds() / 60
        hypo_events.append(
            HypoEvent(
                **current_hypo_event,
                end_time=df.iloc[-1]["Device_Timestamp"],
                duration=duration,
            )
        )

    total_hypo_duration = sum(event.duration for event in hypo_events)
    average_hypo_duration = (
        total_hypo_duration / len(hypo_events) if hypo_events else 0
    )
    hypo_events_count = len(hypo_events)

    return {
        "total_hypo_duration": total_hypo_duration,
        "average_hypo_duration": average_hypo_duration,
        "hypo_events": hypo_events,
        "hypo_events_count": hypo_events_count,
    }
