"""Schemas for voice-based workout logging.

The frontend maintains a running workout session. On each voice input,
it sends the current state alongside the audio. The server transcribes,
interprets with LLM context, fuzzy-matches exercises from the catalog,
and returns the updated session state.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from lib.schemas.exercise import ExerciseResponse


# ── Session state (frontend ↔ backend) ──────────────────────────────────

class SetEntry(BaseModel):
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None


class SessionExercise(BaseModel):
    exercise_name: str
    exercise_id: Optional[str] = None
    sets: list[SetEntry] = Field(default_factory=list)


# ── LLM extraction (internal) ───────────────────────────────────────────

LLMAction = Literal[
    "add_set",
    "new_exercise",
    "update_last_set",
    "remove_exercise",
    "finish",
    "unclear",
]

VoiceAction = Literal[
    "add_set",
    "new_exercise",
    "update_last_set",
    "remove_exercise",
    "needs_confirmation",
    "finish",
    "unclear",
]


class ParsedSet(BaseModel):
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    duration_seconds: Optional[int] = None
    distance_m: Optional[float] = None


class ExerciseActionItem(BaseModel):
    """One exercise/action extracted from the utterance."""

    action: LLMAction
    exercise_name: Optional[str] = Field(
        None, description="Canonical exercise name. None for finish/unclear."
    )
    sets: list[ParsedSet] = Field(
        default_factory=list,
        description="One or more sets. E.g. '3 sets of 10 at 80kg' → 3 entries.",
    )


class VoiceWorkoutExtraction(BaseModel):
    """Structured output the LLM returns for each voice utterance."""

    items: list[ExerciseActionItem] = Field(
        ...,
        description="One entry per exercise/action in the utterance. "
        "A single-exercise utterance has 1 item; multi-exercise speech has several.",
    )
    workout_type: Optional[str] = Field(
        None, description="Inferred workout type: strength, cardio, hiit, mobility, mixed, other.",
    )
    notes: Optional[str] = Field(
        None, description="Any extra context the user mentioned.",
    )
    interpretation: str = Field(
        ..., description="Short human-readable summary of what was understood.",
    )


# ── API request / response ──────────────────────────────────────────────

class WorkoutVoiceSessionState(BaseModel):
    exercises: list[SessionExercise] = Field(default_factory=list)


class ExerciseMatch(BaseModel):
    exercise_id: str
    exercise_name: str
    confidence: float = Field(ge=0, le=1)
    catalog_entry: Optional[ExerciseResponse] = None


class WorkoutVoiceUpdate(BaseModel):
    """What changed in this voice turn."""

    action: VoiceAction
    exercise_index: Optional[int] = Field(
        None, description="Index in session.exercises that was affected.",
    )
    exercise_match: Optional[ExerciseMatch] = None
    candidates: list[ExerciseMatch] = Field(
        default_factory=list,
        description="Alternative matches for the user to pick from.",
    )
    sets_added: list[SetEntry] = Field(default_factory=list)
    pending_sets: list[SetEntry] = Field(
        default_factory=list,
        description="Sets waiting to be added once the user confirms an exercise. "
        "Only populated when action=needs_confirmation.",
    )
    spoken_exercise_name: Optional[str] = Field(
        None,
        description="The raw exercise name the user said. "
        "Only populated when action=needs_confirmation.",
    )
    interpretation: str


class WorkoutVoiceResponse(BaseModel):
    transcript: str
    audio_url: Optional[str] = None
    update: WorkoutVoiceUpdate
    updates: list[WorkoutVoiceUpdate] = Field(default_factory=list)
    session: WorkoutVoiceSessionState
