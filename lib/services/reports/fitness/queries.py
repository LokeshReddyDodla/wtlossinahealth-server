"""Database query utilities for fitness report data."""


def generate_summary_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for summary statistics."""
    return f"""
    SELECT
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS total_steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS total_active_energy,
        SUM(dateDiff('minute', start_datetime, end_datetime)) AS total_active_duration,
        SUM(CASE WHEN type = 'DISTANCE_WALKING_RUNNING' THEN value ELSE 0 END) AS total_distance,
        SUM(CASE WHEN type = 'FLIGHTS_CLIMBED' THEN value ELSE 0 END) AS total_flights_climbed,
        SUM(CASE WHEN type = 'EXERCISE_TIME' THEN value ELSE 0 END) AS total_exercise_time
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND start_datetime >= '{start_datetime}'
        AND end_datetime <= '{end_datetime}'
    """


def generate_hourly_stats_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for hourly statistics."""
    return f"""
   WITH
        hours AS (
            SELECT number AS hour
            FROM numbers(24)
        )
    SELECT
        hours.hour,
        COALESCE(SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END), 0) AS steps,
        COALESCE(SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END), 0) AS active_energy,
        COALESCE(SUM(dateDiff('minute', start_datetime, end_datetime)), 0) AS active_duration,
        COALESCE(SUM(CASE WHEN type = 'DISTANCE_WALKING_RUNNING' THEN value ELSE 0 END), 0) AS distance,
        COALESCE(SUM(CASE WHEN type = 'FLIGHTS_CLIMBED' THEN value ELSE 0 END), 0) AS flights_climbed
    FROM
        hours
    LEFT JOIN (
        SELECT
            toHour(start_datetime) AS activity_hour,
            type,
            value,
            start_datetime,
            end_datetime
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND start_datetime >= '{start_datetime}'
            AND end_datetime <= '{end_datetime}'
    ) AS activity_data
    ON hours.hour = activity_data.activity_hour
    GROUP BY
        hours.hour
    ORDER BY
        hours.hour
    """


def generate_average_active_session_duration_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for average active session duration."""
    return f"""
    SELECT
        AVG(COALESCE(dateDiff('minute', start_datetime, end_datetime), 0)) AS average_active_session_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND start_datetime >= '{start_datetime}'
        AND end_datetime <= '{end_datetime}'
        AND type = 'ACTIVE_ENERGY_BURNED'
    """


def generate_activity_distribution_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for activity distribution by time of day."""
    return f"""
    SELECT
        CASE
            WHEN hour(start_datetime) BETWEEN 6 AND 12 THEN 'Morning'
            WHEN hour(start_datetime) BETWEEN 12 AND 18 THEN 'Afternoon'
            WHEN hour(start_datetime) BETWEEN 18 AND 24 THEN 'Evening'
            ELSE 'Night'
        END AS time_of_day,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', start_datetime, end_datetime)) AS active_duration,
        SUM(CASE WHEN type = 'DISTANCE_WALKING_RUNNING' THEN value ELSE 0 END) AS distance,
        SUM(CASE WHEN type = 'FLIGHTS_CLIMBED' THEN value ELSE 0 END) AS flights_climbed
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND start_datetime >= '{start_datetime}'
        AND end_datetime <= '{end_datetime}'
    GROUP BY
        time_of_day
    ORDER BY
        CASE
            WHEN time_of_day = 'Morning' THEN 1
            WHEN time_of_day = 'Afternoon' THEN 2
            WHEN time_of_day = 'Evening' THEN 3
            ELSE 4
        END
    """


def generate_peak_activity_time_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for peak activity time."""
    return f"""
    SELECT
        hour,
        max_steps,
        max_active_energy,
        max_distance
    FROM (
        SELECT
            formatDateTime(start_datetime, '%Y-%m-%d %H:00:00') AS hour,
            SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS max_steps,
            SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS max_active_energy,
            SUM(CASE WHEN type = 'DISTANCE_WALKING_RUNNING' THEN value ELSE 0 END) AS max_distance
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND start_datetime >= '{start_datetime}'
            AND end_datetime <= '{end_datetime}'
        GROUP BY
            hour
    ) AS hourly_data
    ORDER BY
        max_steps DESC, max_active_energy DESC
    LIMIT 1
    """


def generate_inactive_periods_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for inactive periods."""
    return f"""
    SELECT
        t1.end_datetime AS start_time,
        t2.start_datetime AS end_time,
        dateDiff('minute', t1.end_datetime, t2.start_datetime) AS inactive_duration
    FROM (
        SELECT
            start_datetime,
            end_datetime,
            type AS preceding_activity,
            toInt64(row_number() OVER (ORDER BY start_datetime)) AS rn
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND start_datetime >= toDateTime('{start_datetime}')
            AND end_datetime <= toDateTime('{end_datetime}')
    ) AS t1
    JOIN (
        SELECT
            start_datetime,
            end_datetime,
            type AS following_activity,
            toInt64(row_number() OVER (ORDER BY start_datetime)) AS rn
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND start_datetime >= toDateTime('{start_datetime}')
            AND end_datetime <= toDateTime('{end_datetime}')
    ) AS t2
    ON t1.rn = t2.rn - 1
    WHERE
        dateDiff('minute', t1.end_datetime, t2.start_datetime) > 60
    ORDER BY
        inactive_duration DESC
    """


def generate_daily_activity_metrics_query(
    patient_id: str, start_date: str, end_date: str
) -> str:
    """Per-day activity metrics grouped by date. Returns one row per day."""
    return f"""
    SELECT
        toDate(start_datetime) AS day,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(CASE WHEN type = 'DISTANCE_WALKING_RUNNING' THEN value ELSE 0 END) AS distance,
        SUM(CASE WHEN type = 'FLIGHTS_CLIMBED' THEN value ELSE 0 END) AS flights_climbed,
        SUM(CASE WHEN type = 'EXERCISE_TIME' THEN value ELSE 0 END) AS exercise_time
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND toDate(start_datetime) >= '{start_date}'
        AND toDate(start_datetime) <= '{end_date}'
        AND type IN ('STEPS', 'ACTIVE_ENERGY_BURNED', 'DISTANCE_WALKING_RUNNING',
                     'FLIGHTS_CLIMBED', 'EXERCISE_TIME')
    GROUP BY day
    ORDER BY day
    """


def generate_daily_detected_workouts_query(
    patient_id: str, start_date: str, end_date: str
) -> str:
    """Individual detected workout sessions per day (not aggregated by type)."""
    return f"""
    SELECT
        toDate(start_datetime) AS day,
        type,
        dateDiff('minute', start_datetime, end_datetime) AS duration_minutes,
        value AS calories
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND toDate(start_datetime) >= '{start_date}'
        AND toDate(start_datetime) <= '{end_date}'
        AND type NOT IN ('STEPS', 'ACTIVE_ENERGY_BURNED', 'DISTANCE_WALKING_RUNNING',
                         'FLIGHTS_CLIMBED', 'EXERCISE_TIME')
    ORDER BY day, start_datetime
    """


def generate_workouts_query(
    patient_id: str, start_datetime: str, end_datetime: str
) -> str:
    """Generate query for workout sessions."""
    return f"""
    SELECT
        type,
        count() AS session_count,
        SUM(dateDiff('minute', start_datetime, end_datetime)) AS total_duration,
        SUM(value) AS total_energy,
        any(source_platform) AS source
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND start_datetime >= '{start_datetime}'
        AND end_datetime <= '{end_datetime}'
        AND type NOT IN ('STEPS', 'ACTIVE_ENERGY_BURNED', 'DISTANCE_WALKING_RUNNING',
                         'FLIGHTS_CLIMBED', 'EXERCISE_TIME')
    GROUP BY type
    ORDER BY total_duration DESC
    """
