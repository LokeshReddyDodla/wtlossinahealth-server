def generate_summary_stats_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS total_steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS total_active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS total_active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    """


def generate_daily_stats_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        toDate(date_from) AS date,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    GROUP BY
        date
    ORDER BY
        date
    """


def generate_weekly_stats_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        toWeek(date_from) AS week_number,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    GROUP BY
        week_number
    ORDER BY
        week_number
    """


def generate_monthly_stats_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        formatDateTime(date_from, '%Y-%m') AS month,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    GROUP BY
        month
    ORDER BY
        month
    """


def generate_hourly_stats_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        formatDateTime(date_from, '%Y-%m-%d %H:00:00') AS hour,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    GROUP BY
        hour
    ORDER BY
        hour
    """


def generate_activity_distribution_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        CASE
            WHEN hour(date_from) BETWEEN 6 AND 12 THEN 'Morning'
            WHEN hour(date_from) BETWEEN 12 AND 18 THEN 'Afternoon'
            WHEN hour(date_from) BETWEEN 18 AND 24 THEN 'Evening'
            ELSE 'Night'
        END AS time_of_day,
        SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
        SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
        SUM(dateDiff('minute', date_from, date_to)) AS active_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
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
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        formatDateTime(date_from, '%Y-%m-%d %H:00:00') AS hour,
        MAX(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS max_steps,
        MAX(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS max_active_energy
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
    GROUP BY
        hour
    ORDER BY
        hour DESC
    LIMIT 1
    """


def generate_inactive_periods_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        dateDiff('minute', t1.date_to, t2.date_from) AS inactive_duration
    FROM (
        SELECT
            date_from,
            date_to,
            toInt64(row_number() OVER (ORDER BY date_from)) AS rn
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND date_from >= toDateTime('{from_date}')
            AND date_to <= toDateTime('{to_date}')
    ) AS t1
    JOIN (
        SELECT
            date_from,
            date_to,
            toInt64(row_number() OVER (ORDER BY date_from)) AS rn
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND date_from >= toDateTime('{from_date}')
            AND date_to <= toDateTime('{to_date}')
    ) AS t2
    ON t1.rn = t2.rn - 1
    WHERE
        dateDiff('minute', t1.date_to, t2.date_from) > 60
    ORDER BY
        inactive_duration DESC
    """


def generate_week_over_week_comparison_query(
    patient_id: str, current_week_start: str, previous_week_start: str
) -> str:
    return f"""
    SELECT
        current_week.steps - previous_week.steps AS steps_diff,
        current_week.active_energy - previous_week.active_energy AS active_energy_diff,
        current_week.active_duration - previous_week.active_duration AS active_duration_diff
    FROM
        (SELECT
            SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
            SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
            SUM(dateDiff('minute', date_from, date_to)) AS active_duration
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND date_from >= toDateTime('{current_week_start}')
            AND date_to < addWeeks(toDateTime('{current_week_start}'), 1)
        ) AS current_week,
        (SELECT
            SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS steps,
            SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS active_energy,
            SUM(dateDiff('minute', date_from, date_to)) AS active_duration
        FROM
            aihealth.fitness_data
        WHERE
            patient_id = '{patient_id}'
            AND date_from >= toDateTime('{previous_week_start}')
            AND date_to < addWeeks(toDateTime('{previous_week_start}'), 1)
        ) AS previous_week
    """


def generate_average_active_session_duration_query(
    patient_id: str, from_date: str, to_date: str
) -> str:
    return f"""
    SELECT
        AVG(COALESCE(dateDiff('minute', date_from, date_to), 0)) AS average_active_session_duration
    FROM
        aihealth.fitness_data
    WHERE
        patient_id = '{patient_id}'
        AND date_from >= '{from_date}'
        AND date_to <= '{to_date}'
        AND type = 'ACTIVE'
    """
