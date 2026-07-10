"""Convert string timestamps to BSON dates so Mongo TTL retention works.

ai_conversation_turns.timestamp and ai_thread_summaries.updated_at were
written as ISO strings (model_dump json) — Mongo TTL indexes only expire
Date fields, so retention silently never ran. New writes are already
dates; this converts the backlog. Idempotent; safe to re-run.

Run on the server:
    python -m scripts.migrate_memory_timestamps [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from lib.core.container import container
from lib.core.mongo_store import MongoStore


async def _convert(collection, field: str, dry_run: bool) -> int:
    converted = 0
    cursor = collection.find({field: {"$type": "string"}}, {field: 1})
    async for doc in cursor:
        try:
            dt = datetime.fromisoformat(str(doc[field]).replace("Z", "+00:00"))
        except ValueError:
            print(f"unparseable {field} on {doc['_id']}: {doc[field]!r}")
            continue
        if not dry_run:
            await collection.update_one({"_id": doc["_id"]}, {"$set": {field: dt}})
        converted += 1
        if converted % 500 == 0:
            print(f"{collection.name}.{field}: {converted}", flush=True)
    return converted


async def main(dry_run: bool) -> None:
    mongo = container.resolve(MongoStore)
    turns = await _convert(
        mongo.get_collection("ai_conversation_turns"), "timestamp", dry_run
    )
    summaries = await _convert(
        mongo.get_collection("ai_thread_summaries"), "updated_at", dry_run
    )
    print(f"DONE turns={turns} summaries={summaries} dry_run={dry_run}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
