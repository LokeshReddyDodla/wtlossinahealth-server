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
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.event import listens_for
from sqlalchemy.orm import relationship

from lib.core.background_task_runner import BackgroundTaskRunner
from lib.models import Base
from lib.models.associations import patient_care_provider_association
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_permission import PatientPermission
from lib.models.user_device import UserDevice
from lib.services.chat.chat_management_service import ChatManagementService
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import object_session


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

    diet_plans = relationship(
        "PatientDietPlan", back_populates="patient", cascade="all, delete-orphan"
    )

    fitness_plans = relationship(
        "PatientFitnessPlan", back_populates="patient", cascade="all, delete-orphan"
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

    smbgs = relationship(
        "PatientSMBG", back_populates="patient", cascade="all, delete-orphan"
    )

    prescriptions = relationship(
        "PatientPrescription",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    reports = relationship(
        "PatientReport",
        back_populates="patient",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    connected_apps = relationship(
        "PatientConnectedApp",
        uselist=False,
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    sleep_checkins = relationship(
        "SleepCheckin", back_populates="patient", cascade="all, delete-orphan"
    )
    mood_entries = relationship(
        "MoodEntry", back_populates="patient", cascade="all, delete-orphan"
    )
    symptom_entries = relationship(
        "SymptomEntry", back_populates="patient", cascade="all, delete-orphan"
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

    package_assignments = relationship(
        "PatientPackageAssignment",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    care_providers = relationship(
        "CareProvider",
        secondary=patient_care_provider_association,
        back_populates="patients",
    )

   

    weight_loss_enrollment = relationship(
        "WeightLossAgentEnrollment",
        back_populates="patient",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def current_package(self):
        """Returns the currently active package assignment"""
        today = datetime.now().date()
        return next(
            (
                pa
                for pa in self.package_assignments
                if pa.status == "active"
                and pa.start_date <= today <= pa.end_date
            ),
            None,
        )

    @hybrid_property
    def age(self):  # type: ignore
        if self.dob is None:
            return None
        today = datetime.today()
        return (
            today.year
            - self.dob.year
            - ((today.month, today.day) < (self.dob.month, self.dob.day))
        )

    @age.expression
    def age(cls):
        # This uses PostgreSQL's date functions to calculate age in years
        return func.date_part(
            "year", func.age(func.current_date(), cls.dob)
        ).cast(Integer)

    @hybrid_property
    def full_name(self):  # type: ignore
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        return None

    @full_name.expression
    def full_name(cls):
        return func.concat(cls.first_name, " ", cls.last_name)

    @property
    def default_diet_plan(self):
        """Returns the default diet plan (set during onboarding)"""
        return next(
            (plan for plan in self.diet_plans if plan.is_default and plan.status == "ACTIVE"),
            None,
        )

    @property
    def default_fitness_plan(self):
        """Returns the default fitness plan (set during onboarding)"""
        return next(
            (plan for plan in self.fitness_plans if plan.is_default and plan.status == "ACTIVE"),
            None,
        )

    def get_active_diet_plan(self, date=None):
        """Returns the diet plan active on a given date"""
        if date is None:
            date = datetime.now().date()
        return next(
            (
                plan
                for plan in self.diet_plans
                if plan.status == "ACTIVE" and plan.start_date <= date and (plan.end_date is None or plan.end_date >= date)
            ),
            None,
        )

    def get_active_fitness_plan(self, date=None):
        """Returns the fitness plan active on a given date"""
        if date is None:
            date = datetime.now().date()
        return next(
            (
                plan
                for plan in self.fitness_plans
                if plan.status == "ACTIVE" and plan.start_date <= date and (plan.end_date is None or plan.end_date >= date)
            ),
            None,
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
            "gallery_permission": False,
            "storage_permission": False,
        },
    )

    # create a group chat for the patient
    chat_service = ChatManagementService()
    runner = BackgroundTaskRunner()
    runner.run(
        chat_service.create_new_chat,
        str(target.patient_id),
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
