import traceback
from uuid import UUID
from app.models.user import AlcoholConsumption, CuisinePreference, CurrentMedication, DailyActivity, DiabeticHistory, DietPreference, FamilyDiabeticHistory, FoodAllergy, MealTiming, MedicalHistory, MedicineAllergy, SleepSummary, SmokingHabit, User
from app.schemas.user import AlcoholConsumptionCreate, CuisinePreferenceCreate, CurrentMedicationCreate, DailyActivityCreate, DiabeticHistoryCreate, DietPreferenceCreate, FamilyDiabeticHistoryCreate, FoodAllergyCreate, MealTimingCreate, MedicalHistoryCreate, MedicineAllergyCreate, Prescription, SleepSummaryCreate, SmokingHabitCreate, UserCreate, UserDetail, UserUpdate
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from typing import List, Optional, Union

from fastapi.responses import JSONResponse
from rest_server.response_models import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/user")


@router.get(path="/{user_id}", tags=["User"])
async def get_user_details(user_id: UUID, request: Request):
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(User).where(User.user_id == user_id).options(
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
            print("==> user: ", user)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            
            return user
            # Convert the user to the response model
            user_detail = UserDetail.from_orm(user)
            return SuccessResponse(message="User data fetched successfully.", data=user_detail)
        except Exception as e:
            print("==> exception: ", e)
            response = ErrorResponse(message="Internal Server Error", detail=str(e))
            raise JSONResponse(status_code=500, detail=response.dict())
        
@router.post(path="/basic", tags=["User"])
async def create_basic_user(
    user_data: UserCreate,
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Check if the user already exists
            existing_user = await session.execute(
                select(User).filter(User.email == user_data.email)
            )
            existing_user = existing_user.scalar_one_or_none()

            if existing_user:
                response = ErrorResponse(message="User already exists")
                return JSONResponse(status_code=400, content=response.dict())

            # Create a new user
            new_user = User(**user_data.dict())
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            return SuccessResponse(message="User basic data created successfully.", data=new_user)
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(message="Internal Server Error", detail=str(e))
            return JSONResponse(status_code=400, content=response.dict())
        
@router.put(path="/basic/{user_id}", tags=["User"])
async def update_basic_user(
    user_id: UUID,
    user_data: UserUpdate,
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            user = await session.get(User, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            for key, value in user_data.dict().items():
                setattr(user, key, value)
            
            await session.commit()
            await session.refresh(user)
            return SuccessResponse(message="User basic data updated successfully.", data=user)
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(message="Internal Server Error", detail=str(e))
            return JSONResponse(status_code=500, content=response.dict())


@router.patch(path="/lifestyle/{user_id}", tags=["User"])
async def upsert_user_lifestyle(
    user_id: UUID,
    activities: DailyActivityCreate,
    diet_preferences: List[DietPreferenceCreate],
    alcohol_consumption: AlcoholConsumptionCreate,
    smoking_habits: SmokingHabitCreate,
    sleep_summary: SleepSummaryCreate,
    diabetic_history: DiabeticHistoryCreate,
    current_medication: CurrentMedicationCreate,
    food_allergies: Optional[List[FoodAllergyCreate]] = None,
    medicine_allergies: Optional[List[MedicineAllergyCreate]] = None,
    meal_timings: Optional[List[MealTimingCreate]] = None,
    cuisine_preferences: Optional[List[CuisinePreferenceCreate]] = None,
    family_diabetic_history: Optional[List[FamilyDiabeticHistoryCreate]] = None,
    medical_history: Optional[List[MedicalHistoryCreate]] = None,
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    try:
        async with request.state.context.postgres_store.get_session() as session:
            user = await session.get(User, user_id, options=[
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
            ])
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
                        
            # Update or create related data
            if user.daily_activities:
                for key, value in activities.dict().items():
                    setattr(user.daily_activities[0], key, value)
            else:
                user.daily_activities = [DailyActivity(**activities.dict(), user_id=user_id)]
                
            if user.diet_preferences:
                user.diet_preferences = [DietPreference(**preference.dict(), user_id=user_id) for preference in diet_preferences]
            else:
                user.diet_preferences = [DietPreference(**preference.dict(), user_id=user_id) for preference in diet_preferences]
                
            if user.alcohol_consumption:
                for key, value in alcohol_consumption.dict().items():
                    setattr(user.alcohol_consumption, key, value)
            else:
                user.alcohol_consumption = AlcoholConsumption(**alcohol_consumption.dict(), user_id=user_id)
                
            if user.smoking_habits:
                for key, value in smoking_habits.dict().items():
                    setattr(user.smoking_habits, key, value)
            else:
                user.smoking_habits = SmokingHabit(**smoking_habits.dict(), user_id=user_id)
                
            if user.sleep_summary:
                for key, value in sleep_summary.dict().items():
                    setattr(user.sleep_summary, key, value)
            else:
                user.sleep_summary = SleepSummary(**sleep_summary.dict(), user_id=user_id)
                
            if user.diabetic_history:
                for key, value in diabetic_history.dict().items():
                    setattr(user.diabetic_history, key, value)
            else:
                user.diabetic_history = DiabeticHistory(**diabetic_history.dict(), user_id=user_id)
                
            if user.current_medication:
                for key, value in current_medication.dict().items():
                    setattr(user.current_medication, key, value)
            else:
                user.current_medication = CurrentMedication(**current_medication.dict(), user_id=user_id)

            # Handling lists of related objects
            user.food_allergies = [FoodAllergy(**allergy.dict(), user_id=user_id) for allergy in (food_allergies or [])]
            user.medicine_allergies = [MedicineAllergy(**allergy.dict(), user_id=user_id) for allergy in (medicine_allergies or [])]
            user.meal_timings = [MealTiming(**timing.dict(), user_id=user_id) for timing in (meal_timings or [])]
            user.cuisine_preferences = [CuisinePreference(**cuisine.dict(), user_id=user_id) for cuisine in (cuisine_preferences or [])]
            user.family_diabetic_history = [FamilyDiabeticHistory(**history.dict(), user_id=user_id) for history in (family_diabetic_history or [])]
            user.medical_history = [MedicalHistory(**history.dict(), user_id=user_id) for history in (medical_history or [])]

            session.add(user)
            await session.commit()
            await session.refresh(user)
            return SuccessResponse(message="User lifestyle data upserted successfully.", data=UserDetail.from_orm(user))
    except SQLAlchemyError as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print(error_message)
        print(traceback_message)
        
        await session.rollback()
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())

# 5. Create User Diabetes-Related Information
# @router.post(path="/diabetes", tags=["User"])
# async def create_user_diabetes(
#     diabetic_history: DiabeticHistory,
#     family_diabetic_history: Optional[List[FamilyDiabeticHistory]],
#     medical_history: Optional[List[MedicalHistory]],
#     current_medication: CurrentMedication,
#     prescriptions: Optional[List[Prescription]],
#     request: Request = None
# ) -> Union[SuccessResponse, HTTPException]:
#     try:
#         db: Session = request.state.context.postgres_store
#         # Add logic to create user diabetes-related data in the database
#         return SuccessResponse(message="User diabetes-related data created successfully.")
#     except Exception as e:
#         response = ErrorResponse(message="Internal Server Error", detail=str(e))
#         return JSONResponse(status_code=500, content=response.dict())

# # 6. Update User Diabetes-Related Information
# @router.put(path="/diabetes/{user_id}", tags=["User"])
# async def update_user_diabetes(
#     user_id: int,
#     diabetic_history: DiabeticHistory,
#     family_diabetic_history: Optional[List[FamilyDiabeticHistory]],
#     medical_history: Optional[List[MedicalHistory]],
#     current_medication: CurrentMedication,
#     prescriptions: Optional[List[Prescription]],
#     request: Request = None
# ) -> Union[SuccessResponse, HTTPException]:
#     try:
#         db: Session = request.state.context.postgres_store
#         # Add logic to update user diabetes-related data in the database
#         return SuccessResponse(message="User diabetes-related data updated successfully.")
#     except Exception as e:
#         response = ErrorResponse(message="Internal Server Error", detail=str(e))
#         return JSONResponse(status_code=500, content=response.dict())
