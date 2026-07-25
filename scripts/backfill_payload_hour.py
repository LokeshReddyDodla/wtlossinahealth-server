"""Backfill the `hour` payload field on existing Qdrant points.

Points written before payload_builder gained the universal `hour` key
(meals, check-ins, plans, ...) match NOTHING under hour-range filters.
Derives hour from the stored `start_time` epoch-ms using the same
convention it was written with (wall-clock semantics preserved).

Run on the server (inside the docker network):
    python -m scripts.backfill_payload_hour [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from qdrant_client import models

from lib.core.container import container
from lib.core.qdrant_store import QdrantStore

COLLECTION = "patient_data"
BATCH = 256


async def main(dry_run: bool) -> None:
    store = container.resolve(QdrantStore)
    async with store.get_client() as client:
        offset = None
        scanned = patched = 0
        while True:
            points, offset = await client.scroll(
                collection_name=COLLECTION,
                scroll_filter=models.Filter(must_not=[
                    models.FieldCondition(key="hour", range=models.Range(gte=0)),
                ]),
                limit=BATCH,
                offset=offset,
                with_payload=["start_time"],
                with_vectors=False,
            )
            if not points:
                break
            for p in points:
                scanned += 1
                start_ms = (p.payload or {}).get("start_time")
                if start_ms is None:
                    continue
                # Same naive convention the writer used: epoch-ms → wall hour.
                hour = datetime.fromtimestamp(start_ms / 1000).hour
                if not dry_run:
                    await client.set_payload(
                        collection_name=COLLECTION,
                        payload={"hour": hour},
                        points=[p.id],
                    )
                patched += 1
            print(f"scanned={scanned} patched={patched}", flush=True)
            if offset is None:
                break
        print(f"DONE scanned={scanned} patched={patched} dry_run={dry_run}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
