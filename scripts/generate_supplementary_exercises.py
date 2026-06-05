"""Generate supplementary exercises missing from the free-exercise-db catalog.

Sends batches of exercise names to an LLM to produce complete exercise objects
(matching the free-exercise-db schema + aliases) and writes a JSON file that can
be fed straight into import_exercises.py.

Usage:
    python scripts/generate_supplementary_exercises.py                          # writes data/supplementary_exercises.json
    python scripts/generate_supplementary_exercises.py --dry-run                # preview without writing
    python scripts/generate_supplementary_exercises.py -o /tmp/exercises.json   # custom output path

Then import:
    EXERCISE_IMAGE_BASE_URL=https://exercises.aihealth.in \
      python scripts/import_exercises.py data/supplementary_exercises.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import litellm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_supplementary")

litellm.drop_params = True
litellm.set_verbose = False

MISSING_EXERCISES = [
    # Compound / full-body
    "Burpee",
    "Wall Sit",
    "Cossack Squat",
    "Hip Airplane",
    # Chest
    "Larsen Press",
    "Spoto Press",
    # Back
    "Pendlay Row",
    "Seal Row",
    "Helms Row",
    "Meadows Row",
    "Chest Supported Row",
    "Incline Barbell Row",
    "Ring Row",
    # Shoulders
    "Cable Lateral Raise",
    "Lu Raise",
    "Bus Driver",
    "Prone Y Raise",
    "Prone I Raise",
    "Prone T Raise",
    # Legs
    "Pause Squat",
    "Tempo Squat",
    "Pin Squat",
    "Anderson Squat",
    "Curtsy Lunge",
    "Box Step Up",
    "Nordic Hamstring Curl",
    "Banded Walk",
    # Landmine
    "Landmine Press",
    "Landmine Row",
    "Landmine Squat",
    # Arms
    "Bayesian Curl",
    # Deadlift variations
    "Block Pull",
    # Core
    "Ab Wheel Rollout",
    "Hollow Hold",
    "L-Sit",
    # Olympic
    "Push Jerk",
    # Gymnastics / rings
    "Ring Push-Up",
    # Cardio / conditioning
    "Assault Bike",
    "Ski Erg",
    "Sled Pull",
]

SYSTEM_PROMPT = """\
You are a fitness database expert. Generate complete exercise entries for a \
workout catalog database. Each exercise must match this exact JSON schema:

{
  "id": "Snake_Case_Name",
  "name": "Display Name",
  "force": "push" | "pull" | "static" | null,
  "level": "beginner" | "intermediate" | "expert",
  "mechanic": "compound" | "isolation" | null,
  "equipment": "barbell" | "dumbbell" | "cable" | "machine" | "body only" | "bands" | "kettlebells" | "other" | null,
  "category": "strength" | "stretching" | "plyometrics" | "cardio" | "powerlifting" | "strongman" | "olympic weightlifting",
  "primaryMuscles": ["muscle1"],
  "secondaryMuscles": ["muscle2"],
  "instructions": ["Step 1.", "Step 2.", ...],
  "aliases": ["common name 1", "gym slang", "abbreviation"],
  "images": []
}

Rules:
- id: snake_case version of the name (e.g., "Pendlay_Row")
- instructions: 3-6 clear steps a gym-goer can follow
- aliases: 2-6 common alternative names, nicknames, abbreviations people use \
  in gyms or voice input. All lowercase. Do NOT include the original name.
- primaryMuscles/secondaryMuscles: use standard muscle group names: \
  abdominals, abductors, adductors, biceps, calves, chest, forearms, glutes, \
  hamstrings, lats, lower back, middle back, neck, quadriceps, shoulders, \
  traps, triceps
- images: always empty array (we host our own)
- Be accurate about force, mechanic, equipment, level, and category

Return ONLY a valid JSON array of exercise objects, nothing else.
"""


def _slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


async def _generate_batch(names: list[str]) -> list[dict]:
    user_msg = (
        "Generate complete exercise entries for these exercises:\n"
        + json.dumps(names)
    )

    response = await litellm.acompletion(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    exercises = _extract_exercises(parsed)

    for ex in exercises:
        if "id" not in ex or not ex["id"]:
            ex["id"] = _slugify(ex.get("name", "unknown"))
        if "images" not in ex:
            ex["images"] = []
        if "aliases" not in ex:
            ex["aliases"] = []

    return exercises


def _extract_exercises(data) -> list[dict]:
    """Recursively find exercise objects regardless of LLM response shape."""
    if isinstance(data, list):
        result = []
        for item in data:
            if isinstance(item, dict) and "name" in item:
                result.append(item)
            elif isinstance(item, (dict, list)):
                result.extend(_extract_exercises(item))
        return result

    if isinstance(data, dict):
        if "name" in data and "primaryMuscles" in data:
            return [data]
        result = []
        for value in data.values():
            if isinstance(value, dict) and "name" in value:
                result.append(value)
            elif isinstance(value, (dict, list)):
                result.extend(_extract_exercises(value))
        return result

    return []


async def run(*, dry_run: bool = False, output: str = "data/supplementary_exercises.json", batch_size: int = 15) -> None:
    logger.info("Generating %d missing exercises", len(MISSING_EXERCISES))

    all_exercises: list[dict] = []
    batches = [MISSING_EXERCISES[i:i + batch_size] for i in range(0, len(MISSING_EXERCISES), batch_size)]

    for i, batch in enumerate(batches):
        logger.info("Batch %d/%d (%d exercises): %s", i + 1, len(batches), len(batch), batch)
        try:
            result = await _generate_batch(batch)
            all_exercises.extend(result)
            logger.info("  -> got %d exercises", len(result))
        except Exception:
            logger.exception("Batch %d failed, skipping", i + 1)

    logger.info("Generated %d total exercises", len(all_exercises))

    if dry_run:
        for ex in all_exercises:
            aliases = ", ".join(ex.get("aliases", []))
            print(f"  {ex['name']} [{ex.get('category')}] -> aliases: [{aliases}]")
        return

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_exercises, indent=2, ensure_ascii=False))
    logger.info("Wrote %s", out_path)
    logger.info(
        "Now import with:\n"
        "  EXERCISE_IMAGE_BASE_URL=https://exercises.aihealth.in \\\n"
        "    python scripts/import_exercises.py %s",
        out_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate supplementary exercises via LLM")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("-o", "--output", default="data/supplementary_exercises.json", help="Output JSON path")
    parser.add_argument("--batch-size", type=int, default=15, help="Exercises per LLM call")
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, output=args.output, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
