import uuid

from sqlalchemy import UUID, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMealTiming(Base):
    __tablename__ = "patient_meal_timings"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    eating_habit_id = Column(UUID(as_uuid=True), ForeignKey("patient_eating_habits.eating_habit_id"))
    meal_type = Column(String(50))
    time = Column(String(50))
    eating_habit = relationship("PatientEatingHabit", back_populates="meal_timings")
