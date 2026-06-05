"""Exercise catalog — seeded from yuhonas/free-exercise-db (public domain)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR

from lib.models import Base


class Exercise(Base):
    __tablename__ = "exercises"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)

    force = Column(String, nullable=True)           # push, pull, static
    level = Column(String, nullable=False)          # beginner, intermediate, expert
    mechanic = Column(String, nullable=True)        # compound, isolation
    equipment = Column(String, nullable=True)       # barbell, dumbbell, body only, ...
    category = Column(String, nullable=False)       # strength, cardio, stretching, ...

    primary_muscles = Column(ARRAY(String), nullable=False, default=list)
    secondary_muscles = Column(ARRAY(String), nullable=False, default=list)
    aliases = Column(ARRAY(String), nullable=False, default=list, server_default="{}")

    instructions = Column(ARRAY(Text), nullable=False, default=list)
    image_urls = Column(ARRAY(String), nullable=False, default=list)

    search_tsv = Column(TSVECTOR, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    __table_args__ = (
        Index("ix_exercises_category", "category"),
        Index("ix_exercises_level", "level"),
        Index("ix_exercises_equipment", "equipment"),
        Index("ix_exercises_primary_muscles", "primary_muscles", postgresql_using="gin"),
        Index("ix_exercises_aliases", "aliases", postgresql_using="gin"),
        Index("ix_exercises_search_tsv", "search_tsv", postgresql_using="gin"),
    )
