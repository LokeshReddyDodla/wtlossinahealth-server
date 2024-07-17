from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Date,
    Float,
    Boolean,
    ForeignKey,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    user_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    first_name = Column(String, index=True)
    last_name = Column(String, index=True)
    dob = Column(Date)
    gender = Column(String(10))
    profile_picture = Column(Text, nullable=True)
    height = Column(Float)
    waist = Column(Float)
    weight = Column(Float)
    email = Column(String, unique=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )
    locale = Column(String(50), nullable=True)

    # Relationships
    daily_activities = relationship("DailyActivity", back_populates="user")
    food_allergies = relationship("FoodAllergy", back_populates="user")
    medicine_allergies = relationship("MedicineAllergy", back_populates="user")
    diet_preferences = relationship("DietPreference", back_populates="user")
    alcohol_consumption = relationship(
        "AlcoholConsumption", uselist=False, back_populates="user"
    )
    smoking_habits = relationship(
        "SmokingHabit", uselist=False, back_populates="user"
    )
    meal_timings = relationship("MealTiming", back_populates="user")
    cuisine_preferences = relationship(
        "CuisinePreference", back_populates="user"
    )
    sleep_summary = relationship(
        "SleepSummary", uselist=False, back_populates="user"
    )
    diabetic_history = relationship(
        "DiabeticHistory", uselist=False, back_populates="user"
    )
    family_diabetic_history = relationship(
        "FamilyDiabeticHistory", back_populates="user"
    )
    medical_history = relationship("MedicalHistory", back_populates="user")
    current_medication = relationship(
        "CurrentMedication", uselist=False, back_populates="user"
    )

    meals = relationship("Meal", back_populates="user")


class DailyActivity(Base):
    __tablename__ = "daily_activity"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    activity_level = Column(String(50))
    user = relationship("User", back_populates="daily_activities")


class FoodAllergy(Base):
    __tablename__ = "food_allergies"

    allergy_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    allergy_name = Column(String(100))
    user = relationship("User", back_populates="food_allergies")


class MedicineAllergy(Base):
    __tablename__ = "medicine_allergies"

    allergy_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    allergy_name = Column(String(100))
    user = relationship("User", back_populates="medicine_allergies")


class DietPreference(Base):
    __tablename__ = "diet_preferences"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    preference = Column(String(50))
    detail = Column(String(100), nullable=True)
    user = relationship("User", back_populates="diet_preferences")


class AlcoholConsumption(Base):
    __tablename__ = "alcohol_consumption"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    consume_alcohol = Column(Boolean)
    frequency = Column(String(50), nullable=True)
    quantity = Column(String(50), nullable=True)
    type_of_alcohol = Column(JSON, nullable=True)
    user = relationship("User", back_populates="alcohol_consumption")


class SmokingHabit(Base):
    __tablename__ = "smoking_habits"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    smoke_status = Column(String(20))
    years_of_smoking = Column(Integer, nullable=True)
    cigarettes_per_day = Column(Integer, nullable=True)
    quit_years_ago = Column(Integer, nullable=True)
    user = relationship("User", back_populates="smoking_habits")


class MealTiming(Base):
    __tablename__ = "meal_timings"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    meal_type = Column(String(50))
    time = Column(String(50))
    user = relationship("User", back_populates="meal_timings")


class CuisinePreference(Base):
    __tablename__ = "cuisine_preferences"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    cuisine = Column(String(50))
    user = relationship("User", back_populates="cuisine_preferences")


class SleepSummary(Base):
    __tablename__ = "sleep_summary"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True
    )
    sleep_quality = Column(String(50))
    wake_up_fresh = Column(Boolean)
    drowsy_day = Column(Boolean)
    user = relationship("User", back_populates="sleep_summary")


class DiabeticHistory(Base):
    __tablename__ = "diabetic_history"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True
    )
    type_of_diabetes = Column(String(50), nullable=True)
    years_with_diabetes = Column(Integer, nullable=True)
    is_pregnant = Column(Boolean, nullable=True)
    pregnancy_weeks = Column(Integer, nullable=True)
    user = relationship("User", back_populates="diabetic_history")


class FamilyDiabeticHistory(Base):
    __tablename__ = "family_diabetic_history"

    history_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    family_member = Column(String(50))
    duration = Column(String(50), nullable=True)
    user = relationship("User", back_populates="family_diabetic_history")


class MedicalHistory(Base):
    __tablename__ = "medical_history"

    history_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    condition = Column(String(100))
    duration_years = Column(Integer)
    details = Column(Text, nullable=True)
    user = relationship("User", back_populates="medical_history")


class CurrentMedication(Base):
    __tablename__ = "current_medication"

    medication_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    has_medication = Column(Boolean)
    prescription_description = Column(Text, nullable=True)
    prescription_image_url = Column(Text, nullable=True)
    user = relationship("User", back_populates="current_medication")


class Prescription(Base):
    __tablename__ = "prescriptions"

    prescription_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    medication_id = Column(
        UUID(as_uuid=True), ForeignKey("current_medication.medication_id")
    )
    prescription_file = Column(Text)
