"""Generate common aliases/nicknames for exercises using an LLM.

Reads all exercises from Postgres, batches them, asks the LLM for common
alternative names people use in gyms or voice input, then upserts the aliases
back and rebuilds the search tsvector.

Usage:
    python scripts/generate_exercise_aliases.py
    python scripts/generate_exercise_aliases.py --dry-run   # preview without writing
    python scripts/generate_exercise_aliases.py --batch-size 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import litellm  # noqa: E402
from sqlalchemy import func, select, update  # noqa: E402

from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.models.exercise import Exercise  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_aliases")

litellm.drop_params = True
litellm.set_verbose = False

SYSTEM_PROMPT = """\
You are a fitness expert. For each exercise name provided, generate a JSON array \
of common alternative names, nicknames, abbreviations, and slang that people \
commonly use in gyms or when speaking casually about the exercise.

Rules:
- Include shortened forms (e.g., "bench" for "Barbell Bench Press")
- Include common slang/nicknames (e.g., "skull crushers" for "Lying Triceps Press")
- Include abbreviations people say out loud (e.g., "RDL" for "Romanian Deadlift")
- Include variations without equipment prefix (e.g., "bench press" for "Barbell Bench Press")
- Include the name without special characters (e.g., "34 sit up" for "3/4 Sit-Up")
- Do NOT include the original name itself
- 2-6 aliases per exercise is ideal, only add more if genuinely common
- All aliases should be lowercase

Return ONLY valid JSON — an object mapping each exercise name to its aliases array.
Example:
{"Barbell Bench Press": ["bench press", "bench", "flat bench", "bb bench"], \
"Lying Triceps Press": ["skull crushers", "skulls", "lying tricep extension"]}
"""


async def _generate_batch(exercises: list[dict]) -> dict[str, list[str]]:
    names = [ex["name"] for ex in exercises]
    user_msg = "Generate aliases for these exercises:\n" + json.dumps(names)

    response = await litellm.acompletion(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


async def run(*, dry_run: bool = False, batch_size: int = 25) -> None:
    store = PostgresStore()

    async with store.get_session() as session:
        rows = (
            await session.execute(
                select(Exercise.id, Exercise.name, Exercise.aliases)
                .order_by(Exercise.name)
            )
        ).all()

    exercises = [{"id": r.id, "name": r.name, "aliases": r.aliases or []} for r in rows]
    logger.info("Loaded %d exercises from DB", len(exercises))

    # Only generate for exercises that don't already have aliases
    to_process = [ex for ex in exercises if not ex["aliases"]]
    logger.info("%d exercises need aliases (%d already have them)",
                len(to_process), len(exercises) - len(to_process))

    if not to_process:
        logger.info("Nothing to do.")
        await store.close()
        return

    all_aliases: dict[str, list[str]] = {}
    batches = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]

    for i, batch in enumerate(batches):
        logger.info("Processing batch %d/%d (%d exercises)...", i + 1, len(batches), len(batch))
        try:
            result = await _generate_batch(batch)
            all_aliases.update(result)
        except Exception:
            logger.exception("Batch %d failed, skipping", i + 1)

    logger.info("Generated aliases for %d exercises", len(all_aliases))

    if dry_run:
        for name, aliases in sorted(all_aliases.items()):
            print(f"  {name}: {aliases}")
        await store.close()
        return

    # Build lookup: name -> exercise id
    name_to_id = {ex["name"]: ex["id"] for ex in exercises}

    updated = 0
    async with store.get_session() as session:
        for name, aliases in all_aliases.items():
            exercise_id = name_to_id.get(name)
            if not exercise_id or not aliases:
                continue

            clean_aliases = [a.strip().lower() for a in aliases if a.strip()]

            tsv_parts = [name]
            tsv_parts.extend(clean_aliases)

            row = (
                await session.execute(
                    select(Exercise).where(Exercise.id == exercise_id)
                )
            ).scalar_one_or_none()
            if not row:
                continue

            # Rebuild full tsvector with aliases included
            tsv_parts.extend(row.primary_muscles or [])
            tsv_parts.extend(row.secondary_muscles or [])
            if row.equipment:
                tsv_parts.append(row.equipment)
            if row.category:
                tsv_parts.append(row.category)

            await session.execute(
                update(Exercise)
                .where(Exercise.id == exercise_id)
                .values(
                    aliases=clean_aliases,
                    search_tsv=func.to_tsvector("english", " ".join(tsv_parts)),
                )
            )
            updated += 1

        await session.commit()

    await store.close()
    logger.info("Updated %d exercises with aliases.", updated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate exercise aliases via LLM")
    parser.add_argument("--dry-run", action="store_true", help="Preview aliases without writing to DB")
    parser.add_argument("--batch-size", type=int, default=25, help="Exercises per LLM call")
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
