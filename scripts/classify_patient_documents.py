"""Classify patient_documents into lab reports / radiology / other,
with multi-label lab panels, using the rule-based engine (no LLM).

Reads text_raw already stored in Mongo — no S3, no re-extraction.
Selects docs that have never been classified or were classified by an
older engine version, so the first run is the full backfill and later
runs only pick up new uploads. Dry-run (the default) writes nothing
and prints a distribution report.

Usage:
    python -m scripts.classify_patient_documents            # dry-run
    python -m scripts.classify_patient_documents --limit 200 --verbose
    python -m scripts.classify_patient_documents --write    # backfill
    python -m scripts.classify_patient_documents --write --force
    docker compose exec api python scripts/classify_patient_documents.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.mongo_store import MongoStore  # noqa: E402
from lib.services.document_classification import (  # noqa: E402
    ENGINE_VERSION,
    classify_document,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("classify_patient_documents")

COLLECTION = "patient_documents"
PROJECTION = {
    "text_raw": 1,
    "file.name": 1,
    "file.type": 1,
    "category": 1,
    "patient_id": 1,
}
UNCLASSIFIED_SAMPLE_MAX = 50
EVIDENCE_SAMPLES_PER_TYPE = 3


def build_selection_filter(
    patient_id: str | None = None, force: bool = False
) -> dict:
    """Docs never classified, or classified by an older engine."""
    query: dict = {}
    if patient_id:
        query["patient_id"] = patient_id
    if not force:
        query["$or"] = [
            {"classification": {"$exists": False}},
            {"classification.engine_version": {"$lt": ENGINE_VERSION}},
        ]
    return query


async def ensure_indexes(collection) -> None:
    await collection.create_index(
        [("patient_id", 1), ("classification.doc_type", 1)],
        name="patientDocs_patient_docType_idx",
    )
    await collection.create_index(
        [("classification.panels", 1)],
        name="patientDocs_panels_idx",
    )


class Report:
    def __init__(self) -> None:
        self.doc_types: Counter = Counter()
        self.panels: Counter = Counter()
        self.confidence_buckets: Counter = Counter()
        self.unclassified_names: list[str] = []
        self.samples: dict[str, list[str]] = {}

    def add(self, doc: dict, result) -> None:
        self.doc_types[result.doc_type] += 1
        for panel in result.panels:
            self.panels[panel] += 1
        bucket = f"{int(result.confidence * 10) / 10:.1f}"
        self.confidence_buckets[bucket] += 1
        file_name = (doc.get("file") or {}).get("name") or "<unnamed>"
        if (
            result.doc_type == "unclassified"
            and len(self.unclassified_names) < UNCLASSIFIED_SAMPLE_MAX
        ):
            reason = result.evidence.doc_type.reason or "?"
            self.unclassified_names.append(f"{file_name} ({reason})")
        samples = self.samples.setdefault(result.doc_type, [])
        if len(samples) < EVIDENCE_SAMPLES_PER_TYPE:
            samples.append(f"{file_name}: {_compact_evidence(result)}")

    def print(self) -> None:
        print("\n=== doc_type distribution ===")
        for doc_type, count in self.doc_types.most_common():
            print(f"  {doc_type:15s} {count}")
        print("\n=== panel distribution (lab reports, multi-label) ===")
        for panel, count in self.panels.most_common():
            print(f"  {panel:28s} {count}")
        print("\n=== confidence histogram ===")
        for bucket in sorted(self.confidence_buckets):
            print(f"  {bucket}  {self.confidence_buckets[bucket]}")
        if self.unclassified_names:
            print(
                f"\n=== unclassified (first "
                f"{len(self.unclassified_names)}) ==="
            )
            for name in self.unclassified_names:
                print(f"  {name}")
        print("\n=== sample evidence per doc_type ===")
        for doc_type, samples in self.samples.items():
            print(f"  [{doc_type}]")
            for sample in samples:
                print(f"    {sample}")


def _compact_evidence(result) -> str:
    ev = result.evidence.doc_type
    parts = [
        f"lines={ev.result_lines}",
        f"analytes={ev.analyte_hits}",
    ]
    if result.panels:
        parts.append(f"panels={','.join(result.panels)}")
    if ev.radiology_hits:
        parts.append(f"radiology={','.join(ev.radiology_hits)}")
    if ev.other_hits:
        parts.append(f"other={','.join(ev.other_hits)}")
    if ev.file_signals:
        parts.append(f"file={','.join(ev.file_signals)}")
    if ev.reason:
        parts.append(f"reason={ev.reason}")
    return f"conf={result.confidence} " + " ".join(parts)


async def main(args: argparse.Namespace) -> None:
    store = MongoStore()
    collection = store.get_collection(COLLECTION)

    if args.write:
        await ensure_indexes(collection)

    base_filter = build_selection_filter(args.patient_id, args.force)
    report = Report()
    scanned = written = errors = 0
    last_id = None

    while True:
        query = dict(base_filter)
        if last_id is not None:
            query["_id"] = {"$gt": last_id}
        batch = (
            await collection.find(query, PROJECTION)
            .sort("_id", 1)
            .limit(args.batch_size)
            .to_list(length=args.batch_size)
        )
        if not batch:
            break

        for doc in batch:
            last_id = doc["_id"]
            scanned += 1
            file_info = doc.get("file") or {}
            try:
                result = classify_document(
                    doc.get("text_raw"),
                    file_name=file_info.get("name"),
                    mime_type=file_info.get("type"),
                    category=doc.get("category"),
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.error("classify failed _id=%s: %s", doc["_id"], exc)
                continue

            report.add(doc, result)
            if args.verbose:
                print(
                    f"{doc['_id']} {result.doc_type} "
                    f"{_compact_evidence(result)}",
                    flush=True,
                )
            if args.write:
                await collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"classification": result.to_mongo()}},
                )
                written += 1
            if args.limit and scanned >= args.limit:
                break

        print(f"scanned={scanned} written={written}", flush=True)
        if args.limit and scanned >= args.limit:
            break

    report.print()
    print(
        f"\nDONE scanned={scanned} written={written} errors={errors} "
        f"dry_run={not args.write} engine_version={ENGINE_VERSION}",
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rule-based classification sweep over patient_documents"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="apply $set updates (default: dry-run, no writes)",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after N docs (0 = all)"
    )
    parser.add_argument(
        "--patient-id", default=None, help="restrict to one patient"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="reclassify even docs already at the current engine version",
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--verbose", action="store_true", help="print per-doc evidence"
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
