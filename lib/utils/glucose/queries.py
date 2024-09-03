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


def generate_avg_glucose_reading_by_date_query(
    patient_id, from_date, to_date
):
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
