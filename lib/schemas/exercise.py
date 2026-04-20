"""Schemas for the exercise catalog API."""

from __future__ import annotations

from pydantic import BaseModel


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
