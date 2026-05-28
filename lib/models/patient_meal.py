import uuid
from datetime import datetime

from sqlalchemy import (ARRAY, Boolean, Column, Date, DateTime, Float,
                        ForeignKey, String, Text, Time)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class BaseMacroNutritionalValue(Base):
    __abstract__ = True
    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calories = Column(Float)
    proteins = Column(Float)
    carbohydrates = Column(Float)
    simple_carbs = Column(Float, nullable=True)
    complex_carbs = Column(Float, nullable=True)
    fats = Column(Float)
    fiber = Column(Float)


class BaseMicroNutritionalValue(Base):
    __abstract__ = True
    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calcium = Column(Float)
    iron = Column(Float)
    zinc = Column(Float)
    magnesium = Column(Float)


class PatientMacroNutritionalValue(BaseMacroNutritionalValue):
    __tablename__ = "patient_macro_nutritional_values"

    food_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_food_items.id", ondelete="CASCADE"),
    )
    food_item = relationship(
        "PatientFoodItem", back_populates="macro_nutritional_values"
    )


class PatientMicroNutritionalValue(BaseMicroNutritionalValue):
    __tablename__ = "patient_micro_nutritional_values"

    food_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_food_items.id", ondelete="CASCADE"),
    )
    food_item = relationship(
        "PatientFoodItem", back_populates="micro_nutritional_values"
    )


class PatientFoodItem(Base):
    __tablename__ = "patient_food_items"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    name = Column(String)
    coordinates = Column(ARRAY(Float))
    serving_size = Column(String)
    serving_quantity = Column(Float)
    serving_unit = Column(String)
    category = Column(String)
    macro_nutritional_values = relationship(
        "PatientMacroNutritionalValue",
        back_populates="food_item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    micro_nutritional_values = relationship(
        "PatientMicroNutritionalValue",
        back_populates="food_item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    meal_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_meals.id", ondelete="CASCADE")
    )
    meal = relationship("PatientMeal", back_populates="items")


class PatientTotalMacroNutritionalValue(BaseMacroNutritionalValue):
    __tablename__ = "patient_total_macro_nutritional_values"

    meal_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_meals.id", ondelete="CASCADE")
    )
    meal = relationship(
        "PatientMeal", back_populates="total_macro_nutritional_value"
    )


class PatientTotalMicroNutritionalValue(BaseMicroNutritionalValue):
    __tablename__ = "patient_total_micro_nutritional_values"

    meal_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_meals.id", ondelete="CASCADE")
    )
    meal = relationship(
        "PatientMeal", back_populates="total_micro_nutritional_value"
    )


class PatientMeal(Base):
    __tablename__ = "patient_meals"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    name = Column(String, nullable=True)
    type = Column(String)
    slot = Column(String, nullable=True, index=True)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)
    items = relationship(
        "PatientFoodItem", back_populates="meal", cascade="all, delete-orphan"
    )
    total_macro_nutritional_value = relationship(
        "PatientTotalMacroNutritionalValue",
        back_populates="meal",
        uselist=False,
        cascade="all, delete-orphan",
    )
    total_micro_nutritional_value = relationship(
        "PatientTotalMicroNutritionalValue",
        back_populates="meal",
        uselist=False,
        cascade="all, delete-orphan",
    )
    image_url = Column(Text, nullable=True)
    audio_url = Column(Text, nullable=True)
    description = Column(String, nullable=True)
    source = Column(String, nullable=False)
    feedback = Column(String, nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    score = Column(Float, nullable=True)
    analyzed = Column(Boolean, default=False)
    analyzed_at = Column(DateTime, nullable=True)
    extraction_confidence = Column(String, nullable=True)
    preview_trace_id = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    ai_insight = Column(Text, nullable=True)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
    )
    patient = relationship("Patient", back_populates="meals")
