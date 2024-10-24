import uuid

from sqlalchemy import UUID, Column, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDietPreference(Base):
    __tablename__ = "patient_diet_preferences"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    eating_habit_id = Column(UUID(as_uuid=True), ForeignKey("patient_eating_habits.eating_habit_id"))
    preference = Column(String(50))
    detail = Column(String(100), nullable=True)
    eating_habit = relationship("PatientEatingHabit", back_populates="diet_preferences")