from sqlalchemy import or_
from lib.models.patient import (
    AlcoholConsumption,
    CuisinePreference,
    CurrentMedication,
    DailyActivity,
    DiabeticHistory,
    DietPreference,
    FamilyDiabeticHistory,
    FoodAllergy,
    MealTiming,
    MedicalHistory,
    DrugAllergy,
    SleepSummary,
    SmokingHabit,
    Patient,
)
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import (
    AlcoholConsumptionCreate,
    CuisinePreferenceCreate,
    CurrentMedicationCreate,
    DailyActivityCreate,
    DiabeticHistoryCreate,
    DietPreferenceCreate,
    FamilyDiabeticHistoryCreate,
    FoodAllergyCreate,
    MealTimingCreate,
    MedicalHistoryCreate,
    DrugAllergyCreate,
    SleepSummaryCreate,
    SmokingHabitCreate,
    PatientCreate,
    PatientDetail,
    PatientUpdate,
)
from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from rest_server.response_models import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/patient")


@router.get(path="/profile", tags=["Patient"], response_model=SuccessResponse)
async def get_patient_details(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == current_patient.patient_id)
                .options(
                    selectinload(Patient.daily_activities),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.drug_allergies),
                    selectinload(Patient.diet_preferences),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habits),
                    selectinload(Patient.meal_timings),
                    selectinload(Patient.cuisine_preferences),
                    selectinload(Patient.sleep_summary),
                    selectinload(Patient.diabetic_history),
                    selectinload(Patient.family_diabetic_history),
                    selectinload(Patient.medical_history),
                    selectinload(Patient.current_medication),
                    selectinload(Patient.permissions),
                    selectinload(Patient.vitals),
                    selectinload(Patient.smbg),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.libreview
                    ),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.other_app
                    ),
                )
            )

            patient = result.scalars().first()
            if patient is None:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            # Convert the patient to the response model
            patient_detail = PatientDetail.from_orm(patient)
            return SuccessResponse(
                message="Patient data fetched successfully.",
                data=patient_detail,
            )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.post(path="/basic", tags=["Patient"], response_model=SuccessResponse)
async def create_basic_patient(
    request: Request,
    patient_data: PatientCreate,
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Check if the patient already exists
            existing_patient = await session.execute(
                select(Patient).filter(
                    or_(
                        Patient.email == patient_data.email,
                        Patient.phone_number == patient_data.phone_number,
                    )
                )
            )
            existing_patient = existing_patient.scalar_one_or_none()

            if existing_patient:
                response = ErrorResponse(message="Patient already exists")
                raise HTTPException(status_code=400, detail=response.dict())

            # Create a new patient
            new_patient = Patient(**patient_data.dict())
            session.add(new_patient)
            await session.commit()
            await session.refresh(new_patient)

            return SuccessResponse(
                message="Patient basic data created successfully.",
                data=new_patient,
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


@router.put(
    path="/basic",
    tags=["Patient"],
    response_model=SuccessResponse,
)
async def update_basic_patient(
    request: Request,
    patient_data: PatientUpdate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
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
            return SuccessResponse(
                message="Patient basic data updated successfully.",
                data=patient,
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
    tags=["Patient"],
    response_model=SuccessResponse,
)
async def upsert_patient_lifestyle(
    request: Request,
    activities: DailyActivityCreate,
    diet_preferences: List[DietPreferenceCreate],
    alcohol_consumption: AlcoholConsumptionCreate,
    smoking_habits: SmokingHabitCreate,
    sleep_summary: SleepSummaryCreate,
    food_allergies: Optional[List[FoodAllergyCreate]] = None,
    meal_timings: Optional[List[MealTimingCreate]] = None,
    cuisine_preferences: Optional[List[CuisinePreferenceCreate]] = None,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            patient_id = current_patient.patient_id
            patient_result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == patient_id)
                .options(
                    selectinload(Patient.daily_activities),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.diet_preferences),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habits),
                    selectinload(Patient.meal_timings),
                    selectinload(Patient.cuisine_preferences),
                    selectinload(Patient.sleep_summary),
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
                    DailyActivity(**activities.dict(), patient_id=patient_id)
                ]

            patient.diet_preferences = [
                DietPreference(**preference.dict(), patient_id=patient_id)
                for preference in diet_preferences
            ]

            if patient.alcohol_consumption:
                for key, value in alcohol_consumption.dict().items():
                    setattr(patient.alcohol_consumption, key, value)
            else:
                patient.alcohol_consumption = AlcoholConsumption(
                    **alcohol_consumption.dict(), patient_id=patient_id
                )

            if patient.smoking_habits:
                for key, value in smoking_habits.dict().items():
                    setattr(patient.smoking_habits, key, value)
            else:
                patient.smoking_habits = SmokingHabit(
                    **smoking_habits.dict(), patient_id=patient_id
                )

            if patient.sleep_summary:
                for key, value in sleep_summary.dict().items():
                    setattr(patient.sleep_summary, key, value)
            else:
                patient.sleep_summary = SleepSummary(
                    **sleep_summary.dict(), patient_id=patient_id
                )

            # Handling lists of related objects
            patient.food_allergies = [
                FoodAllergy(**allergy.dict(), patient_id=patient_id)
                for allergy in (food_allergies or [])
            ]
            patient.meal_timings = [
                MealTiming(**timing.dict(), patient_id=patient_id)
                for timing in (meal_timings or [])
            ]
            patient.cuisine_preferences = [
                CuisinePreference(**cuisine.dict(), patient_id=patient_id)
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
    tags=["Patient"],
    response_model=SuccessResponse,
)
async def upsert_patient_medical_history(
    request: Request,
    diabetic_history: DiabeticHistoryCreate,
    current_medication: CurrentMedicationCreate,
    drug_allergies: Optional[List[DrugAllergyCreate]] = None,
    family_diabetic_history: Optional[
        List[FamilyDiabeticHistoryCreate]
    ] = None,
    medical_history: Optional[List[MedicalHistoryCreate]] = None,
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
                patient.diabetic_history = DiabeticHistory(
                    **diabetic_history.dict(), patient_id=patient_id
                )

            if patient.current_medication:
                for key, value in current_medication.dict().items():
                    setattr(patient.current_medication, key, value)
            else:
                patient.current_medication = CurrentMedication(
                    **current_medication.dict(), patient_id=patient_id
                )

            # Handling lists of related objects
            patient.drug_allergies = [
                DrugAllergy(**allergy.dict(), patient_id=patient_id)
                for allergy in (drug_allergies or [])
            ]
            patient.family_diabetic_history = [
                FamilyDiabeticHistory(**history.dict(), patient_id=patient_id)
                for history in (family_diabetic_history or [])
            ]
            patient.medical_history = [
                MedicalHistory(**history.dict(), patient_id=patient_id)
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


@router.delete(
    path="/delete", tags=["Patient"], response_model=SuccessResponse
)
async def delete_patient_api(
    request: Request,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    """
    Delete Patient API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            patient = await session.get(Patient, current_patient.patient_id)
            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            await session.delete(patient)
            await session.commit()

            return SuccessResponse(message="Patient deleted successfully.")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
