from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.schemas.patient import CorePatientProfile, PatientUpdate
from lib.schemas.patient_alcohol_consumption import \
    PatientAlcoholConsumptionCreate
from lib.schemas.patient_current_medication import \
    PatientCurrentMedicationCreate
from lib.schemas.patient_daily_activity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_eating_habit import PatientEatingHabitCreate
from lib.schemas.patient_family_diabetic_history import \
    PatientFamilyDiabeticHistoryCreate
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.put(
    path="/basic",
    response_model=SuccessResponse,
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

        return SuccessResponse(
            message="Patient basic data updated successfully.",
            data=CorePatientProfile.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.patch(
    path="/lifestyle",
    response_model=SuccessResponse,
)
async def upsert_patient_lifestyle(
    request: Request,
    daily_activity: PatientDailyActivityCreate,
    alcohol_consumption: PatientAlcoholConsumptionCreate,
    smoking_habit: PatientSmokingHabitCreate,
    eating_habit: PatientEatingHabitCreate,
    sleep_habit: PatientSleepHabitCreate,
    food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
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
                alcohol_consumption=alcohol_consumption,
                smoking_habit=smoking_habit,
                eating_habit=eating_habit,
                sleep_habit=sleep_habit,
                food_allergies=food_allergies,
            )
        )

        return SuccessResponse(
            message="Patient lifestyle data updated successfully.",
            data=CorePatientProfile.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.patch(
    path="/medical_history",
    response_model=SuccessResponse,
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

        return SuccessResponse(
            message="Patient medical history data updated successfully.",
            data=CorePatientProfile.from_orm(updated_patient),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
