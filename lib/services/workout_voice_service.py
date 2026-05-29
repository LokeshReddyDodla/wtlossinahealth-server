"""Voice workout logging service.

Each call receives an audio clip + the current session state (exercises
logged so far). The service:
  1. Transcribes the audio via Whisper.
  2. Sends the transcript + session context to the LLM for structured extraction.
  3. Fuzzy-matches the exercise name against the catalog.
  4. Returns the updated session state + what changed.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.voice.stt import AudioFormat, SpeechToText
from lib.core.postgres_store import PostgresStore
from lib.models.exercise import Exercise
from lib.schemas.workout_voice import (
    ExerciseMatch,
    SessionExercise,
    SetEntry,
    VoiceWorkoutExtraction,
    WorkoutVoiceResponse,
    WorkoutVoiceSessionState,
    WorkoutVoiceUpdate,
)
from lib.services.exercise_service import ExerciseService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

_MATCH_CONFIDENCE_THRESHOLD = 0.8

_WORKOUT_STT_PROMPT = (
    "A person at the gym logging exercises between sets — "
    "exercise names, sets, reps, weight in kg or lbs, duration, distance."
)

_SYSTEM_PROMPT = """\
You are a workout logging assistant. The user is at the gym and speaks between sets to log what they just did.

Your job: interpret each voice input and extract structured data.

## Rules

1. **Context matters.** The user's current session (exercises logged so far) is provided. Use it to resolve ambiguity:
   - "Same weight, 8 reps" → same exercise as last, same weight_kg, reps=8
   - "Dropped to 70" → same exercise, weight_kg=70
   - "One more set" or "Same again" → repeat the last set of the current exercise
   - "Moving to squats" or "Now squats" → new exercise
   - "3 sets of 10 at 80" or "3 by 10 at 80" → 3 separate set entries

2. **Exercise names:** Output the common/canonical exercise name. E.g. "bench" → "Barbell Bench Press", "skulls" → "Lying Triceps Press", "lat pulldown" → "Lat Pulldown".

3. **Units:** Default to kg for weight. If the user says "lbs" or "pounds", convert to kg (divide by 2.205).

4. **Actions:**
   - `new_exercise` — user mentions an exercise not in the current session
   - `add_set` — user adds a set to an exercise already in the session (or the most recent one)
   - `update_last_set` — user corrects the last set ("actually that was 12 reps not 10")
   - `remove_exercise` — user wants to remove an exercise ("scratch the curls")
   - `finish` — user says they're done ("that's it", "finish workout", "done")
   - `unclear` — can't determine what the user means

5. **workout_type:** Infer from the exercises if possible (strength, cardio, hiit, mobility, mixed, other). Only set this when confident.

6. **interpretation:** Write a short, friendly confirmation. E.g. "Got it — Bench Press set 3: 80kg × 8 reps"
"""


class EmptyTranscriptError(ValueError):
    """Raised when Whisper returns no usable text."""


def _build_user_message(
    transcript: str,
    session: WorkoutVoiceSessionState,
) -> str:
    parts = [f'Voice input: "{transcript}"']

    if session.exercises:
        parts.append("\nCurrent session:")
        for i, ex in enumerate(session.exercises):
            sets_desc = []
            for j, s in enumerate(ex.sets):
                pieces = []
                if s.weight_kg is not None:
                    pieces.append(f"{s.weight_kg}kg")
                if s.reps is not None:
                    pieces.append(f"{s.reps} reps")
                if s.duration_seconds is not None:
                    pieces.append(f"{s.duration_seconds}s")
                if s.distance_m is not None:
                    pieces.append(f"{s.distance_m}m")
                sets_desc.append(f"  Set {j + 1}: {' × '.join(pieces) or 'empty'}")
            sets_text = "\n".join(sets_desc) if sets_desc else "  (no sets yet)"
            parts.append(f"{i + 1}. {ex.exercise_name}\n{sets_text}")
    else:
        parts.append("\nCurrent session: empty (this is the first exercise)")

    return "\n".join(parts)


class WorkoutVoiceService:
    def __init__(
        self,
        *,
        gateway: ModelGateway,
        stt: SpeechToText,
        postgres_store: PostgresStore,
    ) -> None:
        self._gateway = gateway
        self._stt = stt
        self.postgres_store = postgres_store

    async def process_voice_input(
        self,
        *,
        audio_bytes: bytes,
        audio_format: AudioFormat,
        session: WorkoutVoiceSessionState,
        text: Optional[str] = None,
    ) -> WorkoutVoiceResponse:
        transcript_result = await self._stt.transcribe(
            audio_bytes, audio_format=audio_format, prompt=_WORKOUT_STT_PROMPT,
        )
        transcript = transcript_result.text.strip()
        if text:
            transcript = f"{text} {transcript}"

        if not transcript.strip():
            raise EmptyTranscriptError("Could not understand the audio. Please try again.")

        return await self._interpret(transcript, session)

    async def process_text_input(
        self,
        *,
        transcript: str,
        session: WorkoutVoiceSessionState,
    ) -> WorkoutVoiceResponse:
        return await self._interpret(transcript, session)

    # ── Shared interpretation pipeline ───────────────────────────────────

    async def _interpret(
        self,
        transcript: str,
        session: WorkoutVoiceSessionState,
    ) -> WorkoutVoiceResponse:
        extraction, _meta = await self._extract(transcript, session)

        match: Optional[ExerciseMatch] = None
        candidates: list[ExerciseMatch] = []

        if extraction.exercise_name and extraction.action not in ("finish", "unclear"):
            match, candidates = await self._match_exercise(extraction.exercise_name)

        updated_session, update = self._apply_extraction(
            session=session,
            extraction=extraction,
            match=match,
            candidates=candidates,
        )

        return WorkoutVoiceResponse(
            transcript=transcript,
            update=update,
            session=updated_session,
        )

    # ── LLM extraction ──────────────────────────────────────────────────

    async def _extract(
        self,
        transcript: str,
        session: WorkoutVoiceSessionState,
    ) -> tuple[VoiceWorkoutExtraction, object]:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(transcript, session)},
        ]
        return await self._gateway.extract(
            messages=messages,
            response_model=VoiceWorkoutExtraction,
            task=ModelTask.STRUCTURED_ANALYSIS,
            temperature=0.1,
        )

    # ── Exercise matching ────────────────────────────────────────────────

    @with_postgres_session
    async def _match_exercise(
        self,
        exercise_name: str,
        *,
        postgres_session: AsyncSession,
    ) -> tuple[Optional[ExerciseMatch], list[ExerciseMatch]]:
        ts_query = func.plainto_tsquery("english", exercise_name)
        escaped = exercise_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (
            select(Exercise)
            .where(
                or_(
                    Exercise.search_tsv.op("@@")(ts_query),
                    Exercise.name.ilike(f"%{escaped}%", escape="\\"),
                )
            )
            .order_by(Exercise.name.asc())
            .limit(5)
        )
        rows = (await postgres_session.execute(stmt)).scalars().all()

        if not rows:
            return None, []

        matches = []
        name_lower = exercise_name.lower()
        for row in rows:
            row_name_lower = row.name.lower()
            if row_name_lower == name_lower:
                confidence = 1.0
            elif name_lower in row_name_lower or row_name_lower in name_lower:
                confidence = 0.85
            else:
                confidence = 0.6
            matches.append(
                ExerciseMatch(
                    exercise_id=row.id,
                    exercise_name=row.name,
                    confidence=confidence,
                    catalog_entry=ExerciseService.to_response(row),
                )
            )

        matches.sort(key=lambda m: m.confidence, reverse=True)
        best = matches[0]
        candidates = matches[1:] if len(matches) > 1 else []

        return best, candidates

    # ── Apply extraction to session ──────────────────────────────────────

    @staticmethod
    def _needs_confirmation(
        extraction: VoiceWorkoutExtraction,
        match: Optional[ExerciseMatch],
    ) -> bool:
        if extraction.action in ("finish", "unclear", "remove_exercise"):
            return False
        if extraction.action in ("add_set", "update_last_set"):
            return False
        if match is None:
            return True
        return match.confidence < _MATCH_CONFIDENCE_THRESHOLD

    def _apply_extraction(
        self,
        *,
        session: WorkoutVoiceSessionState,
        extraction: VoiceWorkoutExtraction,
        match: Optional[ExerciseMatch],
        candidates: list[ExerciseMatch],
    ) -> tuple[WorkoutVoiceSessionState, WorkoutVoiceUpdate]:
        exercises = [ex.model_copy(deep=True) for ex in session.exercises]
        new_sets = [SetEntry(**s.model_dump()) for s in extraction.sets]

        exercise_name = match.exercise_name if match else (extraction.exercise_name or "Unknown")
        exercise_id = match.exercise_id if match else None

        if self._needs_confirmation(extraction, match):
            all_candidates = []
            if match:
                all_candidates.append(match)
            all_candidates.extend(candidates)
            return (
                WorkoutVoiceSessionState(exercises=exercises),
                WorkoutVoiceUpdate(
                    action="needs_confirmation",
                    candidates=all_candidates,
                    pending_sets=new_sets,
                    spoken_exercise_name=extraction.exercise_name,
                    interpretation="Not sure which exercise — did you mean one of these?",
                ),
            )

        if extraction.action == "new_exercise":
            exercises.append(
                SessionExercise(
                    exercise_name=exercise_name,
                    exercise_id=exercise_id,
                    sets=new_sets,
                )
            )
            exercise_index = len(exercises) - 1

        elif extraction.action == "add_set":
            exercise_index = self._find_exercise_index(
                exercises, exercise_name, extraction.exercise_name, fallback_to_last=True,
            )
            if exercise_index is not None:
                exercises[exercise_index].sets.extend(new_sets)
                if exercise_id and not exercises[exercise_index].exercise_id:
                    exercises[exercise_index].exercise_id = exercise_id
            elif exercise_id:
                exercises.append(
                    SessionExercise(
                        exercise_name=exercise_name,
                        exercise_id=exercise_id,
                        sets=new_sets,
                    )
                )
                exercise_index = len(exercises) - 1
            else:
                all_candidates = []
                if match:
                    all_candidates.append(match)
                all_candidates.extend(candidates)
                return (
                    WorkoutVoiceSessionState(exercises=exercises),
                    WorkoutVoiceUpdate(
                        action="needs_confirmation",
                        candidates=all_candidates,
                        pending_sets=new_sets,
                        spoken_exercise_name=extraction.exercise_name,
                        interpretation="Not sure which exercise — did you mean one of these?",
                    ),
                )

        elif extraction.action == "update_last_set":
            exercise_index = self._find_exercise_index(
                exercises, exercise_name, extraction.exercise_name, fallback_to_last=True,
            )
            if exercise_index is not None and exercises[exercise_index].sets:
                last_set = exercises[exercise_index].sets[-1]
                for s in new_sets[:1]:
                    if s.weight_kg is not None:
                        last_set.weight_kg = s.weight_kg
                    if s.reps is not None:
                        last_set.reps = s.reps
                    if s.duration_seconds is not None:
                        last_set.duration_seconds = s.duration_seconds
                    if s.distance_m is not None:
                        last_set.distance_m = s.distance_m
            else:
                exercise_index = None

        elif extraction.action == "remove_exercise":
            exercise_index = self._find_exercise_index(exercises, exercise_name, extraction.exercise_name)
            if exercise_index is not None:
                exercises.pop(exercise_index)

        elif extraction.action == "finish":
            exercise_index = None

        else:
            exercise_index = None

        update = WorkoutVoiceUpdate(
            action=extraction.action,
            exercise_index=exercise_index,
            exercise_match=match,
            candidates=candidates,
            sets_added=new_sets,
            interpretation=extraction.interpretation,
        )
        updated_session = WorkoutVoiceSessionState(exercises=exercises)
        return updated_session, update

    @staticmethod
    def _find_exercise_index(
        exercises: list[SessionExercise],
        matched_name: str,
        raw_name: Optional[str],
        *,
        fallback_to_last: bool = False,
    ) -> Optional[int]:
        if not exercises:
            return None

        matched_lower = matched_name.lower()
        raw_lower = raw_name.lower() if raw_name else ""

        for i, ex in enumerate(exercises):
            ex_lower = ex.exercise_name.lower()
            if ex_lower == matched_lower or ex_lower == raw_lower:
                return i
            if ex.exercise_id and ex.exercise_id == matched_lower.replace(" ", "_"):
                return i

        return len(exercises) - 1 if fallback_to_last else None
