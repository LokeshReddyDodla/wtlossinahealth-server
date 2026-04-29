"""Schemas for the exercise catalog API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExerciseCreate(BaseModel):
    name: str
    level: str = Field(..., description="beginner, intermediate, expert")
    category: str = Field(..., description="strength, cardio, stretching, plyometrics, ...")
    force: str | None = None
    mechanic: str | None = None
    equipment: str | None = None
    primary_muscles: list[str] = []
    secondary_muscles: list[str] = []
    instructions: list[str] = []
    image_urls: list[str] = []


class ExerciseUpdate(BaseModel):
    name: str | None = None
    level: str | None = None
    category: str | None = None
    force: str | None = None
    mechanic: str | None = None
    equipment: str | None = None
    primary_muscles: list[str] | None = None
    secondary_muscles: list[str] | None = None
    instructions: list[str] | None = None
    image_urls: list[str] | None = None


class ExerciseResponse(BaseModel):
    id: str
    name: str
    force: str | None = None
    level: str
    mechanic: str | None = None
    equipment: str | None = None
    category: str
    primary_muscles: list[str]
    secondary_muscles: list[str]
    instructions: list[str]
    image_urls: list[str]


class ExerciseSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ExerciseResponse]


class ExerciseFacetsResponse(BaseModel):
    muscles: list[str]
    equipment: list[str]
    categories: list[str]
    levels: list[str]
