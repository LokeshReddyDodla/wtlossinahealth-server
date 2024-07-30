from lib.utils.glucose.queries import generate_glucose_level_query
from lib.schemas.glucose import GlucoseRangeStats


class GlucoseRangeStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> GlucoseRangeStats:
        queries = {
            "below_54": generate_glucose_level_query(
                patient_id,
                from_date_str,
                to_date_str,
                "glucose_level < 54",
                "below_54",
            ),
            "below_70_above_54": generate_glucose_level_query(
                patient_id,
                from_date_str,
                to_date_str,
                "glucose_level < 70 AND glucose_level >= 54",
                "below_70_above_54",
            ),
            "in_target_70_180": generate_glucose_level_query(
                patient_id,
                from_date_str,
                to_date_str,
                "glucose_level >= 70 AND glucose_level <= 180",
                "in_target_70_180",
            ),
            "above_180_below_250": generate_glucose_level_query(
                patient_id,
                from_date_str,
                to_date_str,
                "glucose_level > 180 AND glucose_level < 250",
                "above_180_below_250",
            ),
            "above_250": generate_glucose_level_query(
                patient_id,
                from_date_str,
                to_date_str,
                "glucose_level >= 250",
                "above_250",
            ),
        }

        results = {}
        for key, query in queries.items():
            result = clickhouse_store.client.execute(query)
            percentage = result[0][2] if result else 0.0
            results[key] = percentage

        return GlucoseRangeStats(
            below_54=results["below_54"],
            below_70_above_54=results["below_70_above_54"],
            in_target_70_180=results["in_target_70_180"],
            above_180_below_250=results["above_180_below_250"],
            above_250=results["above_250"],
        )
