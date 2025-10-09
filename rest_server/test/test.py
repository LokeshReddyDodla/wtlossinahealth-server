import json
from math import ceil
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
import logging

from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_cgm_report_vector_service,
    get_cgm_vector_service,
    get_meal_service,
    get_meal_vector_service,
    get_patient_profile_service,
    get_qdrant_search_engine_service,
)
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import Patient
from lib.schemas.patient_meal import PatientMeal
from lib.services.cgm_report_service import CGMReportService


from lib.services.cgm_report_service_v2.src.cgm_vector.cgm_vector_service import (
    CGMVectorService,
)

from lib.services.cgm_report_vector_service import CGMReportVectorService
from lib.services.file_content_extractor import FileContentExtractorService
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.services.meal_service import MealService
from lib.services.meal_vector_service import MealVectorService
from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)
from lib.tasks.meal_tasks import generate_meal_vector, process_meal_batch
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.vector_utils import embed_text
from rest_server.response_models import SuccessResponse
from fastapi import Depends, HTTPException, Query, Request, status
from openai import AsyncOpenAI
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema

router = APIRouter(prefix="/test")

logger = logging.getLogger("mongo_test")

extractor = FileContentExtractorService()
openai_client = AsyncOpenAI()


@router.get(path="/mongodb", tags=["Test"])
async def test_api(request: Request):
    try:
        logger.info("Attempting to insert document")
        document = {"initial_key": "initial_value"}
        await request.state.context.mongo_store.insert_document(
            "test_collection", document
        )
        logger.info("Document inserted successfully")
        return {"message": "inserted successfully"}
    except Exception as e:
        logger.error(f"Failed to insert document: {str(e)}")
        return {"message": "failed to insert", "error": str(e)}


@router.post("/extract")
async def extract_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        text = extractor.extract(file_bytes, file.filename, file.content_type)
        return {"filename": file.filename, "content": text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/libreview/never-synced")
async def patients_never_synced_libreview(
    session: AsyncSession = Depends(get_postgres_session),
):
    result = await session.execute(
        select(PatientConnectedApp).options(
            selectinload(PatientConnectedApp.libreview),
            selectinload(PatientConnectedApp.patient),
        )
    )
    connected_apps = result.scalars().all()

    never_synced_patients = []

    for app in connected_apps:
        libreview = app.libreview
        patient = app.patient
        if libreview and libreview.last_sync_timestamp is None:
            never_synced_patients.append(
                {
                    "patient_id": str(patient.patient_id),
                    "first_name": patient.first_name,
                    "last_name": patient.last_name,
                    "phone_number": patient.phone_number,
                    "email": patient.email,
                    "libreview_id": libreview.libreview_id,
                }
            )

    if not never_synced_patients:
        raise HTTPException(
            status_code=404,
            detail="No patients found with never-synced LibreView",
        )

    return {"patients": never_synced_patients}


@router.delete(
    "/libreview/cleanup-invalid",
    response_model=SuccessResponse,
)
async def cleanup_invalid_libreview_connections(
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        result = await session.execute(
            select(PatientConnectedApp).options(
                selectinload(PatientConnectedApp.libreview),
                selectinload(PatientConnectedApp.patient),
            )
        )
        connected_apps = result.scalars().all()

        removed = []
        for app in connected_apps:
            libreview = app.libreview
            patient = app.patient
            if libreview and str(libreview.libreview_id) == str(
                patient.patient_id
            ):
                await session.delete(app)
                removed.append(
                    {
                        "patient_id": str(patient.patient_id),
                        "first_name": patient.first_name,
                        "last_name": patient.last_name,
                        "phone_number": patient.phone_number,
                        "email": patient.email,
                        "libreview_id": libreview.libreview_id,
                    }
                )

        if not removed:
            raise HTTPException(
                status_code=404,
                detail="No invalid LibreView connections found.",
            )

        await session.commit()

        return SuccessResponse(
            message=f"Removed {len(removed)} invalid LibreView connections.",
            data={"removed_patients": removed},
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/qdrant/cgm/{report_id}")
async def test_qdrant_cgm(
    report_id: str,
    patient_id: str,
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    cgm_report_vector_service: CGMReportVectorService = Depends(
        get_cgm_report_vector_service
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    cgm_vector_service: CGMVectorService = Depends(get_cgm_vector_service),
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        report = await cgm_report_service.fetch_report(patient_id, report_id)

        if not report:
            raise

        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )

        await cgm_vector_service.upsert_report(
            patient_id,
            report["overall"]["_id"],
            report["day_wise"],
            patient_info.age,
            patient_info.gender,
        )
        return SuccessResponse(
            message="Report fetched successfully",
            data=report,
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/qdrant/search")
async def search_qdrant_reports(
    query: str = Query(..., description="Text query to search for"),
    limit: int = Query(5, description="Number of results to return"),
    data_types: Optional[List[str]] = Query(
        None,
        description="Filter by one or more data_type values, e.g. cgm_range_stats",
    ),
    cgm_report_vector_service: CGMReportVectorService = Depends(
        get_cgm_report_vector_service
    ),
):
    try:
        query_embedding = await embed_text(query)

        results = await cgm_report_vector_service.search_similar_reports(
            query_embedding=query_embedding, limit=limit, data_types=data_types
        )

        return {"query": query, "results": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def nl_to_qdrant_filter(query: str) -> dict:
    from datetime import datetime

    system_prompt = f"""
    You are an intelligent assistant that converts any natural language query about glucose/CGM
    events or statistics into a valid Qdrant filter JSON.

    ⚠️ RULES:
    - Supported keys: 
    data_type,
    # Summary stats
    data.average_glucose, data.gmi, data.glucose_variability, data.standard_deviation, data.highest_glucose, data.highest_glucose_date,
    data.lowest_glucose, data.lowest_glucose_date,
    # Range stats
    data.in_target_70_180, data.above_180_below_250, data.above_250, data.below_70_above_54, data.below_54,
    # Hyper/hypo stats
    data.total_hyper_duration, data.hyper_events_count, data.average_hyper_duration,
    data.total_hypo_duration, data.hypo_events_count, data.average_hypo_duration,
    # Rapid spike/drop stats
    data.total_spike_duration, data.spike_events_count, data.average_spike_duration,
    data.total_drop_duration, data.drop_events_count, data.average_drop_duration,
    # Event fields
    peak_glucose_level, lowest_glucose_level, initial_glucose_level,
    start_time, end_time, duration, peak_glucose_time, lowest_glucose_time,
    # AGP points
    data.median, data.tenth_percentile, data.ninetieth_percentile, data.twenty_fifth_percentile, data.seventy_fifth_percentile, data.hour,
    # Time period stats
    data.out_of_range_percentage, from_time, to_time

    - Supported data_type values: 
    "cgm_range_stats", "cgm_summary_stats",
    "hyper_stats", "hypo_stats",
    "hyper_event", "hypo_event",
    "rapid_spike_stats", "rapid_spike_event",
    "rapid_drop_stats", "rapid_drop_event",
    "time_period_stats", "agp_point".

    - Time filtering:
    • For all stats sections (summary, range, hyper/hypo stats, spike/drop stats): use "start_time" and "end_time" numeric epoch milliseconds.  
    • For events (hyper_event, hypo_event, rapid_spike_event, rapid_drop_event): use "start_time" and "end_time" numeric epoch milliseconds.  
    • For time_period_stats: use "from_time" and "to_time" numeric epoch milliseconds.
    • Always output numeric ranges for date fields, but keep durations and other numeric metrics in their native units (minutes, counts, percentages, etc.).

    - Durations such as total_hyper_duration, average_hyper_duration, total_hypo_duration, average_hypo_duration, total_spike_duration, average_spike_duration, total_drop_duration, average_drop_duration, and data.duration should always remain in minutes and NOT be converted to milliseconds.
    - If the user specifies only a month (e.g., "September"), assume the current year ({datetime.now().year}).
    - If the user says "events" without specifying hyper/hypo/spike/drop, include ALL event types
    ("hyper_event", "hypo_event", "rapid_spike_event", "rapid_drop_event").  
    - Use "must" for required filters. If multiple possible values exist (like hyper/hypo events), 
    use "should" with "min_should" containing conditions and "min_count".  
    - Include as much filtering as possible based on the query.  
    - Output ONLY the filter object in JSON format.  
    
    Example 1:
    Query: "What was the average glucose level in September?"
    Output:
    {{
    "must": [
        {{"key": "data_type", "match": {{"value": "cgm_summary_stats"}}}},
        {{"key": "start_time", "range": {{"gte": 1756684800000}}}},  
        {{"key": "end_time", "range": {{"lt": 1759363200000}}}}
    ]
    }}

    Example 2:
    Query: "Show events below 200 in September"
    Output:
    {{
    "should": [
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "hyper_event"}}}},
            {{"key": "peak_glucose_level", "range": {{"lt": 200}}}}
        ]
        }},
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "hypo_event"}}}},
            {{"key": "lowest_glucose_level", "range": {{"lt": 200}}}}
        ]
        }},
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "rapid_spike_event"}}}},
            {{"key": "peak_glucose_level", "range": {{"lt": 200}}}}
        ]
        }},
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "rapid_drop_event"}}}},
            {{"key": "lowest_glucose_level", "range": {{"lt": 200}}}}
        ]
        }}
    ],
    "min_should": {{
        "conditions": [
        {{"key": "data_type", "match": {{"value": "hyper_event"}}}},
        {{"key": "data_type", "match": {{"value": "hypo_event"}}}},
        {{"key": "data_type", "match": {{"value": "rapid_spike_event"}}}},
        {{"key": "data_type", "match": {{"value": "rapid_drop_event"}}}}
        ],
        "min_count": 1
    }},
    "must": [
        {{"key": "start_time", "range": {{"gte": 1756684800000}}}},
        {{"key": "end_time", "range": {{"lt": 1759363200000}}}}
    ]
    }}
    
    Example 3:
    Query: "Compare weekdays vs weekends in September"
    Note: since start_time and end_time are stored as numeric epoch milliseconds, the filter must correctly apply date ranges to represent weekdays and weekends.
    Output:
    {{
    "should": [
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "hyper_stats"}}}},
            {{"key": "start_time", "range": {{"gte": 1756684800000, "lt": 1757203200000}}}}
        ]
        }},
        {{
        "must": [
            {{"key": "data_type", "match": {{"value": "hyper_stats"}}}},
            {{"key": "start_time", "range": {{"gte": 1757203200000, "lt": 1757721600000}}}}
        ]
        }}
    ],
    "min_should": {{
        "conditions": [
        {{"key": "data_type", "match": {{"value": "hyper_stats"}}}}
        ],
        "min_count": 1
    }}
    }}
    
    Example 4:
    Query: "Which patient days had >2 hypo events?"
    Output:
    {{
    "must": [
        {{"key": "data_type", "match": {{"value": "hypo_stats"}}}},
        {{"key": "data.hypo_events_count", "range": {{"gt": 2}}}}
    ]
    }}
    
    Example 5:
    Query: "Did hypoglycemia frequency reduce after September 22?"
    Note: "September 22" → "2025-09-22T00:00:00Z" → 1758499200000 milliseconds since epoch (UTC).
    Output:
    {{
        "must": [
            {{
                "key": "data_type",
                "match": {{"value": "hypo_stats"}}
            }},
            {{
                "key": "start_time",
                "range": {{"gte": 1758499200000}}
            }}
        ]
    }}
    
    Example 6:
    Query: "Show AGP points for 6am–9am in September."
    Note: Hours are stored as integers (0–23), so 6am–9am → 6 to 9.
    Output:
    {{
        "must": [
            {{
                "key": "data_type",
                "match": {{"value": "agp_point"}}
            }},
            {{
                "key": "hour",
                "range": {{"gte": 6, "lt": 9}}
            }},
            {{
                "key": "start_time",
                "range": {{"gte": 1756684800000}}
            }},
            {{
                "key": "end_time",
                "range": {{"lt": 1759276800000}}
            }}
        ]
    }}


    
    """

    response = await openai_client.chat.completions.create(
        model="gpt-4o",  # or gpt-4o for more accuracy
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        response_format={"type": "json_object"},  # ensures clean JSON
    )

    content = response.choices[0].message.content
    return json.loads(content)


@router.get("/qdrant/nl_search")
async def search_qdrant_nl(
    query: str = Query(
        ..., description="Natural language query to search for"
    ),
    limit: int = Query(5, description="Number of results to return"),
    cgm_report_vector_service: CGMReportVectorService = Depends(
        get_cgm_report_vector_service
    ),
):
    try:
        # Step 1: Get query embedding
        query_embedding = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        embedding = query_embedding.data[0].embedding

        # Step 2: Convert natural language → Qdrant filter
        filter_conditions = await nl_to_qdrant_filter(query)

        # Step 3: Perform search in Qdrant
        results = await cgm_report_vector_service.search_similar_reports(
            query_embedding=embedding,
            limit=limit,
            filter_conditions=filter_conditions,  # type: ignore
        )

        return {
            "query": query,
            "filter": filter_conditions,
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/nl_search/v2")
async def search_qdrant_nl_v2(
    query: str = Query(
        ..., description="Natural language query to search for"
    ),
    patient_id: Optional[str] = Query(None, description="Patient ID"),
    limit: int = Query(500, description="Number of results to return"),
    qdrant_search_engine_service: QdrantSearchEngine = Depends(
        get_qdrant_search_engine_service
    ),
):
    try:
        return await qdrant_search_engine_service.search(
            query, limit, patient_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/meal/all")
async def enqueue_meal_vector_batches(
    session: AsyncSession = Depends(get_postgres_session),
):
    BATCH_SIZE = 50
    try:
        query = (
            select(PatientMealModel)
            .options(
                selectinload(PatientMealModel.patient),
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.macro_nutritional_values
                ),
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.micro_nutritional_values
                ),
                selectinload(PatientMealModel.total_macro_nutritional_value),
                selectinload(PatientMealModel.total_micro_nutritional_value),
            )
            .filter(PatientMealModel.analyzed == True)
        )
        result = await session.execute(query)
        meals = result.scalars().all()

        meals_data = [
            {
                **PatientMealSchema.model_validate(m).model_dump(mode="json"),
                "patient": (
                    Patient.model_validate(m.patient).model_dump(mode="json")
                    if m.patient
                    else None
                ),
            }
            for m in meals
        ]
        total_batches = ceil(len(meals_data) / BATCH_SIZE)

        for i in range(total_batches):
            batch = meals_data[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
            process_meal_batch.delay(batch)

        return {
            "message": f"Enqueued {total_batches} batches for {len(meals_data)} meals."
        }

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/qdrant/meal/{meal_id}")
async def test_qdrant_meal(
    meal_id: str,
    patient_id: str,
    meal_service: MealService = Depends(get_meal_service),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    meal_vector_service: MealVectorService = Depends(get_meal_vector_service),
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        meal = await meal_service.fetch_meal(meal_id)

        if not meal:
            raise

        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )

        meal_schema = PatientMeal.from_orm(meal)
        meal_dict = meal_schema.model_dump()

        print("==> meal_dict: ", meal_dict)

        result = await meal_vector_service.upsert_meal(
            patient_id,
            str(meal.id),
            meal_dict,
            patient_info.age,
            patient_info.gender,
        )
        return SuccessResponse(
            message="Meal report fetched successfully",
            data=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
