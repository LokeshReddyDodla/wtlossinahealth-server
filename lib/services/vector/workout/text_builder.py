"""Text representation builder for patient workout sessions."""

from typing import Any, Dict, List


class WorkoutTextReprBuilder:
    """Builder for creating embeddable text representations of workouts."""

    @staticmethod
    def build(workout: Dict[str, Any]) -> str:
        segments: List[Dict[str, Any]] = workout.get("segments") or []

        date = workout.get("date") or "unknown date"
        time = workout.get("time") or ""
        intensity = workout.get("intensity")
        calories = workout.get("calories_burned")
        notes = (workout.get("notes") or "").strip()

        if segments:
            seg_types = list({seg.get("type") for seg in segments if seg.get("type")})
            type_str = seg_types[0].capitalize() if len(seg_types) == 1 else " + ".join(
                t.capitalize() for t in sorted(seg_types)
            )
            total_duration = sum(seg.get("duration_minutes") or 0 for seg in segments) or None
        else:
            type_str = (workout.get("type") or "workout").capitalize()
            total_duration = workout.get("duration_minutes")

        header_bits = [f"{type_str} workout on {date}"]
        if time:
            header_bits.append(f"at {time}")
        if total_duration is not None:
            header_bits.append(f"({total_duration} min")
            if intensity:
                header_bits[-1] += f", {intensity}"
            header_bits[-1] += ")"
        elif intensity:
            header_bits.append(f"({intensity})")

        parts = [" ".join(header_bits) + "."]

        if segments and len(segments) > 1:
            for i, seg in enumerate(segments, 1):
                seg_type = (seg.get("type") or "segment").capitalize()
                seg_dur = seg.get("duration_minutes")
                dur_str = f" ({seg_dur} min)" if seg_dur else ""
                exercises = seg.get("exercises") or []
                parts.append(f"Segment {i}: {seg_type}{dur_str}")
                for ex in exercises:
                    parts.append(f"- {WorkoutTextReprBuilder._format_exercise(ex)}")
        else:
            exercises = (
                (segments[0].get("exercises") or []) if segments
                else (workout.get("exercises") or [])
            )
            if exercises:
                parts.append("Exercises:")
                for ex in exercises:
                    parts.append(f"- {WorkoutTextReprBuilder._format_exercise(ex)}")

        if calories is not None:
            parts.append(f"Calories burned: {calories}.")

        if notes:
            parts.append(f"Notes: {notes}")

        return " ".join(parts)

    @staticmethod
    def _format_exercise(ex: Dict[str, Any]) -> str:
        name = ex.get("exercise_name") or ex.get("exercise_id") or "exercise"
        sets = ex.get("sets")
        reps = ex.get("reps")
        weight = ex.get("weight_kg")
        duration = ex.get("duration_seconds")
        distance = ex.get("distance_m")

        segments: list[str] = []
        if sets and reps:
            seg = f"{sets}x{reps}"
            if weight:
                seg += f" @ {weight}kg"
            segments.append(seg)
        elif sets:
            segments.append(f"{sets} sets")
        if duration:
            segments.append(f"{duration}s")
        if distance:
            segments.append(f"{distance}m")

        detail = ", ".join(segments)
        return f"{name}: {detail}" if detail else name
