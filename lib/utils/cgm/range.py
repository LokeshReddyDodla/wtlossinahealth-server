import math

from lib.schemas.cgm_stats import CGMRangeStats
from lib.utils.cgm.queries import generate_cgm_range_coverage_query
from lib.utils.validation_utils import validate_float


class CGMRangeStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, start_date_str, end_date_str
    ) -> CGMRangeStats:
        queries = {
            "below_54": generate_cgm_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level < 54",
                "below_54",
            ),
            "below_70_above_54": generate_cgm_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level < 70 AND glucose_level >= 54",
                "below_70_above_54",
            ),
            "in_target_70_180": generate_cgm_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 70 AND glucose_level <= 180",
                "in_target_70_180",
            ),
            "above_180_below_250": generate_cgm_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level > 180 AND glucose_level < 250",
                "above_180_below_250",
            ),
            "above_250": generate_cgm_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 250",
                "above_250",
            ),
        }

        results = {}
        for key, query in queries.items():
            result = clickhouse_store.client.execute(query)
            percentage = validate_float(
                result[0][2] if result and len(result[0]) > 2 else 0.0
            )
            results[key] = percentage

        return CGMRangeStats(
            below_54_percent=results.get("below_54", 0.0),
            below_70_above_54_percent=results.get("below_70_above_54", 0.0),
            in_target_70_180_percent=results.get("in_target_70_180", 0.0),
            above_180_below_250_percent=results.get(
                "above_180_below_250", 0.0
            ),
            above_250_percent=results.get("above_250", 0.0),
        )
