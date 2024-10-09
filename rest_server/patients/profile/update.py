from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.models.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_cuisine_preference import PatientCuisinePreference
from lib.models.patient_current_medication import PatientCurrentMedication
from lib.models.patient_daily_activity import PatientDailyActivity
from lib.models.patient_diabetic_history import PatientDiabeticHistory
from lib.models.patient_diet_preference import PatientDietPreference
from lib.models.patient_drug_allergy import PatientDrugAllergy
from lib.models.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistory
from lib.models.patient_food_allergy import PatientFoodAllergy
from lib.models.patient_meal_timing import PatientMealTiming
from lib.models.patient_medical_history import PatientMedicalHistory
from lib.models.patient_sleep_habit import PatientSleepHabit
from lib.models.patient_smoking_habit import PatientSmokingHabit
from lib.schemas.patient import CompletePatientProfile
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientCreate, PatientUpdate
from lib.schemas.patient_alcohol_consumption import \
    PatientAlcoholConsumptionCreate
from lib.schemas.patient_cuisine_preference import \
    PatientCuisinePreferenceCreate
from lib.schemas.patient_current_medication import \
    PatientCurrentMedicationCreate
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_diet_preference import PatientDietPreferenceCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistoryCreate
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_meal_timing import PatientMealTimingCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.services.patient_profile_service import PatientProfileService
from rest_server.patients.profile.api_schema import PatientProfileResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.put(
    path="/basic",
    response_model=PatientProfileResponse,
)
async def update_basic_patient(
    request: Request,
    patient_data: PatientUpdate,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        updated_patient = (
            await patient_profile_service.update_basic_patient_profile(
                patient_id=str(current_patient.patient_id),
                patient_data=patient_data,
            )
        )

        return PatientProfileResponse(
            message="Patient basic data updated successfully.",
            data=PatientSchema.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.patch(
    path="/lifestyle",
    response_model=PatientProfileResponse,
)
async def upsert_patient_lifestyle(
    request: Request,
    daily_activity: PatientDailyActivityCreate,
    diet_preferences: List[PatientDietPreferenceCreate],
    alcohol_consumption: PatientAlcoholConsumptionCreate,
    smoking_habit: PatientSmokingHabitCreate,
    sleep_habit: PatientSleepHabitCreate,
    food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
    meal_timings: Optional[List[PatientMealTimingCreate]] = None,
    cuisine_preferences: Optional[List[PatientCuisinePreferenceCreate]] = None,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        updated_patient = (
            await patient_profile_service.upsert_patient_lifestyle(
                patient_id=str(current_patient.patient_id),
                daily_activity=daily_activity,
                diet_preferences=diet_preferences,
                alcohol_consumption=alcohol_consumption,
                smoking_habit=smoking_habit,
                sleep_habit=sleep_habit,
                food_allergies=food_allergies,
                meal_timings=meal_timings,
                cuisine_preferences=cuisine_preferences,
            )
        )

        return PatientProfileResponse(
            message="Patient lifestyle data updated successfully.",
            data=PatientSchema.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.patch(
    path="/medical_history",
    response_model=PatientProfileResponse,
)
async def upsert_patient_medical_history(
    request: Request,
    diabetic_history: PatientDiabeticHistoryCreate,
    current_medication: PatientCurrentMedicationCreate,
    drug_allergies: Optional[List[PatientDrugAllergyCreate]] = None,
    family_diabetic_histories: Optional[
        List[PatientFamilyDiabeticHistoryCreate]
    ] = None,
    medical_histories: Optional[List[PatientMedicalHistoryCreate]] = None,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        updated_patient = (
            await patient_profile_service.upsert_patient_medical_history(
                patient_id=str(current_patient.patient_id),
                diabetic_history=diabetic_history,
                current_medication=current_medication,
                drug_allergies=drug_allergies,
                family_diabetic_histories=family_diabetic_histories,
                medical_histories=medical_histories,
            )
        )

        return PatientProfileResponse(
            message="Patient medical history data updated successfully.",
            data=PatientSchema.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
