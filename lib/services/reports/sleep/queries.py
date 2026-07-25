"""ClickHouse query utilities for sleep report data."""


def generate_total_sessions_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    return f"""
    SELECT count() AS total_sessions
    FROM aihealth.sleep_data FINAL
    WHERE patient_id = '{patient_id}'
        AND sleep_start_time >= '{start_datetime}'
        AND sleep_end_time <= '{end_datetime}'
    """


def generate_duration_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    return f"""
    SELECT
        sum(sleep_duration) AS total_duration,
        avg(sleep_duration) AS avg_duration,
        max(sleep_duration) AS max_duration,
        min(sleep_duration) AS min_duration
    FROM aihealth.sleep_data FINAL
    WHERE patient_id = '{patient_id}'
        AND sleep_start_time >= '{start_datetime}'
        AND sleep_end_time <= '{end_datetime}'
    """


def generate_type_distribution_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    return f"""
    SELECT
        type,
        sum(sleep_duration) AS duration
    FROM aihealth.sleep_data FINAL
    WHERE patient_id = '{patient_id}'
        AND sleep_start_time >= '{start_datetime}'
        AND sleep_end_time <= '{end_datetime}'
    GROUP BY type
    """


def generate_timing_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Timing stats for nighttime sleep (start >= 18:00 or end < 12:00), excluding awake."""
    return f"""
    SELECT
        if(count() > 0, formatDateTime(min(sleep_start_time), '%H:%M:%S'), '') AS earliest_start,
        if(count() > 0, formatDateTime(max(sleep_end_time), '%H:%M:%S'), '') AS latest_end,
        if(count() > 0,
            formatDateTime(toDateTime(toUInt32(avg(toUnixTimestamp(toTime(sleep_start_time))))), '%H:%M:%S'),
            ''
        ) AS avg_start,
        if(count() > 0,
            formatDateTime(toDateTime(toUInt32(avg(toUnixTimestamp(toTime(sleep_end_time))))), '%H:%M:%S'),
            ''
        ) AS avg_end
    FROM aihealth.sleep_data FINAL
    WHERE patient_id = '{patient_id}'
        AND sleep_start_time >= '{start_datetime}'
        AND sleep_end_time <= '{end_datetime}'
        AND (toHour(sleep_start_time) >= 18 OR toHour(sleep_end_time) < 12)
        AND type != 'sleep_awake'
    """


def generate_quality_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    return f"""
    SELECT
        type,
        sum(sleep_duration) AS duration
    FROM aihealth.sleep_data FINAL
    WHERE patient_id = '{patient_id}'
        AND sleep_start_time >= '{start_datetime}'
        AND sleep_end_time <= '{end_datetime}'
    GROUP BY type
    """
