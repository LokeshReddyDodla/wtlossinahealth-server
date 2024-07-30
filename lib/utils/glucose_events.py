from typing import Any, Dict
import pandas as pd

from rest_server.cgm.api_schema import (
    GlucoseRangeStats,
    GlucoseSummaryStats,
    HyperEvent,
    HypoEvent,
)


def execute_query(clickhouse_store, query: str) -> pd.DataFrame:
    data = clickhouse_store.client.execute(query)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["Device_Timestamp", "Glucose_Level"])
    df["Device Timestamp"] = pd.to_datetime(df["Device_Timestamp"])
    return df


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


def calculate_glucose_events(
    clickhouse_store,
    patient_id,
    from_date_str,
    to_date_str,
    hyper_threshold=180,
    hypo_threshold=70,
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

    hyper_events_metrics = process_hyper_events(df, threshold=hyper_threshold)
    hypo_events_metrics = process_hypo_events(df, threshold=hypo_threshold)

    return {**hyper_events_metrics, **hypo_events_metrics}


def calculate_glucose_summary_stats(df: pd.DataFrame) -> GlucoseSummaryStats:
    total_readings = len(df)
    average_glucose = df["Glucose_Level"].mean()
    glucose_stddev = df["Glucose_Level"].std()
    gmi = 3.31 + 0.02392 * average_glucose
    gmi_mmol = gmi * 10.93
    glucose_variability = (
        (glucose_stddev / average_glucose) * 100 if average_glucose else 0
    )

    return GlucoseSummaryStats(
        average_glucose=average_glucose,
        gmi=gmi,
        gmi_mmol=gmi_mmol,
        glucose_variability=glucose_variability,
    )


def calculate_glucose_range_stats(df: pd.DataFrame) -> GlucoseRangeStats:
    total_readings = len(df)
    below_54 = (df["Glucose_Level"] < 54).sum() / total_readings * 100
    below_70_above_54 = (
        ((df["Glucose_Level"] >= 54) & (df["Glucose_Level"] < 70)).sum()
        / total_readings
        * 100
    )
    in_target_70_180 = (
        ((df["Glucose_Level"] >= 70) & (df["Glucose_Level"] <= 180)).sum()
        / total_readings
        * 100
    )
    above_180_below_250 = (
        ((df["Glucose_Level"] > 180) & (df["Glucose_Level"] < 250)).sum()
        / total_readings
        * 100
    )
    above_250 = (df["Glucose_Level"] >= 250).sum() / total_readings * 100

    return GlucoseRangeStats(
        below_54=below_54,
        below_70_above_54=below_70_above_54,
        in_target_70_180=in_target_70_180,
        above_180_below_250=above_180_below_250,
        above_250=above_250,
    )
