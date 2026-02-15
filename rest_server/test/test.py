from math import ceil
from datetime import datetime
import hashlib
from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
import logging

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_cgm_vector_service,
    get_libreview_service,
    get_patient_profile_service,
)
from lib.models.admin import Admin
from lib.schemas.patient import CorePatientProfile

from lib.services.reports import CGMReportService
from lib.services.vector import CGMVectorService
from lib.services.file_content_extractor import FileContentExtractorService
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from fastapi import Depends, status
from openai import AsyncOpenAI
from lib.models.patient import Patient as PatientModel
from lib.models.patient_eating_habit import (
    PatientEatingHabit as PatientEatingHabitModel,
)
from rest_server.response_models import InQueueResponse, SuccessResponse
from lib.services.libreview_service import LibreViewService

router = APIRouter(prefix="/test")

logger = logging.getLogger("mongo_test")

extractor = FileContentExtractorService()
openai_client = AsyncOpenAI()


@router.post(path="/libreview/sync/{patient_id}", tags=["Test"])
async def test_libreview_sync(
    patient_id: str,
    current_admin: Admin = Depends(get_current_admin),
    libreview_service: LibreViewService = Depends(get_libreview_service),
    force: bool = False,
):
    """
    Test endpoint: Enqueue LibreView sync for a single patient via ARQ worker.

    This will:
    1. Get the patient's LibreView ID from the database
    2. Solve Cloudflare Turnstile captcha
    3. Request LibreView data export
    4. Poll for export completion
    5. Download CSV and upload to ClickHouse
    """
    try:
        result = await libreview_service.sync_libreview(patient_id, force=force)

        if result.get("status") == "in_queue":
            return InQueueResponse(**result)

        return SuccessResponse(
            message="LibreView sync job enqueued successfully",
            data={
                **(result.get("data") or {}),
                "patient_id": patient_id,
                "queue": "arq:queue:libreview",
                "note": "Check worker logs for progress",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.delete(path="/cgm-reports/duplicates", tags=["Test"])
async def delete_duplicate_cgm_reports(
    request: Request,
    current_admin: Admin = Depends(get_current_admin),
):
    """
    Delete ALL duplicate CGM reports with report_type="custom" that have the same
    patient_id and start_date but different end_dates.
    All duplicates will be deleted (reports will be regenerated later).
    """
    try:
        # Get the cgm_reports collection
        cgm_collection = request.state.context.mongo_store.get_collection("cgm_reports")

        # Run aggregation to find duplicates
        pipeline = [
            {"$match": {"report_type": "custom"}},
            {
                "$group": {
                    "_id": {"patient_id": "$patient_id", "start_date": "$start_date"},
                    "end_dates": {"$addToSet": "$end_date"},
                    "ids": {"$push": "$_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}, "end_dates.1": {"$exists": True}}},
        ]

        duplicate_groups = await cgm_collection.aggregate(pipeline).to_list(length=None)

        # Collect all IDs to delete
        all_ids_to_delete = []
        deleted_reports = []

        for group in duplicate_groups:
            report_ids = group["ids"]
            patient_id = group["_id"]["patient_id"]
            start_date = group["_id"]["start_date"]

            # Fetch all reports in this duplicate group to get their details
            reports = await cgm_collection.find({"_id": {"$in": report_ids}}).to_list(
                length=None
            )

            # Add all report IDs to delete list
            for report in reports:
                all_ids_to_delete.append(report["_id"])
                deleted_reports.append(
                    {
                        "report_id": str(report["_id"]),
                        "patient_id": str(patient_id),
                        "start_date": report.get("start_date"),
                        "end_date": report.get("end_date"),
                    }
                )

        # Delete all duplicate reports
        total_deleted = 0
        if all_ids_to_delete:
            delete_result = await cgm_collection.delete_many(
                {"_id": {"$in": all_ids_to_delete}}
            )
            total_deleted = delete_result.deleted_count

        return {
            "message": f"Deleted {total_deleted} duplicate reports",
            "summary": {
                "duplicate_groups_found": len(duplicate_groups),
                "total_deleted": total_deleted,
            },
            "deleted_reports": deleted_reports,
        }

    except Exception as e:
        logger.error(f"Failed to delete duplicate reports: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete duplicate reports: {str(e)}"
        )


# @router.get("/active-patients", tags=["Test"])
# async def get_active_patients(
#     days: int = Query(default=3, ge=0, description="Number of days to look back for activity"),
#     active_patient_service: ActivePatientService = Depends(
#         get_active_patient_service
#     ),
# ):
#     """
#     Test endpoint to fetch active patients from the last N days.
#     """
#     try:
#         patient_ids = await active_patient_service.get_active_patients(days=days)
#         return {
#             "message": f"Found {len(patient_ids)} active patients in the last {days} days",
#             "days": days,
#             "count": len(patient_ids),
#             "patient_ids": patient_ids,
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Failed to fetch active patients",
#             detail=str(e),
#         )


# @router.post("/patient-summary/{patient_id}", tags=["Test"])
# async def generate_patient_summary(
#     patient_id: str,
#     date: date,
#     include_document: bool = True,
#     patient_summary_service: PatientSummaryService = Depends(
#         get_patient_summary_service
#     ),
# ):
#     """
#     Trigger generate_daily_summary for a patient for a specific date and optionally
#     return the stored document.
#     """
#     try:

#         start_dt = datetime.combine(
#             date, datetime.min.time(), tzinfo=timezone.utc
#         )
#         end_dt = datetime.combine(
#             date, datetime.max.time(), tzinfo=timezone.utc
#         )

#         await patient_summary_service.generate_daily_summary(
#             patient_id, date
#         )

#         doc = None
#         if include_document:
#             doc = await patient_summary_service.patient_summary_collection.find_one(
#                 {
#                     "patient_id": patient_id,
#                     "start_date": start_dt,
#                     "end_date": end_dt,
#                 }
#             )

#         return {
#             "message": "summary generated",
#             "period": {"start": start_dt, "end": end_dt},
#             "data": jsonable_encoder(doc, custom_encoder={ObjectId: str}),
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Failed to generate patient summary",
#             detail=str(e),
#         )


# @router.post("/extract")
# async def extract_file(file: UploadFile = File(...)):
#     try:
#         file_bytes = await file.read()
#         text = extractor.extract(file_bytes, file.filename, file.content_type)
#         return {"filename": file.filename, "content": text}
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @router.get("/libreview/never-synced")
# async def patients_never_synced_libreview(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     result = await session.execute(
#         select(PatientConnectedApp).options(
#             selectinload(PatientConnectedApp.libreview),
#             selectinload(PatientConnectedApp.patient),
#         )
#     )
#     connected_apps = result.scalars().all()

#     never_synced_patients = []

#     for app in connected_apps:
#         libreview = app.libreview
#         patient = app.patient
#         if libreview and libreview.last_sync_timestamp is None:
#             never_synced_patients.append(
#                 {
#                     "patient_id": str(patient.patient_id),
#                     "first_name": patient.first_name,
#                     "last_name": patient.last_name,
#                     "phone_number": patient.phone_number,
#                     "email": patient.email,
#                     "libreview_id": libreview.libreview_id,
#                 }
#             )

#     if not never_synced_patients:
#         raise HTTPException(
#             status_code=404,
#             detail="No patients found with never-synced LibreView",
#         )

#     return {"patients": never_synced_patients}


# @router.delete(
#     "/libreview/cleanup-invalid",
#     response_model=SuccessResponse,
# )
# async def cleanup_invalid_libreview_connections(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     try:
#         result = await session.execute(
#             select(PatientConnectedApp).options(
#                 selectinload(PatientConnectedApp.libreview),
#                 selectinload(PatientConnectedApp.patient),
#             )
#         )
#         connected_apps = result.scalars().all()

#         removed = []
#         for app in connected_apps:
#             libreview = app.libreview
#             patient = app.patient
#             if libreview and str(libreview.libreview_id) == str(
#                 patient.patient_id
#             ):
#                 await session.delete(app)
#                 removed.append(
#                     {
#                         "patient_id": str(patient.patient_id),
#                         "first_name": patient.first_name,
#                         "last_name": patient.last_name,
#                         "phone_number": patient.phone_number,
#                         "email": patient.email,
#                         "libreview_id": libreview.libreview_id,
#                     }
#                 )

#         if not removed:
#             raise HTTPException(
#                 status_code=404,
#                 detail="No invalid LibreView connections found.",
#             )

#         await session.commit()

#         return SuccessResponse(
#             message=f"Removed {len(removed)} invalid LibreView connections.",
#             data={"removed_patients": removed},
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


@router.get("/qdrant/cgm/{report_id}")
async def test_qdrant_cgm(
    report_id: str,
    patient_id: str,
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    cgm_vector_service: CGMVectorService = Depends(get_cgm_vector_service),
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        report = await cgm_report_service.fetch_report(patient_id, report_id)

        if not report:
            raise

        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )

        await sync_patient_daily_cgm_reports_to_vector_store(
            patient_id,
            patient_info.age,
            patient_info.gender,
            report["overall"]["start_date"],
            report["overall"]["end_date"],
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


# @router.get("/qdrant/search")
# async def search_qdrant_reports(
#     query: str = Query(..., description="Text query to search for"),
#     limit: int = Query(5, description="Number of results to return"),
#     data_types: Optional[List[str]] = Query(
#         None,
#         description="Filter by one or more data_type values, e.g. cgm_range_stats",
#     ),
#     cgm_report_vector_service: CGMReportVectorService = Depends(
#         get_cgm_report_vector_service
#     ),
# ):
#     try:
#         query_embedding = await embed_text(query)

#         results = await cgm_report_vector_service.search_similar_reports(
#             query_embedding=query_embedding, limit=limit, data_types=data_types
#         )

#         return {"query": query, "results": results}

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# async def nl_to_qdrant_filter(query: str) -> dict:
#     from datetime import datetime

#     system_prompt = f"""
#     You are an intelligent assistant that converts any natural language query about glucose/CGM
#     events or statistics into a valid Qdrant filter JSON.

#     ⚠️ RULES:
#     - Supported keys:
#     data_type,
#     # Summary stats
#     data.average_glucose, data.gmi, data.glucose_variability, data.standard_deviation, data.highest_glucose, data.highest_glucose_date,
#     data.lowest_glucose, data.lowest_glucose_date,
#     # Range stats
#     data.in_target_70_180, data.above_180_below_250, data.above_250, data.below_70_above_54, data.below_54,
#     # Hyper/hypo stats
#     data.total_hyper_duration, data.hyper_events_count, data.average_hyper_duration,
#     data.total_hypo_duration, data.hypo_events_count, data.average_hypo_duration,
#     # Rapid spike/drop stats
#     data.total_spike_duration, data.spike_events_count, data.average_spike_duration,
#     data.total_drop_duration, data.drop_events_count, data.average_drop_duration,
#     # Event fields
#     peak_glucose_level, lowest_glucose_level, initial_glucose_level,
#     start_time, end_time, duration, peak_glucose_time, lowest_glucose_time,
#     # AGP points
#     data.median, data.tenth_percentile, data.ninetieth_percentile, data.twenty_fifth_percentile, data.seventy_fifth_percentile, data.hour,
#     # Time period stats
#     data.out_of_range_percentage, from_time, to_time

#     - Supported data_type values:
#     "cgm_range_stats", "cgm_summary_stats",
#     "hyper_stats", "hypo_stats",
#     "hyper_event", "hypo_event",
#     "rapid_spike_stats", "rapid_spike_event",
#     "rapid_drop_stats", "rapid_drop_event",
#     "time_period_stats", "agp_point".

#     - Time filtering:
#     • For all stats sections (summary, range, hyper/hypo stats, spike/drop stats): use "start_time" and "end_time" numeric epoch milliseconds.
#     • For events (hyper_event, hypo_event, rapid_spike_event, rapid_drop_event): use "start_time" and "end_time" numeric epoch milliseconds.
#     • For time_period_stats: use "from_time" and "to_time" numeric epoch milliseconds.
#     • Always output numeric ranges for date fields, but keep durations and other numeric metrics in their native units (minutes, counts, percentages, etc.).

#     - Durations such as total_hyper_duration, average_hyper_duration, total_hypo_duration, average_hypo_duration, total_spike_duration, average_spike_duration, total_drop_duration, average_drop_duration, and data.duration should always remain in minutes and NOT be converted to milliseconds.
#     - If the user specifies only a month (e.g., "September"), assume the current year ({datetime.now().year}).
#     - If the user says "events" without specifying hyper/hypo/spike/drop, include ALL event types
#     ("hyper_event", "hypo_event", "rapid_spike_event", "rapid_drop_event").
#     - Use "must" for required filters. If multiple possible values exist (like hyper/hypo events),
#     use "should" with "min_should" containing conditions and "min_count".
#     - Include as much filtering as possible based on the query.
#     - Output ONLY the filter object in JSON format.

#     Example 1:
#     Query: "What was the average glucose level in September?"
#     Output:
#     {{
#     "must": [
#         {{"key": "data_type", "match": {{"value": "cgm_summary_stats"}}}},
#         {{"key": "start_time", "range": {{"gte": 1756684800000}}}},
#         {{"key": "end_time", "range": {{"lt": 1759363200000}}}}
#     ]
#     }}

#     Example 2:
#     Query: "Show events below 200 in September"
#     Output:
#     {{
#     "should": [
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "hyper_event"}}}},
#             {{"key": "peak_glucose_level", "range": {{"lt": 200}}}}
#         ]
#         }},
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "hypo_event"}}}},
#             {{"key": "lowest_glucose_level", "range": {{"lt": 200}}}}
#         ]
#         }},
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "rapid_spike_event"}}}},
#             {{"key": "peak_glucose_level", "range": {{"lt": 200}}}}
#         ]
#         }},
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "rapid_drop_event"}}}},
#             {{"key": "lowest_glucose_level", "range": {{"lt": 200}}}}
#         ]
#         }}
#     ],
#     "min_should": {{
#         "conditions": [
#         {{"key": "data_type", "match": {{"value": "hyper_event"}}}},
#         {{"key": "data_type", "match": {{"value": "hypo_event"}}}},
#         {{"key": "data_type", "match": {{"value": "rapid_spike_event"}}}},
#         {{"key": "data_type", "match": {{"value": "rapid_drop_event"}}}}
#         ],
#         "min_count": 1
#     }},
#     "must": [
#         {{"key": "start_time", "range": {{"gte": 1756684800000}}}},
#         {{"key": "end_time", "range": {{"lt": 1759363200000}}}}
#     ]
#     }}

#     Example 3:
#     Query: "Compare weekdays vs weekends in September"
#     Note: since start_time and end_time are stored as numeric epoch milliseconds, the filter must correctly apply date ranges to represent weekdays and weekends.
#     Output:
#     {{
#     "should": [
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "hyper_stats"}}}},
#             {{"key": "start_time", "range": {{"gte": 1756684800000, "lt": 1757203200000}}}}
#         ]
#         }},
#         {{
#         "must": [
#             {{"key": "data_type", "match": {{"value": "hyper_stats"}}}},
#             {{"key": "start_time", "range": {{"gte": 1757203200000, "lt": 1757721600000}}}}
#         ]
#         }}
#     ],
#     "min_should": {{
#         "conditions": [
#         {{"key": "data_type", "match": {{"value": "hyper_stats"}}}}
#         ],
#         "min_count": 1
#     }}
#     }}

#     Example 4:
#     Query: "Which patient days had >2 hypo events?"
#     Output:
#     {{
#     "must": [
#         {{"key": "data_type", "match": {{"value": "hypo_stats"}}}},
#         {{"key": "data.hypo_events_count", "range": {{"gt": 2}}}}
#     ]
#     }}

#     Example 5:
#     Query: "Did hypoglycemia frequency reduce after September 22?"
#     Note: "September 22" → "2025-09-22T00:00:00Z" → 1758499200000 milliseconds since epoch (UTC).
#     Output:
#     {{
#         "must": [
#             {{
#                 "key": "data_type",
#                 "match": {{"value": "hypo_stats"}}
#             }},
#             {{
#                 "key": "start_time",
#                 "range": {{"gte": 1758499200000}}
#             }}
#         ]
#     }}

#     Example 6:
#     Query: "Show AGP points for 6am–9am in September."
#     Note: Hours are stored as integers (0–23), so 6am–9am → 6 to 9.
#     Output:
#     {{
#         "must": [
#             {{
#                 "key": "data_type",
#                 "match": {{"value": "agp_point"}}
#             }},
#             {{
#                 "key": "hour",
#                 "range": {{"gte": 6, "lt": 9}}
#             }},
#             {{
#                 "key": "start_time",
#                 "range": {{"gte": 1756684800000}}
#             }},
#             {{
#                 "key": "end_time",
#                 "range": {{"lt": 1759276800000}}
#             }}
#         ]
#     }}


#     """

#     response = await openai_client.chat.completions.create(
#         model="gpt-4o",  # or gpt-4o for more accuracy
#         messages=[
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": query},
#         ],
#         response_format={"type": "json_object"},  # ensures clean JSON
#     )

#     content = response.choices[0].message.content
#     return json.loads(content)


# @router.get("/qdrant/meal/all")
# async def enqueue_meal_vector_batches(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     BATCH_SIZE = 50
#     try:
#         query = (
#             select(PatientMealModel)
#             .options(
#                 selectinload(PatientMealModel.patient),
#                 selectinload(PatientMealModel.items).selectinload(
#                     PatientFoodItemModel.macro_nutritional_values
#                 ),
#                 selectinload(PatientMealModel.items).selectinload(
#                     PatientFoodItemModel.micro_nutritional_values
#                 ),
#                 selectinload(PatientMealModel.total_macro_nutritional_value),
#                 selectinload(PatientMealModel.total_micro_nutritional_value),
#             )
#             .filter(PatientMealModel.analyzed == True)
#         )
#         result = await session.execute(query)
#         meals = result.scalars().all()

#         meals_data = [
#             {
#                 **PatientMealSchema.model_validate(m).model_dump(mode="json"),
#                 "patient": (
#                     Patient.model_validate(m.patient).model_dump(mode="json")
#                     if m.patient
#                     else None
#                 ),
#             }
#             for m in meals
#         ]
#         total_batches = ceil(len(meals_data) / BATCH_SIZE)

#         for i in range(total_batches):
#             batch = meals_data[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
#             process_meal_batch.delay(batch)

#         return {
#             "message": f"Enqueued {total_batches} batches for {len(meals_data)} meals."
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


# @router.get("/qdrant/smbg/all")
# async def enqueue_smbg_vector_batches(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     BATCH_SIZE = 50
#     try:
#         query = select(PatientSMBG).options(
#             selectinload(PatientSMBG.patient),
#         )
#         result = await session.execute(query)
#         smbgs = result.scalars().all()

#         smbgs_data = [
#             {
#                 "glucose_mgdl": m.glucose_level,
#                 "reading_time": m.reading_time,
#                 "type": m.type,
#                 "notes": m.notes,
#                 "uploaded_at": m.uploaded_at,
#                 "source": m.source_name or "app",
#                 "id": str(m.id),
#                 "patient_id": str(m.patient_id),
#                 "patient": (
#                     Patient.model_validate(m.patient).model_dump(mode="json")
#                     if m.patient
#                     else None
#                 ),
#             }
#             for m in smbgs
#         ]
#         total_batches = ceil(len(smbgs_data) / BATCH_SIZE)

#         for i in range(total_batches):
#             batch = smbgs_data[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
#             process_smbg_batch.delay(batch)

#         return {
#             "message": f"Enqueued {total_batches} batches for {len(smbgs_data)} smbgs."
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


# @router.get("/qdrant/patient/all")
# async def enqueue_patient_vector_batches(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     BATCH_SIZE = 50
#     try:
#         query = select(PatientModel).options(
#             selectinload(PatientModel.daily_activity),
#             selectinload(PatientModel.food_allergies),
#             selectinload(PatientModel.drug_allergies),
#             selectinload(PatientModel.alcohol_consumption),
#             selectinload(PatientModel.smoking_habit),
#             selectinload(PatientModel.sleep_habit),
#             selectinload(PatientModel.eating_habit).selectinload(
#                 PatientEatingHabitModel.meal_timings
#             ),
#             selectinload(PatientModel.eating_habit).selectinload(
#                 PatientEatingHabitModel.diet_preferences
#             ),
#             selectinload(PatientModel.diabetic_history),
#             selectinload(PatientModel.family_diabetic_histories),
#             selectinload(PatientModel.medical_histories),
#             selectinload(PatientModel.current_medication),
#         )
#         result = await session.execute(query)
#         profiles = result.scalars().all()

#         profiles_data = [
#             CorePatientProfile.from_orm(m).model_dump(mode="json")
#             for m in profiles
#         ]
#         total_batches = ceil(len(profiles_data) / BATCH_SIZE)

#         for i in range(total_batches):
#             batch = profiles_data[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
#             process_profile_batch.delay(batch)

#         return {
#             "message": f"Enqueued {total_batches} batches for {len(profiles_data)} profiles."
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


# @router.get("/qdrant/fitness/all")
# async def enqueue_fitness_vector_batches(
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     BATCH_SIZE = 50
#     try:
#         patients = (
#             (await session.execute(select(PatientModel))).scalars().all()
#         )
#         total_patients = len(patients)
#         total_batches = ceil(total_patients / BATCH_SIZE)

#         for i in range(total_batches):
#             batch = patients[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
#             patient_ids = [str(p.patient_id) for p in batch]
#             trigger_fitness_batch_sync.delay(patient_ids)

#         return {
#             "message": f"Enqueued {total_batches} batches for {total_patients} patients."
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


# @router.get("/qdrant/meal/{meal_id}")
# async def test_qdrant_meal(
#     meal_id: str,
#     patient_id: str,
#     meal_service: MealService = Depends(get_meal_service),
#     patient_profile_service: PatientProfileService = Depends(
#         get_patient_profile_service
#     ),
#     meal_vector_service: MealVectorService = Depends(get_meal_vector_service),
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     try:
#         meal = await meal_service.fetch_meal(meal_id)

#         if not meal:
#             raise

#         patient_info = await patient_profile_service.fetch_patient_profile(
#             patient_id=patient_id, include_health_data=True
#         )

#         meal_schema = PatientMeal.from_orm(meal)
#         meal_dict = meal_schema.model_dump()

#         print("==> meal_dict: ", meal_dict)

#         result = await meal_vector_service.upsert_meal(
#             patient_id,
#             str(meal.id),
#             meal_dict,
#             patient_info.age,
#             patient_info.gender,
#         )
#         return SuccessResponse(
#             message="Meal report fetched successfully",
#             data=result,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )


# @router.get("/qdrant/fitness/{fitness_report_id}")
# async def test_qdrant_meal(
#     fitness_report_id: str,
#     patient_id: str,
#     fitness_report_service: FitnessReportService = Depends(
#         get_fitness_report_service
#     ),
#     patient_profile_service: PatientProfileService = Depends(
#         get_patient_profile_service
#     ),
#     fitness_vector_service: FitnessVectorService = Depends(
#         get_fitness_vector_service
#     ),
#     session: AsyncSession = Depends(get_postgres_session),
# ):
#     try:
#         report = await fitness_report_service.fetch_report_by_id(
#             fitness_report_id
#         )

#         if not report:
#             raise

#         print("==> report: ", report)

#         patient_info = await patient_profile_service.fetch_patient_profile(
#             patient_id=patient_id, include_health_data=True
#         )

#         result = await fitness_vector_service.upsert_report(
#             patient_id,
#             [report],
#             patient_info.age,
#             patient_info.gender,
#         )
#         return SuccessResponse(
#             message="Fitness report saved successfully",
#             data=result,
#         )
#     except HTTPException:
#         raise
#     except Exception as e:
#         await session.rollback()
#         raise_http_exception(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             message="Internal Server Error",
#             detail=str(e),
#         )
