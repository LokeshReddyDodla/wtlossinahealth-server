"""One-off: delete the daily custom-report slivers the retired CGM reconciler
left behind. Dry-run by default.

Deletes a custom CGM report when either holds:
- its window spans <= 1 day (the CSV lifecycle path's 48h minimum makes such
  a doc impossible to create legitimately), or
- its window is fully contained inside another custom report of the same
  patient.

Embedded fitness/sleep sub-report docs referenced only by a deleted custom
are removed with it.

Usage: poetry run python scripts/cleanup_cgm_custom_slivers.py [--apply]
"""

import asyncio
import sys
from datetime import datetime

from lib.core.mongo_store import MongoStore


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v))


async def main(apply: bool) -> None:
    store = MongoStore()
    cgm = store.get_collection("cgm_reports")

    docs = await cgm.find(
        {"metadata.report_type": "custom"},
        {"patient_id": 1, "metadata.date_range": 1, "fitness_report_id": 1, "sleep_report_id": 1},
    ).to_list(length=None)

    by_patient: dict[str, list[dict]] = {}
    for d in docs:
        rng = d["metadata"]["date_range"]
        d["_start"], d["_end"] = _dt(rng["start"]), _dt(rng["end"])
        by_patient.setdefault(d["patient_id"], []).append(d)

    to_delete: list[dict] = []
    for patient_docs in by_patient.values():
        for d in patient_docs:
            span_days = (d["_end"] - d["_start"]).total_seconds() / 86400
            contained = any(
                o["_id"] != d["_id"]
                and o["_start"] <= d["_start"]
                and o["_end"] >= d["_end"]
                and (o["_end"] - o["_start"]) > (d["_end"] - d["_start"])
                for o in patient_docs
            )
            if span_days <= 1.01 or contained:
                to_delete.append(d)

    print(f"custom reports: {len(docs)} total, {len(to_delete)} slivers to delete")
    for d in sorted(to_delete, key=lambda x: (x["patient_id"], x["_start"])):
        print(f"  {d['patient_id']}  {d['_start'].date()} -> {d['_end'].date()}")

    if not apply:
        print("dry run — pass --apply to delete")
        return

    ids = [d["_id"] for d in to_delete]
    result = await cgm.delete_many({"_id": {"$in": ids}})
    print(f"deleted {result.deleted_count} custom reports")

    for coll_name, key in (("fitness_reports", "fitness_report_id"), ("sleep_reports", "sleep_report_id")):
        sub_ids = {d.get(key) for d in to_delete if d.get(key)}
        keep = {
            doc.get(key)
            async for doc in cgm.find({key: {"$in": list(sub_ids)}}, {key: 1})
        }
        orphaned = list(sub_ids - keep)
        if orphaned:
            sub = store.get_collection(coll_name)
            r = await sub.delete_many({"_id": {"$in": orphaned}})
            print(f"deleted {r.deleted_count} orphaned {coll_name} sub-reports")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
