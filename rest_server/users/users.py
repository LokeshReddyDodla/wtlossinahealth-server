from sqlalchemy import or_
from lib.models.user import (
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
    MedicineAllergy,
    SleepSummary,
    SmokingHabit,
    User,
)
from lib.schemas.user import (
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
    MedicineAllergyCreate,
    SleepSummaryCreate,
    SmokingHabitCreate,
    UserCreate,
    UserDetail,
    UserUpdate,
)
from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth import get_current_user
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union

from rest_server.response_models import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/user")


@router.get(path="/profile", tags=["User"], response_model=SuccessResponse)
async def get_user_details(
    request: Request, current_user: User = Depends(get_current_user)
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(User)
                .where(User.user_id == current_user.user_id)
                .options(
                    selectinload(User.daily_activities),
                    selectinload(User.food_allergies),
                    selectinload(User.medicine_allergies),
                    selectinload(User.diet_preferences),
                    selectinload(User.alcohol_consumption),
                    selectinload(User.smoking_habits),
                    selectinload(User.meal_timings),
                    selectinload(User.cuisine_preferences),
                    selectinload(User.sleep_summary),
                    selectinload(User.diabetic_history),
                    selectinload(User.family_diabetic_history),
                    selectinload(User.medical_history),
                    selectinload(User.current_medication),
                )
            )

            user = result.scalars().first()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")

            # Convert the user to the response model
            user_detail = UserDetail.from_orm(user)
            return SuccessResponse(
                message="User data fetched successfully.", data=user_detail
            )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.post(path="/basic", tags=["User"], response_model=SuccessResponse)
async def create_basic_user(
    request: Request,
    user_data: UserCreate,
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Check if the user already exists
            existing_user = await session.execute(
                select(User).filter(
                    or_(
                        User.email == user_data.email,
                        User.phone_number == user_data.phone_number,
                    )
                )
            )
            existing_user = existing_user.scalar_one_or_none()

            if existing_user:
                response = ErrorResponse(message="User already exists")
                raise HTTPException(status_code=400, detail=response.dict())

            # Create a new user
            new_user = User(**user_data.dict())
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            return SuccessResponse(
                message="User basic data created successfully.", data=new_user
            )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.put(
    path="/basic/{user_id}", tags=["User"], response_model=SuccessResponse
)
async def update_basic_user(
    request: Request,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            user = await session.get(User, current_user.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            for key, value in user_data.dict(exclude_unset=True).items():
                if key not in ["created_at", "updated_at"]:
                    setattr(user, key, value)

            await session.commit()
            await session.refresh(user)
            return SuccessResponse(
                message="User basic data updated successfully.", data=user
            )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.patch(
    path="/lifestyle/{user_id}", tags=["User"], response_model=SuccessResponse
)
async def upsert_user_lifestyle(
    request: Request,
    activities: DailyActivityCreate,
    diet_preferences: List[DietPreferenceCreate],
    alcohol_consumption: AlcoholConsumptionCreate,
    smoking_habits: SmokingHabitCreate,
    sleep_summary: SleepSummaryCreate,
    food_allergies: Optional[List[FoodAllergyCreate]] = None,
    meal_timings: Optional[List[MealTimingCreate]] = None,
    cuisine_preferences: Optional[List[CuisinePreferenceCreate]] = None,
    current_user: User = Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            user_id = current_user.user_id
            user_result = await session.execute(
                select(User)
                .where(User.user_id == user_id)
                .options(
                    selectinload(User.daily_activities),
                    selectinload(User.food_allergies),
                    selectinload(User.diet_preferences),
                    selectinload(User.alcohol_consumption),
                    selectinload(User.smoking_habits),
                    selectinload(User.meal_timings),
                    selectinload(User.cuisine_preferences),
                    selectinload(User.sleep_summary),
                )
            )
            user = user_result.scalars().first()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Update or create related data
            if user.daily_activities:
                for key, value in activities.dict().items():
                    setattr(user.daily_activities[0], key, value)
            else:
                user.daily_activities = [
                    DailyActivity(**activities.dict(), user_id=user_id)
                ]

            user.diet_preferences = [
                DietPreference(**preference.dict(), user_id=user_id)
                for preference in diet_preferences
            ]

            if user.alcohol_consumption:
                for key, value in alcohol_consumption.dict().items():
                    setattr(user.alcohol_consumption, key, value)
            else:
                user.alcohol_consumption = AlcoholConsumption(
                    **alcohol_consumption.dict(), user_id=user_id
                )

            if user.smoking_habits:
                for key, value in smoking_habits.dict().items():
                    setattr(user.smoking_habits, key, value)
            else:
                user.smoking_habits = SmokingHabit(
                    **smoking_habits.dict(), user_id=user_id
                )

            if user.sleep_summary:
                for key, value in sleep_summary.dict().items():
                    setattr(user.sleep_summary, key, value)
            else:
                user.sleep_summary = SleepSummary(
                    **sleep_summary.dict(), user_id=user_id
                )

            # Handling lists of related objects
            user.food_allergies = [
                FoodAllergy(**allergy.dict(), user_id=user_id)
                for allergy in (food_allergies or [])
            ]
            user.meal_timings = [
                MealTiming(**timing.dict(), user_id=user_id)
                for timing in (meal_timings or [])
            ]
            user.cuisine_preferences = [
                CuisinePreference(**cuisine.dict(), user_id=user_id)
                for cuisine in (cuisine_preferences or [])
            ]

            session.add(user)
            await session.commit()
            await session.refresh(user)
            return SuccessResponse(
                message="User lifestyle data upserted successfully.", data=user
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
    path="/medical_history/{user_id}",
    tags=["User"],
    response_model=SuccessResponse,
)
async def upsert_user_medical_history(
    request: Request,
    diabetic_history: DiabeticHistoryCreate,
    current_medication: CurrentMedicationCreate,
    medicine_allergies: Optional[List[MedicineAllergyCreate]] = None,
    family_diabetic_history: Optional[
        List[FamilyDiabeticHistoryCreate]
    ] = None,
    medical_history: Optional[List[MedicalHistoryCreate]] = None,
    current_user: User = Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            user_id = current_user.user_id
            user = await session.get(
                User,
                user_id,
                options=[
                    selectinload(User.diabetic_history),
                    selectinload(User.current_medication),
                    selectinload(User.medicine_allergies),
                    selectinload(User.family_diabetic_history),
                    selectinload(User.medical_history),
                ],
            )

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Update or create related data
            if user.diabetic_history:
                for key, value in diabetic_history.dict().items():
                    setattr(user.diabetic_history, key, value)
            else:
                user.diabetic_history = DiabeticHistory(
                    **diabetic_history.dict(), user_id=user_id
                )

            if user.current_medication:
                for key, value in current_medication.dict().items():
                    setattr(user.current_medication, key, value)
            else:
                user.current_medication = CurrentMedication(
                    **current_medication.dict(), user_id=user_id
                )

            # Handling lists of related objects
            user.medicine_allergies = [
                MedicineAllergy(**allergy.dict(), user_id=user_id)
                for allergy in (medicine_allergies or [])
            ]
            user.family_diabetic_history = [
                FamilyDiabeticHistory(**history.dict(), user_id=user_id)
                for history in (family_diabetic_history or [])
            ]
            user.medical_history = [
                MedicalHistory(**history.dict(), user_id=user_id)
                for history in (medical_history or [])
            ]

            session.add(user)
            await session.commit()
            await session.refresh(user)
            return SuccessResponse(
                message="User medical history data upserted successfully.",
                data=user,
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


@router.delete(path="/delete", tags=["User"], response_model=SuccessResponse)
async def delete_user_api(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> Union[SuccessResponse, HTTPException]:
    """
    Delete User API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            user = await session.get(User, current_user.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            await session.delete(user)
            await session.commit()

            return SuccessResponse(message="User deleted successfully.")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
