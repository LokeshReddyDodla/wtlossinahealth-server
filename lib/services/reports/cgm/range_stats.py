"""CGM glucose range statistics calculations."""

from lib.schemas.cgm_stats import CGMRangeStats
from lib.utils.validation_utils import validate_float

from .queries import generate_range_coverage_query


class CGMRangeStatistics:
    """Static methods for calculating CGM range statistics."""

    @staticmethod
    def fetch(
        clickhouse_store, patient_id: str, start_date_str: str, end_date_str: str
    ) -> CGMRangeStats:
        """Fetch glucose range coverage statistics."""
        queries = {
            "below_54": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level < 54",
                "below_54",
            ),
            "below_70_above_54": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level < 70 AND glucose_level >= 54",
                "below_70_above_54",
            ),
            "in_target_70_180": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 70 AND glucose_level <= 180",
                "in_target_70_180",
            ),
            "in_tight_target_70_140": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 70 AND glucose_level <= 140",
                "in_tight_target_70_140",
            ),
            "above_180_below_250": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level > 180 AND glucose_level < 250",
                "above_180_below_250",
            ),
            "above_250": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 250",
                "above_250",
            ),
            "in_target_63_140": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level >= 63 AND glucose_level <= 140",
                "in_target_63_140",
            ),
            "below_63_above_54": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level < 63 AND glucose_level >= 54",
                "below_63_above_54",
            ),
            "above_140": generate_range_coverage_query(
                patient_id,
                start_date_str,
                end_date_str,
                "glucose_level > 140",
                "above_140",
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
            in_tight_target_70_140_percent=results.get("in_tight_target_70_140", 0.0),
            above_180_below_250_percent=results.get("above_180_below_250", 0.0),
            above_250_percent=results.get("above_250", 0.0),
            in_target_63_140_percent=results.get("in_target_63_140", 0.0),
            below_63_above_54_percent=results.get("below_63_above_54", 0.0),
            above_140_percent=results.get("above_140", 0.0),
        )

    @staticmethod
    def compute_gri(stats: CGMRangeStats) -> float:
        """Glycemia Risk Index (Klonoff 2022): single 0-100 score, hypo weighted
        heavier than hyper. Expanded from GRI = 3.0*Hypo + 1.6*Hyper where
        Hypo = VLow + 0.8*Low and Hyper = VHigh + 0.5*High.
        """
        gri = (
            3.0 * stats.below_54_percent
            + 2.4 * stats.below_70_above_54_percent
            + 1.6 * stats.above_250_percent
            + 0.8 * stats.above_180_below_250_percent
        )
        return round(min(100.0, gri), 1)
