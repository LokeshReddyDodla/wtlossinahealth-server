import uuid

from sqlalchemy import UUID, Column, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientCuisinePreference(Base):
    __tablename__ = "patient_cuisine_preferences"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    eating_habit_id = Column(UUID(as_uuid=True), ForeignKey("patient_eating_habits.eating_habit_id"))
    cuisine = Column(String(50))
    eating_habit = relationship("PatientEatingHabit", back_populates="cuisine_preferences")
