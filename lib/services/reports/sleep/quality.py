from .queries import generate_quality_stats_query


class SleepQualityStatistics:
    @staticmethod
    def fetch(
        clickhouse_store,
        patient_id: str,
        start_datetime: str,
        end_datetime: str,
    ) -> dict:
        query = generate_quality_stats_query(patient_id, start_datetime, end_datetime)
        rows = clickhouse_store.client.execute(query)

        type_durations = {row[0]: row[1] for row in rows}

        deep_sleep = type_durations.get("sleep_deep", 0)
        rem_sleep = type_durations.get("sleep_rem", 0)
        light_sleep = type_durations.get("sleep_light", 0)
        awake_time = type_durations.get("sleep_awake", 0)
        in_bed_duration = type_durations.get("sleep_in_bed", None)

        total_duration = deep_sleep + light_sleep + rem_sleep
        effective_in_bed_duration = in_bed_duration or (total_duration + awake_time)

        sleep_efficiency = (
            (total_duration / effective_in_bed_duration) * 100
            if effective_in_bed_duration > 0
            else 0
        )
        restorative_sleep = (
            ((deep_sleep + rem_sleep) / total_duration) * 100
            if total_duration > 0
            else 0
        )
        awake_percentage = (
            (awake_time / effective_in_bed_duration) * 100
            if effective_in_bed_duration > 0
            else 0
        )

        sleep_quality = SleepQualityStatistics._classify_sleep_quality(
            sleep_efficiency, restorative_sleep, awake_percentage,
        )

        return {
            "deep_sleep_percentage": (deep_sleep / total_duration) * 100 if total_duration else 0,
            "rem_sleep_percentage": (rem_sleep / total_duration) * 100 if total_duration else 0,
            "awake_time_percentage": awake_percentage,
            "restorative_sleep": restorative_sleep,
            "sleep_efficiency": sleep_efficiency,
            "sleep_quality": sleep_quality,
        }

    @staticmethod
    def _classify_sleep_quality(
        sleep_efficiency: float,
        restorative_sleep: float,
        awake_percentage: float,
    ) -> str:
        if sleep_efficiency >= 90 and restorative_sleep >= 60 and awake_percentage < 5:
            return "excellent"
        elif sleep_efficiency >= 85 and restorative_sleep >= 50 and awake_percentage < 10:
            return "good"
        elif sleep_efficiency >= 75 and restorative_sleep >= 40 and awake_percentage < 15:
            return "could be better"
        elif sleep_efficiency >= 60 and restorative_sleep >= 30 and awake_percentage < 20:
            return "poor"
        else:
            return "very poor"
