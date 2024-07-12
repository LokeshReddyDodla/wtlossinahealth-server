from uuid import UUID
from app.models.user import User
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from typing import List, Optional, Union

from fastapi.responses import JSONResponse
from rest_server.users.api_schema import (
    UserCreate, UserResponse, UserUpdate, DailyActivity, FoodAllergy, MedicineAllergy, 
    DietPreference, AlcoholConsumption, SmokingHabit, MealTiming, 
    CuisinePreference, SleepSummary, DiabeticHistory, FamilyDiabeticHistory, 
    MedicalHistory, CurrentMedication, Prescription
)
from rest_server.response_models import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/user")


@router.get(path="/{user_id}", tags=["User"], response_model=UserResponse)
async def get_user_details(user_id: UUID, request: Request) -> UserResponse:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(User).where(User.user_id == user_id).options(
                    selectinload(User.daily_activities),
                    selectinload(User.food_allergies),
                    selectinload(User.medicine_allergies),
                    selectinload(User.diet_preference),
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
                response = ErrorResponse(message="User not found")
                raise JSONResponse(status_code=404, content=response.dict())
            return UserResponse(message="User data fetched successfully.", data=user)
        except Exception as e:
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

# 3. Create User Fitness and Lifestyle Data
@router.post(path="/lifestyle", tags=["User"])
async def create_user_lifestyle(
    activities: DailyActivity,
    food_allergies: Optional[List[FoodAllergy]],
    medicine_allergies: Optional[List[MedicineAllergy]],
    diet_preference: DietPreference,
    alcohol_consumption: AlcoholConsumption,
    smoking_habits: SmokingHabit,
    meal_timings: Optional[List[MealTiming]],
    cuisine_preferences: Optional[List[CuisinePreference]],
    sleep_summary: SleepSummary,
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    try:
        db: Session = request.state.context.postgres_store
        # Add logic to create user lifestyle data in the database
        return SuccessResponse(message="User lifestyle data created successfully.")
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())

# 4. Update User Fitness and Lifestyle Data
@router.put(path="/lifestyle/{user_id}", tags=["User"])
async def update_user_lifestyle(
    user_id: int,
    activities: DailyActivity,
    food_allergies: Optional[List[FoodAllergy]],
    medicine_allergies: Optional[List[MedicineAllergy]],
    diet_preference: DietPreference,
    alcohol_consumption: AlcoholConsumption,
    smoking_habits: SmokingHabit,
    meal_timings: Optional[List[MealTiming]],
    cuisine_preferences: Optional[List[CuisinePreference]],
    sleep_summary: SleepSummary,
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    try:
        db: Session = request.state.context.postgres_store
        # Add logic to update user lifestyle data in the database
        return SuccessResponse(message="User lifestyle data updated successfully.")
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())

# 5. Create User Diabetes-Related Information
@router.post(path="/diabetes", tags=["User"])
async def create_user_diabetes(
    diabetic_history: DiabeticHistory,
    family_diabetic_history: Optional[List[FamilyDiabeticHistory]],
    medical_history: Optional[List[MedicalHistory]],
    current_medication: CurrentMedication,
    prescriptions: Optional[List[Prescription]],
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    try:
        db: Session = request.state.context.postgres_store
        # Add logic to create user diabetes-related data in the database
        return SuccessResponse(message="User diabetes-related data created successfully.")
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())

# 6. Update User Diabetes-Related Information
@router.put(path="/diabetes/{user_id}", tags=["User"])
async def update_user_diabetes(
    user_id: int,
    diabetic_history: DiabeticHistory,
    family_diabetic_history: Optional[List[FamilyDiabeticHistory]],
    medical_history: Optional[List[MedicalHistory]],
    current_medication: CurrentMedication,
    prescriptions: Optional[List[Prescription]],
    request: Request = None
) -> Union[SuccessResponse, HTTPException]:
    try:
        db: Session = request.state.context.postgres_store
        # Add logic to update user diabetes-related data in the database
        return SuccessResponse(message="User diabetes-related data updated successfully.")
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())
