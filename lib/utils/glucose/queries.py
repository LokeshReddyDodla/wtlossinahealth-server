def generate_agp_points_query(patient_id, start_date, end_date) -> str:
    return f"""
    SELECT
        toHour(time) AS hour_24,
        formatDateTime(time, '%I:00 %p') AS hour,
        quantile(0.10)(glucose_level) AS tenth_percentile,
        quantile(0.25)(glucose_level) AS twenty_fifth_percentile,
        quantile(0.50)(glucose_level) AS median,
        quantile(0.75)(glucose_level) AS seventy_fifth_percentile,
        quantile(0.90)(glucose_level) AS ninetieth_percentile
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY hour_24, hour
    ORDER BY hour_24
    """


def generate_glucose_level_query(
    patient_id, start_date, end_date, range_condition, alias
):
    return f"""
    SELECT
        COUNT(*) AS total_readings,
        SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) AS condition_met,
        IF(COUNT(*) = 0, 0, (SUM(CASE WHEN {range_condition} THEN 1 ELSE 0 END) / COUNT(*)) * 100) AS {alias}
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    """


def generate_glucose_stats_query(patient_id, start_date, end_date):
    return f"""
    SELECT
        AVG(glucose_level) AS average_glucose,
        STDDEV_SAMP(glucose_level) AS glucose_stddev,
        MAX(glucose_level) AS highest_glucose,
        argMax(time, glucose_level) AS highest_glucose_date,
        MIN(glucose_level) AS lowest_glucose,
        argMin(time, glucose_level) AS lowest_glucose_date
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    """


def generate_time_period_stats_query(patient_id, start_date, end_date):
    return f"""
    SELECT
        CASE
            WHEN formatDateTime(time, '%H:%M') BETWEEN '00:00' AND '05:59' THEN 'overnight'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '06:00' AND '11:59' THEN 'breakfast'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '12:00' AND '17:59' THEN 'lunch'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '18:00' AND '23:59' THEN 'dinner'
            ELSE 'unknown'
        END AS time_period,
        CASE
            WHEN formatDateTime(time, '%H:%M') BETWEEN '00:00' AND '05:59' THEN '00:00:00'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '06:00' AND '11:59' THEN '06:00:00'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '12:00' AND '17:59' THEN '12:00:00'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '18:00' AND '23:59' THEN '18:00:00'
            ELSE NULL
        END AS from_time,
        CASE
            WHEN formatDateTime(time, '%H:%M') BETWEEN '00:00' AND '05:59' THEN '05:59:59'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '06:00' AND '11:59' THEN '11:59:59'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '12:00' AND '17:59' THEN '17:59:59'
            WHEN formatDateTime(time, '%H:%M') BETWEEN '18:00' AND '23:59' THEN '23:59:59'
            ELSE NULL
        END AS to_time,
        AVG(glucose_level) AS avg_sugar,
        MAX(glucose_level) AS highest_sugar,
        MIN(glucose_level) AS lowest_sugar,
        SUM(CASE WHEN glucose_level < 70 OR glucose_level > 180 THEN 1 ELSE 0 END) / COUNT(*) * 100 AS out_of_range_percentage
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time IS NOT NULL
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY time_period, from_time, to_time
    ORDER BY time_period
    """


def generate_glucose_readings_by_date_query(patient_id, start_date, end_date):
    return f"""
    SELECT
        time AS Device_Timestamp,
        glucose_level AS Glucose_Level
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    ORDER BY time
    """


def generate_avg_glucose_readings_by_hour_query(
    patient_id, start_date, end_date
):
    return f"""
    SELECT
        toHour(time) AS hour_24,
        formatDateTime(time, '%I:00 %p') AS hour,
        avg(glucose_level) AS avg_glucose_level
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
    GROUP BY hour_24, hour
    ORDER BY hour_24
    """


def generate_avg_glucose_reading_by_date_query(
    patient_id, start_date, end_date
):
    return f"""
    SELECT
        toDate(time) AS date,
        AVG(glucose_level) AS average_glucose
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{start_date}'
        AND time <= '{end_date}'
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
