from sqlalchemy import or_
from lib.models.patient import (
    Patient,
)
from lib.models.patient_alcohol_consumption import PatientAlcoholConsumption
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_cuisine_preference import PatientCuisinePreference
from lib.models.patient_current_medication import PatientCurrentMedication
from lib.models.patient_daily_acitivity import PatientDailyActivity
from lib.models.patient_diabetic_history import PatientDiabeticHistory
from lib.models.patient_diet_preference import PatientDietPreference
from lib.models.patient_drug_allergy import PatientDrugAllergy
from lib.models.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistory,
)
from lib.models.patient_food_allergy import PatientFoodAllergy
from lib.models.patient_meal_timing import PatientMealTiming
from lib.models.patient_medical_history import PatientMedicalHistory
from lib.models.patient_sleep_habit import PatientSleepHabit
from lib.models.patient_smoking_habit import PatientSmokingHabit
from lib.schemas.patient import (
    PatientCreate,
    PatientUpdate,
    Patient as PatientSchema,
)
from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from lib.schemas.patient_alcohol_consumption import (
    PatientAlcoholConsumptionCreate,
)
from lib.schemas.patient_cuisine_preference import (
    PatientCuisinePreferenceCreate,
)
from lib.schemas.patient_current_medication import (
    PatientCurrentMedicationCreate,
)
from lib.schemas.patient_daily_acitivity import PatientDailyActivityCreate
from lib.schemas.patient_diabetic_history import PatientDiabeticHistoryCreate
from lib.schemas.patient_diet_preference import PatientDietPreferenceCreate
from lib.schemas.patient_drug_allergy import PatientDrugAllergyCreate
from lib.schemas.patient_family_diabetic_history import (
    PatientFamilyDiabeticHistoryCreate,
)
from lib.schemas.patient_food_allergy import PatientFoodAllergyCreate
from lib.schemas.patient_meal_timing import PatientMealTimingCreate
from lib.schemas.patient_medical_history import PatientMedicalHistoryCreate
from lib.schemas.patient_sleep_habit import PatientSleepHabitCreate
from lib.schemas.patient_smoking_habit import PatientSmokingHabitCreate
from rest_server.patients.profile.api_schema import PatientProfileResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.put(
    path="/basic",
    tags=["Profile"],
    response_model=PatientProfileResponse,
)
async def update_basic_patient(
    request: Request,
    patient_data: PatientUpdate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[PatientProfileResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            patient = await session.get(Patient, current_patient.patient_id)
            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            for key, value in patient_data.dict(exclude_unset=True).items():
                if key not in ["created_at", "updated_at"]:
                    setattr(patient, key, value)

            await session.commit()
            await session.refresh(patient)

            result = PatientSchema.from_orm(patient)
            return PatientProfileResponse(
                message="Patient basic data updated successfully.",
                data=result,
            )
        except HTTPException as http_exc:
            raise http_exc
        except IntegrityError as e:
            await session.rollback()
            response = ErrorResponse(message="Integrity Error", detail=str(e))
            raise HTTPException(status_code=400, detail=response.dict())
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.patch(
    path="/lifestyle",
    tags=["Profile"],
    response_model=SuccessResponse,
)
async def upsert_patient_lifestyle(
    request: Request,
    activities: PatientDailyActivityCreate,
    diet_preferences: List[PatientDietPreferenceCreate],
    alcohol_consumption: PatientAlcoholConsumptionCreate,
    smoking_habits: PatientSmokingHabitCreate,
    sleep_habit: PatientSleepHabitCreate,
    food_allergies: Optional[List[PatientFoodAllergyCreate]] = None,
    meal_timings: Optional[List[PatientMealTimingCreate]] = None,
    cuisine_preferences: Optional[List[PatientCuisinePreferenceCreate]] = None,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            patient_id = current_patient.patient_id
            patient_result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == patient_id)
                .options(
                    selectinload(Patient.daily_activity),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.diet_preferences),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habit),
                    selectinload(Patient.meal_timings),
                    selectinload(Patient.cuisine_preferences),
                    selectinload(Patient.sleep_habit),
                )
            )
            patient = patient_result.scalars().first()

            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            # Update or create related data
            if patient.daily_activities:
                for key, value in activities.dict().items():
                    setattr(patient.daily_activities[0], key, value)
            else:
                patient.daily_activities = [
                    PatientDailyActivity(
                        **activities.dict(), patient_id=patient_id
                    )
                ]

            patient.diet_preferences = [
                PatientDietPreference(
                    **preference.dict(), patient_id=patient_id
                )
                for preference in diet_preferences
            ]

            if patient.alcohol_consumption:
                for key, value in alcohol_consumption.dict().items():
                    setattr(patient.alcohol_consumption, key, value)
            else:
                patient.alcohol_consumption = PatientAlcoholConsumption(
                    **alcohol_consumption.dict(), patient_id=patient_id
                )

            if patient.smoking_habit:
                for key, value in smoking_habits.dict().items():
                    setattr(patient.smoking_habit, key, value)
            else:
                patient.smoking_habit = PatientSmokingHabit(
                    **smoking_habits.dict(), patient_id=patient_id
                )

            if patient.sleep_habit:
                for key, value in sleep_habit.dict().items():
                    setattr(patient.sleep_habit, key, value)
            else:
                patient.sleep_habit = PatientSleepHabit(
                    **sleep_habit.dict(), patient_id=patient_id
                )

            # Handling lists of related objects
            patient.food_allergies = [
                PatientFoodAllergy(**allergy.dict(), patient_id=patient_id)
                for allergy in (food_allergies or [])
            ]
            patient.meal_timings = [
                PatientMealTiming(**timing.dict(), patient_id=patient_id)
                for timing in (meal_timings or [])
            ]
            patient.cuisine_preferences = [
                PatientCuisinePreference(
                    **cuisine.dict(), patient_id=patient_id
                )
                for cuisine in (cuisine_preferences or [])
            ]

            session.add(patient)
            await session.commit()
            await session.refresh(patient)
            return SuccessResponse(
                message="Patient lifestyle data upserted successfully.",
                data=patient,
            )
    except SQLAlchemyError as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=400, detail=response.dict())
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.patch(
    path="/medical_history",
    tags=["Profile"],
    response_model=SuccessResponse,
)
async def upsert_patient_medical_history(
    request: Request,
    diabetic_history: PatientDiabeticHistoryCreate,
    current_medication: PatientCurrentMedicationCreate,
    drug_allergies: Optional[List[PatientDrugAllergyCreate]] = None,
    family_diabetic_history: Optional[
        List[PatientFamilyDiabeticHistoryCreate]
    ] = None,
    medical_history: Optional[List[PatientMedicalHistoryCreate]] = None,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            patient_id = current_patient.patient_id
            patient = await session.get(
                Patient,
                patient_id,
                options=[
                    selectinload(Patient.diabetic_history),
                    selectinload(Patient.current_medication),
                    selectinload(Patient.drug_allergies),
                    selectinload(Patient.family_diabetic_history),
                    selectinload(Patient.medical_history),
                ],
            )

            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            # Update or create related data
            if patient.diabetic_history:
                for key, value in diabetic_history.dict().items():
                    setattr(patient.diabetic_history, key, value)
            else:
                patient.diabetic_history = PatientDiabeticHistory(
                    **diabetic_history.dict(), patient_id=patient_id
                )

            if patient.current_medication:
                for key, value in current_medication.dict().items():
                    setattr(patient.current_medication, key, value)
            else:
                patient.current_medication = PatientCurrentMedication(
                    **current_medication.dict(), patient_id=patient_id
                )

            # Handling lists of related objects
            patient.drug_allergies = [
                PatientDrugAllergy(**allergy.dict(), patient_id=patient_id)
                for allergy in (drug_allergies or [])
            ]
            patient.family_diabetic_history = [
                PatientFamilyDiabeticHistory(
                    **history.dict(), patient_id=patient_id
                )
                for history in (family_diabetic_history or [])
            ]
            patient.medical_history = [
                PatientMedicalHistory(**history.dict(), patient_id=patient_id)
                for history in (medical_history or [])
            ]

            session.add(patient)
            await session.commit()
            await session.refresh(patient)
            return SuccessResponse(
                message="Patient medical history data upserted successfully.",
                data=patient,
            )
    except SQLAlchemyError as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        await session.rollback()
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
