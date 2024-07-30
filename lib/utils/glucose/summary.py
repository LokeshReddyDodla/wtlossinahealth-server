from lib.utils.glucose.queries import generate_overall_glucose_stats_query
from lib.schemas.glucose import GlucoseSummaryStats


class GlucoseSummaryStatsFetcher:
    @staticmethod
    def fetch(
        clickhouse_store, patient_id, from_date_str, to_date_str
    ) -> GlucoseSummaryStats:
        query = generate_overall_glucose_stats_query(
            patient_id, from_date_str, to_date_str
        )
        result = clickhouse_store.client.execute(query)

        average_glucose = result[0][0] if result else 0.0
        glucose_stddev = result[0][1] if result else 0.0

        gmi = 3.31 + 0.02392 * average_glucose
        gmi_mmol = gmi * 10.93
        glucose_variability = (
            (glucose_stddev / average_glucose) * 100 if average_glucose else 0
        )

        return GlucoseSummaryStats(
            average_glucose=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability=glucose_variability,
        )
