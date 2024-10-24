import asyncio
import uuid
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float,
                        ForeignKey, Integer, String, Text, Time)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.event import listens_for
from sqlalchemy.orm import Session, object_session, relationship

from lib.core.background_task_runner import BackgroundTaskRunner
from lib.models import Base
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_permission import PatientPermission
from lib.services.chat_service import ChatService


class Patient(Base):
    __tablename__ = "patients"

    patient_id = Column(
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
    locale = Column(String(50), nullable=True, default="Asia/Kolkata")

    # Relationships
    daily_activity = relationship(
        "PatientDailyActivity",
        back_populates="patient",
        cascade="all, delete-orphan",
        uselist=False,
    )
    food_allergies = relationship(
        "PatientFoodAllergy",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    drug_allergies = relationship(
        "PatientDrugAllergy",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    diet_preferences = relationship(
        "PatientDietPreference",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    alcohol_consumption = relationship(
        "PatientAlcoholConsumption",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    smoking_habit = relationship(
        "PatientSmokingHabit",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    meal_timings = relationship(
        "PatientMealTiming",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    cuisine_preferences = relationship(
        "PatientCuisinePreference",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    sleep_habit = relationship(
        "PatientSleepHabit",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    diabetic_history = relationship(
        "PatientDiabeticHistory",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    family_diabetic_histories = relationship(
        "PatientFamilyDiabeticHistory",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    medical_histories = relationship(
        "PatientMedicalHistory",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    current_medication = relationship(
        "PatientCurrentMedication",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    patient_plans = relationship(
        "PatientPlan", back_populates="patient", cascade="all, delete-orphan"
    )

    meals = relationship(
        "PatientMeal", back_populates="patient", cascade="all, delete-orphan"
    )

    permissions = relationship(
        "PatientPermission",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    vitals = relationship(
        "PatientVital", back_populates="patient", cascade="all, delete-orphan"
    )

    smbgs = relationship(
        "PatientSMBG", back_populates="patient", cascade="all, delete-orphan"
    )

    connected_apps = relationship(
        "PatientConnectedApp",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    sleep_entries = relationship(
        "PatientSleep", back_populates="patient", cascade="all, delete-orphan"
    )

    token_usage_logs = relationship(
        "PatientTokenUsageLog",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    health_facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "health_facilities.health_facility_id", ondelete="SET NULL"
        ),
    )

    health_facility = relationship(
        "HealthFacility", back_populates="patients", passive_deletes=True
    )

    care_providers = relationship(
        "PatientCareProvider",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    user_devices = relationship(
        "UserDevice", back_populates="patient", cascade="all, delete-orphan"
    )


@listens_for(Patient, "after_insert")
def create_related_records(mapper, connection, target):
    # Insert into PatientConnectedApp
    connection.execute(
        PatientConnectedApp.__table__.insert(),
        {
            "patient_id": target.patient_id,
        },
    )
    # Insert into PatientPermission
    connection.execute(
        PatientPermission.__table__.insert(),
        {
            "patient_id": target.patient_id,
            "notification_permission": False,
            "health_permission": False,
            "camera_permission": False,
            "storage_permission": False,
        },
    )

    # create a group chat for the patient
    chat_service = ChatService()
    runner = BackgroundTaskRunner()
    runner.run(
        chat_service.create_new_chat, str(target.patient_id), "patient", True
    )
    runner.shutdown()
