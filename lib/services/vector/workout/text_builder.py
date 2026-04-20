"""Text representation builder for patient workout sessions."""

from typing import Any, Dict


class WorkoutTextReprBuilder:
    """Builder for creating embeddable text representations of workouts."""

    @staticmethod
    def build(workout: Dict[str, Any]) -> str:
        type_str = (workout.get("type") or "workout").capitalize()
        date = workout.get("date") or "unknown date"
        time = workout.get("time") or ""
        duration = workout.get("duration_minutes")
        intensity = workout.get("intensity")
        calories = workout.get("calories_burned")
        notes = (workout.get("notes") or "").strip()
        exercises = workout.get("exercises") or []

        header_bits = [f"{type_str} workout on {date}"]
        if time:
            header_bits.append(f"at {time}")
        if duration is not None:
            header_bits.append(f"({duration} min")
            if intensity:
                header_bits[-1] += f", {intensity}"
            header_bits[-1] += ")"
        elif intensity:
            header_bits.append(f"({intensity})")

        parts = [" ".join(header_bits) + "."]

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
