"""The coverage sweep's diff must be exact: a false 'missing' re-embeds paid
work every week; a false 'present' leaves a permanent RAG hole."""

from datetime import datetime

from lib.services.vector.utils.point_id_generator import PointIdGenerator
from lib.workers.tasks.vector_coverage.sweep import (
    diff_missing,
    group_vital_rows,
    normalize_point_id,
)


def test_normalize_matches_qdrant_uuid_form():
    # We store raw 32-hex md5 ids; Qdrant returns them UUID-hyphenated.
    raw = PointIdGenerator.generate_simple("meal-123")
    hyphenated = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    assert normalize_point_id(hyphenated) == normalize_point_id(raw) == raw


def test_diff_missing_is_exact():
    ids = [PointIdGenerator.generate_simple(f"e{i}") for i in range(4)]
    candidates = [(pid, f"thunk{i}") for i, pid in enumerate(ids)]
    # Qdrant holds e0 (hyphenated) and e2 (raw) — e1 and e3 are the holes.
    existing = {
        normalize_point_id(f"{ids[0][:8]}-{ids[0][8:12]}-{ids[0][12:16]}-{ids[0][16:20]}-{ids[0][20:]}"),
        normalize_point_id(ids[2]),
    }
    assert diff_missing(candidates, existing) == ["thunk1", "thunk3"]
    # full coverage -> zero work
    assert diff_missing(candidates, {normalize_point_id(p) for p in ids}) == []


def test_group_vital_rows_rebuilds_task_payload():
    t = datetime(2026, 8, 20, 9, 0)
    rows = [
        {"vital_id": "v1", "type": "systolic_bp", "value": 130.0, "time": t, "source_name": "app", "source_platform": "ios"},
        {"vital_id": "v1", "type": "diastolic_bp", "value": 85.0, "time": t, "source_name": "app", "source_platform": "ios"},
        {"vital_id": "v2", "type": "weight", "value": 80.0, "time": t, "source_name": "app", "source_platform": "ios"},
    ]
    grouped = group_vital_rows(rows)
    assert set(grouped) == {"v1", "v2"}
    assert grouped["v1"]["systolic_bp"] == 130.0
    assert grouped["v1"]["diastolic_bp"] == 85.0
    assert grouped["v1"]["test_time"] == t
    assert grouped["v2"]["weight"] == 80.0
