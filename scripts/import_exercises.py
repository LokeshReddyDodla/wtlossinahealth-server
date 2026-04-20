"""One-time importer for the free-exercise-db catalog into Postgres.

Usage:
    # 1. Clone the dataset once (anywhere):
    #    git clone --depth 1 https://github.com/yuhonas/free-exercise-db.git /tmp/free-exercise-db
    #
    # 2. Host the `exercises/` folder somewhere (Cloudflare Pages, S3, nginx, ...)
    #    so images are served at <EXERCISE_IMAGE_BASE_URL>/exercises/<name>/0.jpg
    #
    # 3. Run:
    #    EXERCISE_IMAGE_BASE_URL=https://exercises.aihealth.in \
    #      python scripts/import_exercises.py /tmp/free-exercise-db/dist/exercises.json

Re-running is safe: upserts by id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from decouple import config  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.models.exercise import Exercise  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import_exercises")


def _rewrite_image_urls(rel_paths: list[str], base: str) -> list[str]:
    base = base.rstrip("/")
    return [f"{base}/exercises/{p.lstrip('/')}" for p in rel_paths]


async def import_exercises(json_path: Path, base_url: str) -> None:
    raw = json.loads(json_path.read_text())
    logger.info("Loaded %d exercises from %s", len(raw), json_path)

    store = PostgresStore()
    inserted = 0
    updated = 0

    async with store.get_session() as session:
        for ex in raw:
            values = {
                "id": ex["id"],
                "name": ex["name"],
                "force": ex.get("force"),
                "level": ex["level"],
                "mechanic": ex.get("mechanic"),
                "equipment": ex.get("equipment"),
                "category": ex["category"],
                "primary_muscles": ex.get("primaryMuscles", []) or [],
                "secondary_muscles": ex.get("secondaryMuscles", []) or [],
                "instructions": ex.get("instructions", []) or [],
                "image_urls": _rewrite_image_urls(ex.get("images", []) or [], base_url),
            }

            stmt = insert(Exercise).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in values.items() if k != "id"},
            )
            result = await session.execute(stmt)
            # rowcount is 1 for both insert and update with ON CONFLICT DO UPDATE
            if result.rowcount:
                inserted += 1

        await session.commit()

    await store.close()
    logger.info("Done. Upserted %d rows.", inserted)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/import_exercises.py <path/to/exercises.json>", file=sys.stderr)
        sys.exit(2)

    json_path = Path(sys.argv[1]).expanduser().resolve()
    if not json_path.exists():
        print(f"File not found: {json_path}", file=sys.stderr)
        sys.exit(2)

    base_url = config("EXERCISE_IMAGE_BASE_URL", default="").strip()
    if not base_url:
        print(
            "EXERCISE_IMAGE_BASE_URL must be set, e.g. https://exercises.aihealth.in",
            file=sys.stderr,
        )
        sys.exit(2)

    asyncio.run(import_exercises(json_path, base_url))


if __name__ == "__main__":
    main()
