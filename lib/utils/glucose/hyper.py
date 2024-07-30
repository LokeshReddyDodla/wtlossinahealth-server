from typing import Any, Dict
import pandas as pd
from lib.utils.glucose_events import execute_query
from rest_server.cgm.api_schema import HyperEvent


def fetch_hyper_stats(
    clickhouse_store, patient_id, from_date_str, to_date_str
):
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
        if row["Glucose_Level"] > threshold:
            if current_hyper_event is None:
                current_hyper_event = {
                    "start_time": row["Device_Timestamp"],
                    "peak_glucose_level": row["Glucose_Level"],
                }
            else:
                current_hyper_event["peak_glucose_level"] = max(
                    current_hyper_event["peak_glucose_level"],
                    row["Glucose_Level"],
                )
        else:
            if current_hyper_event is not None:
                duration = (
                    row["Device_Timestamp"] - current_hyper_event["start_time"]
                ).total_seconds() / 60
                hyper_events.append(
                    HyperEvent(
                        **current_hyper_event,
                        end_time=row["Device_Timestamp"],
                        duration=duration,
                    )
                )
                current_hyper_event = None

    if current_hyper_event is not None:
        duration = (
            df.iloc[-1]["Device_Timestamp"] - current_hyper_event["start_time"]
        ).total_seconds() / 60
        hyper_events.append(
            HyperEvent(
                **current_hyper_event,
                end_time=df.iloc[-1]["Device_Timestamp"],
                duration=duration,
            )
        )

    total_hyper_duration = sum(event.duration for event in hyper_events)
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
