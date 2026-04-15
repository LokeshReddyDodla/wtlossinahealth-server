import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from bson import ObjectId

from lib.services.patient_data_export_service import PatientDataExportService


def _service() -> PatientDataExportService:
    # Bypass __init__ to unit test pure helpers.
    svc = object.__new__(PatientDataExportService)
    svc.MAX_CHUNK_BYTES = 80
    return svc


def test_json_safe_serialization_handles_common_types():
    svc = _service()

    payload = {
        "uuid": uuid4(),
        "object_id": ObjectId(),
        "decimal": Decimal("12.34"),
        "timestamp": datetime(2026, 3, 9, 12, 0, 0),
        "nested": {"values": [Decimal("1.5"), b"abc"]},
    }

    out = svc._serialize_mapping(payload)

    assert isinstance(out["uuid"], str)
    assert isinstance(out["object_id"], str)
    assert out["decimal"] == 12.34
    assert out["timestamp"] == "2026-03-09T12:00:00"
    assert out["nested"]["values"][0] == 1.5
    assert out["nested"]["values"][1] == "616263"


def test_write_dataset_chunks_splits_and_writes_valid_ndjson(tmp_path: Path):
    svc = _service()

    rows = [{"idx": i, "text": "x" * 20} for i in range(10)]
    chunks = svc._write_dataset_chunks(
        dataset="sample.table",
        rows=rows,
        dataset_dir=tmp_path,
    )

    assert len(chunks) > 1

    # `chunk["path"]` is relative to dataset_dir.parent (the exports root),
    # not dataset_dir itself.
    read_rows = 0
    for chunk in chunks:
        chunk_path = tmp_path.parent / chunk["path"]
        assert chunk_path.exists()
        with open(chunk_path, "r", encoding="utf-8") as f:
            for line in f:
                json.loads(line)
                read_rows += 1

    assert read_rows == len(rows)
