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


def generate_night_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Per-night sleep stats. Segments are grouped into nights on a noon-anchored
    day (a night spanning midnight stays one group), then aggregated. Asleep time
    is deep+light+rem only — never the overlapping sleep_in_bed envelope, which
    would double-count. Bedtime/wake are measured in minutes from that night's
    noon anchor, so times after midnight don't wrap. Nights with no staged sleep
    are dropped."""
    return f"""
    SELECT
        count() AS nights,
        sum(asleep_min) AS total_asleep,
        avg(asleep_min) AS avg_asleep,
        max(asleep_min) AS longest_night,
        min(asleep_min) AS shortest_night,
        stddevPop(bed_min) AS bedtime_sd,
        stddevPop(wake_min) AS wake_sd
    FROM (
        SELECT
            toDate(sleep_start_time - INTERVAL 12 HOUR) AS sleep_date,
            (toUnixTimestamp(toDateTime(min(sleep_start_time)))
                - toUnixTimestamp(toDateTime(sleep_date) + INTERVAL 12 HOUR)) / 60.0 AS bed_min,
            (toUnixTimestamp(toDateTime(max(sleep_end_time)))
                - toUnixTimestamp(toDateTime(sleep_date) + INTERVAL 12 HOUR)) / 60.0 AS wake_min,
            sumIf(sleep_duration, type IN ('sleep_deep', 'sleep_light', 'sleep_rem')) AS asleep_min
        FROM aihealth.sleep_data FINAL
        WHERE patient_id = '{patient_id}'
            AND sleep_start_time >= '{start_datetime}'
            AND sleep_end_time <= '{end_datetime}'
            AND type != 'sleep_awake'
            AND (toHour(sleep_start_time) >= 18 OR toHour(sleep_end_time) < 12)
        GROUP BY sleep_date
        HAVING asleep_min > 0
    )
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
