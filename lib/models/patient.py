import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.event import listens_for
from sqlalchemy.orm import relationship

from lib.core.background_task_runner import BackgroundTaskRunner
from lib.models import Base
from lib.models.associations import patient_care_provider_association
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_permission import PatientPermission
from lib.services.chat.chat_management_service import ChatManagementService


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
    is_verified = Column(Boolean, default=False)

    profile_completion = Column(
        JSON,
        default={
            "basic": {"is_complete": False, "is_mandatory": True},
            "lifestyle": {"is_complete": False, "is_mandatory": True},
            "medical_history": {"is_complete": False, "is_mandatory": True},
        },
    )

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
    eating_habit = relationship(
        "PatientEatingHabit",
        back_populates="patient",
        uselist=False,
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

    health_facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "health_facilities.health_facility_id", ondelete="SET NULL"
        ),
    )
    health_facility = relationship(
        "HealthFacility",
        back_populates="patients",
    )

    package_id = Column(
        UUID(as_uuid=True),
        ForeignKey("packages.package_id", ondelete="SET NULL"),
    )
    package = relationship(
        "Package",
        back_populates="patients",
    )

    care_providers = relationship(
        "CareProvider",
        secondary=patient_care_provider_association,
        back_populates="patients",
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
    chat_service = ChatManagementService()
    runner = BackgroundTaskRunner()
    runner.run(
        chat_service.create_new_chat,
        str(target.patient_id),
        "patient",
        True,
        group_name="My Care Team Group",
    )

    # Add initial message to the conversation
    from lib.services.ai_conversation_service.ai_conversation_service import (
        AiConversationService,
    )

    ai_conversation_service = AiConversationService()
    welcome_message = (
        "Welcome to AiHealth! We're glad to have you onboard. "
        "Let us know how we can assist you, or start a conversation with your health assistant."
    )
    runner.run(
        ai_conversation_service.add_message_to_conversation,
        user_id=str(target.patient_id),
        conversation_id=f"{target.patient_id}-patient",
        conversation_type="other",
        role="system",
        content=welcome_message,
        message_type="text",
    )

    runner.shutdown()
