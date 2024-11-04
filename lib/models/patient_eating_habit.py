import uuid

from sqlalchemy import (ARRAY, UUID, Boolean, Column, Float, ForeignKey,
                        Integer, String, Time)
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientEatingHabit(Base):
    __tablename__ = "patient_eating_habits"

    eating_habit_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))

    meal_timings = relationship(
        "PatientMealTiming",
        back_populates="eating_habit",
        cascade="all, delete-orphan",
    )
    snacks_count = Column(Integer, nullable=True)
    meals_per_day = Column(Integer, nullable=True)

    cuisine_preferences = Column(ARRAY(String), nullable=True)

    diet_preferences = relationship(
        "PatientDietPreference",
        back_populates="eating_habit",
        cascade="all, delete-orphan",
        uselist=False,
    )

    patient = relationship("Patient", back_populates="eating_habit")
