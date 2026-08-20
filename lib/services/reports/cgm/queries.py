"""ClickHouse query builders for CGM data."""


def generate_hourly_agp_points_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query for hourly AGP (Ambulatory Glucose Profile) points."""
    return f"""
    SELECT
        toHour(time) AS hour_24,
        formatDateTime(time, '%I:00 %p') AS hour,
        quantile(0.10)(glucose_level) AS percentile_10,
        quantile(0.25)(glucose_level) AS percentile_25,
        quantile(0.50)(glucose_level) AS median,
        quantile(0.75)(glucose_level) AS percentile_75,
        quantile(0.90)(glucose_level) AS percentile_90
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY hour_24, hour
    ORDER BY hour_24
    """


def generate_range_coverage_query(
    patient_id: str, start_date: str, end_date: str, range_condition: str, alias: str
) -> str:
    """Generate query for glucose range coverage statistics."""
    return f"""
    SELECT
        COUNT(*) AS total_readings,
        SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) AS condition_met,
        IF(COUNT(*) = 0, 0, (SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) / COUNT(*)) * 100) AS {alias}
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    """


def generate_summary_stats_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query for CGM summary statistics."""
    return f"""
    SELECT
        AVG(glucose_level) AS average_glucose_mgdl,
        STDDEV_SAMP(glucose_level) AS glucose_stddev_mgdl,
        MAX(glucose_level) AS highest_glucose_mgdl,
        argMax(time, glucose_level) AS highest_glucose_date,
        MIN(glucose_level) AS lowest_glucose_mgdl,
        argMin(time, glucose_level) AS lowest_glucose_date
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    """


def generate_time_period_stats_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query for time period statistics (overnight, breakfast, lunch, dinner)."""
    return f"""
    SELECT
        CASE
            WHEN formatDateTime(time, '%H:%i') BETWEEN '00:00' AND '05:59' THEN 'overnight'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '06:00' AND '11:59' THEN 'breakfast'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '12:00' AND '17:59' THEN 'lunch'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '18:00' AND '23:59' THEN 'dinner'
            ELSE 'unknown'
        END AS time_period,
        CASE
            WHEN formatDateTime(time, '%H:%i') BETWEEN '00:00' AND '05:59' THEN '00:00:00'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '06:00' AND '11:59' THEN '06:00:00'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '12:00' AND '17:59' THEN '12:00:00'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '18:00' AND '23:59' THEN '18:00:00'
            ELSE NULL
        END AS from_time,
        CASE
            WHEN formatDateTime(time, '%H:%i') BETWEEN '00:00' AND '05:59' THEN '05:59:59'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '06:00' AND '11:59' THEN '11:59:59'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '12:00' AND '17:59' THEN '17:59:59'
            WHEN formatDateTime(time, '%H:%i') BETWEEN '18:00' AND '23:59' THEN '23:59:59'
            ELSE NULL
        END AS to_time,
        AVG(glucose_level) AS avg_glucose_mgdl,
        MAX(glucose_level) AS highest_glucose_mgdl,
        MIN(glucose_level) AS lowest_glucose_mgdl,
        SUM(CASE WHEN glucose_level < 70 OR glucose_level > 180 THEN 1 ELSE 0 END) / COUNT(*) * 100 AS out_of_range_percentage
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time IS NOT NULL
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY time_period, from_time, to_time
    ORDER BY time_period
    """


def generate_readings_in_range_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query to fetch all CGM readings in a date range."""
    return f"""
    SELECT
        time AS device_timestamp,
        glucose_level AS glucose_mgdl
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    ORDER BY time
    """


def generate_hourly_avg_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query for hourly average glucose levels."""
    return f"""
    SELECT
        toHour(time) AS hour_24,
        formatDateTime(time, '%I:00 %p') AS hour,
        avg(glucose_level) AS avg_glucose_mgdl
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY hour_24, hour
    ORDER BY hour_24
    """


def generate_daily_avg_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query for daily average glucose levels."""
    return f"""
    SELECT
        toDate(time) AS date,
        AVG(glucose_level) AS average_glucose_mgdl
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY date
    ORDER BY date;
    """


def generate_readings_window_query(
    patient_id: str, start: str, end: str
) -> tuple[str, dict]:
    """Query + params for all readings in a window, sorted by time.

    Parameterized because the bounds derive from stored meal payloads —
    execute as ``client.execute(query, params)``.
    """
    query = """
    SELECT
        time AS reading_time,
        glucose_level AS glucose_mgdl
    FROM
        aihealth.cgm_data FINAL
    WHERE
        patient_id = %(patient_id)s
        AND record_type = 'historic'
        AND time BETWEEN toDateTime(%(start)s) AND toDateTime(%(end)s)
    ORDER BY time;
    """
    return query, {"patient_id": patient_id, "start": start, "end": end}


def generate_trend_prev_window_query(patient_id: str, prev_start: str, prev_end: str) -> str:
    """Avg glucose + in-range count for the previous window. `prev_end` is
    exclusive (equals the current window's start) so the windows never overlap."""
    return f"""
    SELECT
        avg(glucose_level) AS avg_glucose,
        countIf(glucose_level >= 70 AND glucose_level <= 180) AS in_range,
        count() AS total
    FROM aihealth.cgm_data FINAL
    WHERE patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{prev_start}'
        AND time < '{prev_end}'
    """


def generate_nocturnal_dawn_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Nocturnal (00:00-05:59) hypo coverage + dawn rise in one pass."""
    return f"""
    SELECT
        countIf(glucose_level < 70 AND toHour(time) < 6) AS nocturnal_below,
        countIf(toHour(time) < 6) AS nocturnal_total,
        avgIf(glucose_level, toHour(time) >= 3 AND toHour(time) < 6) AS dawn_avg,
        avgIf(glucose_level, toHour(time) < 3) AS predawn_avg
    FROM aihealth.cgm_data FINAL
    WHERE patient_id = '{patient_id}'
        AND record_type = 'historic'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    """


def generate_sensor_active_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Median seconds between consecutive readings = the sensor's actual cadence,
    derived from data so any device (5-min, 15-min, ...) is scored on its own
    rate. Gaps over 1h are sensor-off dropouts, not cadence, so they're excluded.
    """
    return f"""
    SELECT median(gap_s)
    FROM (
        SELECT dateDiff('second',
                        lagInFrame(time, 1) OVER (
                            ORDER BY time ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
                        ),
                        time) AS gap_s
        FROM aihealth.cgm_data FINAL
        WHERE patient_id = '{patient_id}'
            AND record_type = 'historic'
            AND time >= '{start_date}'
            AND time <= '{end_date}'
    )
    WHERE gap_s > 0 AND gap_s <= 3600
    """


def generate_total_readings_count_query(patient_id: str, start_date: str, end_date: str) -> str:
    """Generate query to count total CGM readings in a date range."""
    return f"""
    SELECT COUNT(*) 
    FROM aihealth.cgm_data FINAL
    WHERE patient_id = '{patient_id}'
    AND record_type = 'historic'
    AND time >= '{start_date}'
    AND time <= '{end_date}'
    """
