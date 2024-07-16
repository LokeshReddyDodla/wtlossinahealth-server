import uuid
from sqlalchemy import (
    ARRAY,
    JSON,
    Column,
    Float,
    Integer,
    String,
    ForeignKey,
    DateTime,
    Text,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
from lib.models import Base


class NutritionalValues(Base):
    __tablename__ = "nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calories = Column(String)
    proteins = Column(String)
    carbohydrates = Column(String)
    fats = Column(String)
    fiber = Column(String)
    food_item_id = Column(UUID(as_uuid=True), ForeignKey("food_items.id"))
    food_item = relationship("FoodItem", back_populates="nutritional_values")


class FoodItem(Base):
    __tablename__ = "food_items"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    name = Column(String)
    coordinates = Column(ARRAY(Float))
    serving_size = Column(String)
    serving_quantity = Column(Float)
    serving_unit = Column(String)
    nutritional_values = relationship(
        "NutritionalValues", back_populates="food_item"
    )
    meal_id = Column(UUID(as_uuid=True), ForeignKey("meals.id"))
    meal = relationship("Meal", back_populates="items")


class TotalNutritionalValue(Base):
    __tablename__ = "total_nutritional_values"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    calories = Column(String)
    proteins = Column(String)
    carbohydrates = Column(String)
    fats = Column(String)
    fiber = Column(String)
    meal_id = Column(UUID(as_uuid=True), ForeignKey("meals.id"))
    meal = relationship("Meal", back_populates="total_nutritional_value")


class Meal(Base):
    __tablename__ = "meals"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    type = Column(String)
    time = Column(DateTime)
    items = relationship("FoodItem", back_populates="meal")
    total_nutritional_value = relationship(
        "TotalNutritionalValue", back_populates="meal"
    )
    image_url = Column(Text)
    description = Column(String, nullable=True)
    source = Column(String, nullable=True)
    feedback = Column(String)
    tags = Column(ARRAY(String))
    context_id = Column(String)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    user = relationship("User", back_populates="meals")
