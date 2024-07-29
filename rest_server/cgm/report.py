from typing import Union
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query


from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from lib.utils.glucose_events import calculate_glucose_events
from lib.utils.glucose_queries import (
    generate_glucose_level_query,
    generate_overall_glucose_stats_query,
)
from rest_server.cgm.api_schema import (
    GlucoseLevelStats,
    GlucoseRangeStats,
    GlucoseSummaryStats,
    HyperStats,
    HypoStats,
)

# Create FastAPI router
router = APIRouter(prefix="/cgm/report")


@router.get(
    "/overall_glucose_stats", response_model=GlucoseLevelStats, tags=["CGM"]
)
async def get_overall_glucose_stats(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[GlucoseLevelStats, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store

        patient_id = str(current_patient.patient_id)
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

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

        # Generate query for overall statistics
        overall_stats_query = generate_overall_glucose_stats_query(
            patient_id, from_date_str, to_date_str
        )

        results = {}
        for key, query in queries.items():
            result = clickhouse_store.client.execute(query)
            total_readings = result[0][0] if result else 0
            condition_met = result[0][1] if result else 0
            percentage = result[0][2] if result else 0.0

            # Logging intermediate results for debugging
            # print(f"Query: {query}")
            print(
                f"Total readings: {total_readings}, Condition met: {condition_met}, Percentage: {percentage}"
            )

            results[key] = percentage

        # Execute overall statistics query
        overall_stats_result = clickhouse_store.client.execute(
            overall_stats_query
        )
        average_glucose = (
            overall_stats_result[0][0] if overall_stats_result else 0.0
        )
        glucose_stddev = (
            overall_stats_result[0][1] if overall_stats_result else 0.0
        )

        # Calculate GMI and glucose variability
        gmi = 3.31 + 0.02392 * average_glucose
        gmi_mmol = gmi * 10.93
        glucose_variability = (
            (glucose_stddev / average_glucose) * 100 if average_glucose else 0
        )

        # Calculate hyper events
        glucose_events_metrics = calculate_glucose_events(
            clickhouse_store,
            patient_id,
            from_date_str,
            to_date_str,
            hyper_threshold=180,
            hypo_threshold=70,
        )
        print("==> glucose_events_metrics: ", glucose_events_metrics)

        glucose_range_stats = GlucoseRangeStats(
            below_54=results["below_54"],
            below_70_above_54=results["below_70_above_54"],
            in_target_70_180=results["in_target_70_180"],
            above_180_below_250=results["above_180_below_250"],
            above_250=results["above_250"],
        )

        glucose_summary_stats = GlucoseSummaryStats(
            average_glucose=average_glucose,
            gmi=gmi,
            gmi_mmol=gmi_mmol,
            glucose_variability=glucose_variability,
        )

        hyper_stats = HyperStats(
            total_hyper_duration=glucose_events_metrics[
                "total_hyper_duration"
            ],
            average_hyper_duration=glucose_events_metrics[
                "average_hyper_duration"
            ],
            hyper_events_count=glucose_events_metrics["hyper_events_count"],
        )

        hypo_stats = HypoStats(
            total_hypo_duration=glucose_events_metrics["total_hypo_duration"],
            average_hypo_duration=glucose_events_metrics[
                "average_hypo_duration"
            ],
            hypo_events_count=glucose_events_metrics["hypo_events_count"],
        )

        return GlucoseLevelStats(
            patient_id=patient_id,
            total_readings=total_readings,
            glucose_summary_stats=glucose_summary_stats,
            glucose_range_stats=glucose_range_stats,
            hyper_stats=hyper_stats,
            hyper_events=glucose_events_metrics["hyper_events"],
            hypo_stats=hypo_stats,
            hypo_events=glucose_events_metrics["hypo_events"],
        )

    except Exception as e:
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
