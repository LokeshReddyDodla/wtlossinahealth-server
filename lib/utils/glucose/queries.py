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


def generate_highest_glucose_query(patient_id, from_date, to_date):
    return f"""
    SELECT
            MAX(glucose_level),
            MAX(time)
        FROM
            aihealth.cgm_data
        WHERE
            patient_id = '{patient_id}'
            AND time >= '{from_date}'
            AND time <= '{to_date}'
    """


def generate_lowest_glucose_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        MIN(glucose_level),
        MIN(time)
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    """


def generate_overall_glucose_stats_query(patient_id, from_date, to_date):
    return f"""
    SELECT
        AVG(glucose_level) AS average_glucose,
        STDDEV_SAMP(glucose_level) AS glucose_stddev
    FROM
        aihealth.cgm_data
    WHERE
        patient_id = '{patient_id}'
        AND time >= '{from_date}'
        AND time <= '{to_date}'
    """
