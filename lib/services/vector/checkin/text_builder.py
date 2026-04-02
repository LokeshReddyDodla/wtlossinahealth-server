"""Text representation builders for sleep check-in, mood entry, and symptom entry data."""

from typing import Any, Dict

_QUALITY_LABELS = {1: "very poor", 2: "poor", 3: "fair", 4: "good", 5: "excellent"}
_MOOD_LABELS = {1: "very bad", 2: "bad", 3: "neutral", 4: "good", 5: "great"}
_SEVERITY_LABELS = {1: "minimal", 2: "mild", 3: "moderate", 4: "severe", 5: "very severe"}

_GI_SYMPTOMS = {"nausea", "vomiting", "constipation", "diarrhea", "bloating", "heartburn"}
_NEURO_SYMPTOMS = {"headache", "dizziness", "brain_fog", "anxiety", "insomnia"}
_PAIN_SYMPTOMS = {"muscle_pain", "joint_pain", "headache"}


class CheckinTextReprBuilder:
    """Builds human-readable text representations for embedding."""

    @staticmethod
    def build_sleep(data: Dict[str, Any]) -> str:
        quality = data.get("quality", 3)
        hours = data.get("hours_slept", 0)
        bed_time = data.get("bed_time", "unknown")
        wake_time = data.get("wake_time", "unknown")
        checkin_date = data.get("checkin_date", "unknown date")
        notes = (data.get("notes") or "").strip()

        quality_label = _QUALITY_LABELS.get(quality, "unknown")

        parts = [
            f"Sleep check-in on {checkin_date}.",
            f"Quality: {quality}/5 ({quality_label}).",
            f"Duration: {hours}h.",
            f"Bed time: {bed_time}, Wake time: {wake_time}.",
        ]

        # Interpretation
        if hours < 6:
            parts.append("Short sleep duration — below recommended 7-9 hours.")
        elif hours > 9:
            parts.append("Long sleep duration — above typical 7-9 hour range.")
        else:
            parts.append("Adequate sleep duration within 7-9 hour range.")

        if quality <= 2:
            parts.append("Self-reported poor sleep quality.")
        elif quality >= 4:
            parts.append("Self-reported good sleep quality.")

        if notes:
            parts.append(f"Notes: {notes}")

        return " ".join(parts)

    @staticmethod
    def build_mood(data: Dict[str, Any]) -> str:
        level = data.get("level", 3)
        emoji = data.get("emoji", "neutral")
        tags = data.get("tags", [])
        recorded_at = data.get("recorded_at", "unknown time")
        checkin_date = data.get("checkin_date", "unknown date")
        notes = (data.get("notes") or "").strip()

        mood_label = _MOOD_LABELS.get(level, "unknown")

        parts = [
            f"Mood entry on {checkin_date} at {recorded_at}.",
            f"Level: {level}/5 ({mood_label}).",
        ]

        if tags:
            parts.append(f"Tags: {', '.join(tags)}.")

        # Interpretation
        if level <= 2:
            parts.append("Patient is reporting a negative mood state.")
        elif level >= 4:
            parts.append("Patient is reporting a positive mood state.")
        else:
            parts.append("Patient is reporting a neutral mood state.")

        if notes:
            parts.append(f"Notes: {notes}")

        return " ".join(parts)

    @staticmethod
    def build_symptoms(data: Dict[str, Any]) -> str:
        checkin_date = data.get("checkin_date", "unknown date")
        symptoms = data.get("symptoms", [])
        notes = (data.get("notes") or "").strip()

        count = len(symptoms)
        parts = [f"Symptom entry on {checkin_date}. Reported {count} symptom(s)."]

        severities = []
        symptom_names = set()
        for s in symptoms:
            name = s.get("symptom_name", "unknown")
            severity = s.get("severity", 1)
            label = _SEVERITY_LABELS.get(severity, "unknown")
            display_name = (s.get("custom_label") or name) if name == "other" else name.replace("_", " ")
            parts.append(f"{display_name.capitalize()}: severity {severity}/5 ({label}).")
            severities.append(severity)
            symptom_names.add(name)

        if severities:
            max_sev = max(severities)
            avg_sev = sum(severities) / len(severities)
            if max_sev >= 4:
                assessment = "high"
            elif max_sev >= 3:
                assessment = "moderate"
            else:
                assessment = "low"
            parts.append(
                f"Overall severity: {assessment} (max {max_sev}/5, avg {avg_sev:.1f}/5)."
            )

        # Symptom group interpretations
        gi = symptom_names & _GI_SYMPTOMS
        if gi:
            parts.append(f"GI symptoms present ({', '.join(sorted(gi))}).")

        neuro = symptom_names & _NEURO_SYMPTOMS
        if neuro:
            parts.append(f"Neurological/psychological symptoms present ({', '.join(sorted(neuro))}).")

        pain = symptom_names & _PAIN_SYMPTOMS
        if pain:
            parts.append(f"Pain symptoms present ({', '.join(sorted(pain))}).")

        if notes:
            parts.append(f"Notes: {notes}")

        return " ".join(parts)
