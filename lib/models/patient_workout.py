"""Patient-logged workout sessions. Each session contains N exercises pulled from
the catalog (lib/models/exercise.py)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientWorkout(Base):
    __tablename__ = "patient_workouts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    date = Column(Date, nullable=False)
    time = Column(Time, nullable=True)

    # Legacy columns — kept for backward compat, will be dropped in future cleanup.
    # New code reads/writes through segments instead.
    type = Column(String, nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    intensity = Column(String, nullable=True)         # light, moderate, vigorous
    calories_burned = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    source = Column(String, nullable=False, default="app")

    fitness_plan_session_id = Column(UUID(as_uuid=True), nullable=True)

    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    segments = relationship(
        "PatientWorkoutSegment",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="PatientWorkoutSegment.order_index",
    )

    # Legacy relationship — kept for backward compat, will be removed in future cleanup.
    exercises = relationship(
        "PatientWorkoutExercise",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="PatientWorkoutExercise.order_index",
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_workouts_patient_date", "patient_id", "date"),
        Index(
            "ix_workouts_patient_plan_session",
            "patient_id",
            "fitness_plan_session_id",
        ),
    )


class PatientWorkoutSegment(Base):
    __tablename__ = "patient_workout_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workout_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_workouts.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    workout = relationship("PatientWorkout", back_populates="segments")
    exercises = relationship(
        "PatientWorkoutExercise",
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="PatientWorkoutExercise.order_index",
    )

    __table_args__ = (
        Index("ix_workout_segments_workout", "workout_id"),
    )


class PatientWorkoutExercise(Base):
    __tablename__ = "patient_workout_exercises"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Legacy column — kept for backward compat, will be dropped in future cleanup.
    workout_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_workouts.id", ondelete="CASCADE"),
        nullable=True,
    )

    segment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_workout_segments.id", ondelete="CASCADE"),
        nullable=True,
    )

    exercise_id = Column(
        String,
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_name = Column(String, nullable=False)
    order_index = Column(Integer, nullable=False, default=0)

    sets = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)

    workout = relationship("PatientWorkout", back_populates="exercises")
    segment = relationship("PatientWorkoutSegment", back_populates="exercises")
    set_details = relationship(
        "PatientWorkoutSet",
        back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="PatientWorkoutSet.set_number",
    )

    __table_args__ = (
        Index("ix_workout_exercises_workout", "workout_id"),
        Index("ix_workout_exercises_segment", "segment_id"),
        Index("ix_workout_exercises_exercise_id", "exercise_id"),
    )


class PatientWorkoutSet(Base):
    __tablename__ = "patient_workout_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workout_exercise_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number = Column(Integer, nullable=False)

    reps = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)

    exercise = relationship("PatientWorkoutExercise", back_populates="set_details")

    __table_args__ = (
        Index("ix_workout_sets_exercise", "workout_exercise_id"),
    )
