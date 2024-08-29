import uuid
from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    String,
    ForeignKey,
    DateTime,
    Text,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import UUID
from lib.models import Base


class PatientMacroNutritionalValue(Base):
    __tablename__ = "patient_macro_nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calories = Column(String)
    proteins = Column(String)
    carbohydrates = Column(String)
    fats = Column(String)
    fiber = Column(String)
    food_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_food_items.id", ondelete="CASCADE"),
    )
    food_item = relationship(
        "PatientFoodItem", back_populates="macro_nutritional_values"
    )


class PatientMicroNutritionalValue(Base):
    __tablename__ = "patient_micro_nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calcium = Column(String)
    iron = Column(String)
    zinc = Column(String)
    magnesium = Column(String)
    cholesterol = Column(String)
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


class PatientTotalMacroNutritionalValue(Base):
    __tablename__ = "patient_total_macro_nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calories = Column(String)
    proteins = Column(String)
    carbohydrates = Column(String)
    fats = Column(String)
    fiber = Column(String)
    meal_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_meals.id", ondelete="CASCADE")
    )
    meal = relationship(
        "PatientMeal", back_populates="total_macro_nutritional_value"
    )


class PatientTotalMicroNutritionalValue(Base):
    __tablename__ = "patient_total_micro_nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calcium = Column(String)
    iron = Column(String)
    zinc = Column(String)
    magnesium = Column(String)
    cholesterol = Column(String)
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
    time = Column(DateTime)
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
    image_url = Column(Text)
    description = Column(String, nullable=True)
    source = Column(String, nullable=False)
    feedback = Column(String, nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    score = Column(Float, nullable=True)
    context_id = Column(String, nullable=True)
    analyzed = Column(Boolean, default=False)
    analyzed_at = Column(DateTime, nullable=True)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
    )
    patient = relationship("Patient", back_populates="meals")
