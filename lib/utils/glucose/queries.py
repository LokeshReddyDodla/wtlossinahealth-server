def generate_agp_points_query(patient_id, from_date, to_date) -> str:
    return f"""
    SELECT
        formatDateTime(time, '%H:00') AS hour,
        quantile(0.10)(glucose_level) AS tenth_percentile,
        quantile(0.25)(glucose_level) AS twenty_fifth_percentile,
        quantile(0.50)(glucose_level) AS median,
        quantile(0.75)(glucose_level) AS seventy_fifth_percentile,
        quantile(0.90)(glucose_level) AS ninetieth_percentile
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    GROUP BY hour
    ORDER BY hour
    """


def generate_glucose_level_query(
    patient_id, from_date, to_date, range_condition, alias
):
    return f"""
    SELECT
        COUNT(*) AS total_readings,
        SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) AS condition_met,
        (SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) / COUNT(*)) * 100 AS {alias}
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    """


def generate_glucose_stats_query(patient_id, from_date, to_date):
    return f"""
    SELECT
        AVG(glucose_level) AS average_glucose,
        STDDEV_SAMP(glucose_level) AS glucose_stddev,
        MAX(glucose_level) AS highest_glucose,
        MAX(time) AS highest_glucose_date,
        MIN(glucose_level) AS lowest_glucose,
        MIN(time) AS lowest_glucose_date
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    """


def generate_glucose_readings_by_date_query(patient_id, from_date, to_date):
    return f"""
    SELECT
        time AS Device_Timestamp,
        glucose_level AS Glucose_Level
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    ORDER BY time
    """


def generate_avg_glucose_readings_by_hour_query(
    patient_id, from_date, to_date
):
    return f"""
    SELECT
        formatDateTime(time, '%H:00') AS hour,
        avg(glucose_level) AS avg_glucose_level
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    GROUP BY hour
    ORDER BY hour
    """


def generate_avg_glucose_reading_by_date_query(patient_id, from_date, to_date):
    return f"""
    SELECT
        toDate(time) AS date,
        AVG(glucose_level) AS average_glucose
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    GROUP BY date
    ORDER BY date;
    """


def generate_glucose_readings_around_meal_query(
    patient_id, meal_time, before_minutes=30, after_minutes=30
):
    return f"""
    SELECT
        time AS reading_time,
        glucose_level AS glucose_level
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time BETWEEN 
            toDateTime('{meal_time}') - INTERVAL {before_minutes} MINUTE
            AND 
            toDateTime('{meal_time}') + INTERVAL {after_minutes} MINUTE
    ORDER BY time;
    """
