"""Voice workout logging service.

Voice operates on a single segment at a time. Each call receives an audio
clip + the current segment state (exercises logged so far). The service:
  1. Transcribes the audio via Whisper.
  2. Sends the transcript + session context to the LLM for structured extraction.
  3. Fuzzy-matches the exercise name against the catalog.
  4. Returns the updated segment state + what changed.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.voice.stt import AudioFormat, BaseSpeechToText
from lib.core.postgres_store import PostgresStore
from lib.models.exercise import Exercise
from lib.schemas.workout_voice import (
    ExerciseActionItem,
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

1. **Multiple exercises in one utterance.** The user may describe several exercises at once. Return one item per exercise in the `items` list. E.g. "I did bench 3×10 at 80, then squats 5×5 at 100, then curls" → 3 items. Never merge distinct exercises into one item.

2. **Context matters.** The user's current session (exercises logged so far) is provided. Use it to resolve ambiguity:
   - "Same weight, 8 reps" → same exercise as last, same weight_kg, reps=8
   - "Dropped to 70" → same exercise, weight_kg=70
   - "One more set" or "Same again" → repeat the last set of the current exercise
   - "Moving to squats" or "Now squats" → new exercise
   - "3 sets of 10 at 80" or "3 by 10 at 80" → 3 separate set entries

3. **Exercise names:** Output the common/canonical exercise name. E.g. "bench" → "Barbell Bench Press", "skulls" → "Lying Triceps Press", "lat pulldown" → "Lat Pulldown".

4. **Units:** Default to kg for weight. If the user says "lbs" or "pounds", convert to kg (divide by 2.205).

5. **Actions (per item):**
   - `new_exercise` — user mentions an exercise not in the current session
   - `add_set` — user adds a set to an exercise already in the session (or the most recent one)
   - `update_last_set` — user corrects the last set ("actually that was 12 reps not 10")
   - `remove_exercise` — user wants to remove an exercise ("scratch the curls")
   - `finish` — user says they're done ("that's it", "finish workout", "done")
   - `unclear` — can't determine what the user means

6. **workout_type:** Infer from the exercises if possible (strength, cardio, hiit, mobility, mixed, other). Only set this when confident.

7. **interpretation:** Write a short, friendly confirmation covering ALL exercises mentioned. E.g. "Got it — Incline Dumbbell Press 3×10 at 45kg, Incline Bench Press 3×10, and Cable Fly 3 sets"
"""


class EmptyTranscriptError(ValueError):
    """Raised when Whisper returns no usable text."""


def _build_user_message(
    transcript: str,
    session: WorkoutVoiceSessionState,
) -> str:
    parts = [f'Voice input: "{transcript}"']

    if session.segment_type:
        parts.append(f"\nSegment type: {session.segment_type}")

    if not session.exercises:
        parts.append("\nCurrent session: empty (this is the first exercise)")
        return "\n".join(parts)

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

    return "\n".join(parts)


class WorkoutVoiceService:
    def __init__(
        self,
        *,
        gateway: ModelGateway,
        stt: BaseSpeechToText,
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
        trace_id = f"trc_{uuid4().hex[:16]}"
        self._gateway.langfuse_trace_input(
            trace_id=trace_id, name="workout_voice", input_text=transcript,
        )
        extraction, _meta = await self._extract(transcript, session, trace_id=trace_id)
        self._gateway.langfuse_trace_output(
            trace_id=trace_id, output_text=str(getattr(extraction, "items", "")),
        )

        logger.info(
            "[WorkoutVoice] LLM extraction | items=%d | interpretation=%r",
            len(extraction.items),
            extraction.interpretation,
        )

        current_session = session
        all_updates: list[WorkoutVoiceUpdate] = []

        for i, item in enumerate(extraction.items):
            match: Optional[ExerciseMatch] = None
            candidates: list[ExerciseMatch] = []

            if item.exercise_name and item.action not in ("finish", "unclear"):
                match, candidates = await self._match_exercise(item.exercise_name)
                logger.info(
                    "[WorkoutVoice] DB match [%d] | query=%r | best=%s(%.2f) | candidates=%d",
                    i,
                    item.exercise_name,
                    match.exercise_name if match else "None",
                    match.confidence if match else 0,
                    len(candidates),
                )

            current_session, update = self._apply_item(
                session=current_session,
                item=item,
                match=match,
                candidates=candidates,
                interpretation=extraction.interpretation,
            )
            all_updates.append(update)

            logger.info(
                "[WorkoutVoice] applied [%d] | action=%s → %s | exercises=%d",
                i,
                item.action,
                update.action,
                len(current_session.exercises),
            )

        logger.info(
            "[WorkoutVoice] pipeline done | exercises_before=%d → exercises_after=%d | updates=%d",
            len(session.exercises),
            len(current_session.exercises),
            len(all_updates),
        )

        return WorkoutVoiceResponse(
            transcript=transcript,
            update=all_updates[0],
            updates=all_updates,
            session=current_session,
        )

    # ── LLM extraction ──────────────────────────────────────────────────

    async def _extract(
        self,
        transcript: str,
        session: WorkoutVoiceSessionState,
        *,
        trace_id: str | None = None,
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
            trace_id=trace_id,
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
                    Exercise.aliases.any(exercise_name),
                )
            )
            .order_by(Exercise.name.asc())
            .limit(5)
        )
        rows = (await postgres_session.execute(stmt)).scalars().all()

        if not rows:
            trgm_stmt = (
                select(Exercise)
                .where(
                    func.similarity(Exercise.name, exercise_name) > 0.15
                )
                .order_by(func.similarity(Exercise.name, exercise_name).desc())
                .limit(5)
            )
            rows = (await postgres_session.execute(trgm_stmt)).scalars().all()

        if not rows:
            return None, []

        matches = []
        name_lower = exercise_name.lower()
        for row in rows:
            row_name_lower = row.name.lower()
            aliases_lower = [a.lower() for a in (row.aliases or [])]
            if row_name_lower == name_lower or name_lower in aliases_lower:
                confidence = 1.0
            elif name_lower in row_name_lower or row_name_lower in name_lower:
                confidence = 0.85
            elif any(name_lower in a or a in name_lower for a in aliases_lower):
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
        item: ExerciseActionItem,
        match: Optional[ExerciseMatch],
    ) -> bool:
        if item.action in ("finish", "unclear", "remove_exercise"):
            return False
        if item.action in ("add_set", "update_last_set"):
            return False
        if match is None:
            return True
        return match.confidence < _MATCH_CONFIDENCE_THRESHOLD

    def _apply_item(
        self,
        *,
        session: WorkoutVoiceSessionState,
        item: ExerciseActionItem,
        match: Optional[ExerciseMatch],
        candidates: list[ExerciseMatch],
        interpretation: str,
    ) -> tuple[WorkoutVoiceSessionState, WorkoutVoiceUpdate]:
        exercises = [ex.model_copy(deep=True) for ex in session.exercises]
        new_sets = [SetEntry(**s.model_dump()) for s in item.sets]

        exercise_name = match.exercise_name if match else (item.exercise_name or "Unknown")
        exercise_id = match.exercise_id if match else None

        if self._needs_confirmation(item, match):
            all_candidates = []
            if match:
                all_candidates.append(match)
            all_candidates.extend(candidates)
            return (
                WorkoutVoiceSessionState(
                    segment_type=session.segment_type,
                    exercises=exercises,
                ),
                WorkoutVoiceUpdate(
                    action="needs_confirmation",
                    candidates=all_candidates,
                    pending_sets=new_sets,
                    spoken_exercise_name=item.exercise_name,
                    interpretation="Not sure which exercise — did you mean one of these?",
                ),
            )

        exercise_index: Optional[int] = None

        if item.action == "new_exercise":
            exercises.append(
                SessionExercise(
                    exercise_name=exercise_name,
                    exercise_id=exercise_id,
                    sets=new_sets,
                )
            )
            exercise_index = len(exercises) - 1

        elif item.action == "add_set":
            idx = self._find_exercise_index(
                exercises, exercise_name, item.exercise_name, fallback_to_last=True,
            )
            if idx is not None:
                exercises[idx].sets.extend(new_sets)
                if exercise_id and not exercises[idx].exercise_id:
                    exercises[idx].exercise_id = exercise_id
                exercise_index = idx
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
                    WorkoutVoiceSessionState(
                        segment_type=session.segment_type,
                        exercises=exercises,
                    ),
                    WorkoutVoiceUpdate(
                        action="needs_confirmation",
                        candidates=all_candidates,
                        pending_sets=new_sets,
                        spoken_exercise_name=item.exercise_name,
                        interpretation="Not sure which exercise — did you mean one of these?",
                    ),
                )

        elif item.action == "update_last_set":
            idx = self._find_exercise_index(
                exercises, exercise_name, item.exercise_name, fallback_to_last=True,
            )
            if idx is not None and exercises[idx].sets:
                last_set = exercises[idx].sets[-1]
                for s in new_sets[:1]:
                    if s.weight_kg is not None:
                        last_set.weight_kg = s.weight_kg
                    if s.reps is not None:
                        last_set.reps = s.reps
                    if s.duration_seconds is not None:
                        last_set.duration_seconds = s.duration_seconds
                    if s.distance_m is not None:
                        last_set.distance_m = s.distance_m
                exercise_index = idx

        elif item.action == "remove_exercise":
            idx = self._find_exercise_index(
                exercises, exercise_name, item.exercise_name,
            )
            if idx is not None:
                exercise_index = idx
                exercises.pop(idx)

        update = WorkoutVoiceUpdate(
            action=item.action,
            exercise_index=exercise_index,
            exercise_match=match,
            candidates=candidates,
            sets_added=new_sets,
            interpretation=interpretation,
        )
        updated_session = WorkoutVoiceSessionState(
            segment_type=session.segment_type,
            exercises=exercises,
        )
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

        if fallback_to_last:
            return len(exercises) - 1

        return None
