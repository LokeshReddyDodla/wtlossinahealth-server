from lib.services.document_classification import (
    ENGINE_VERSION,
    classify_document,
)
from scripts.classify_patient_documents import Report, build_selection_filter

from . import fixtures as fx


def test_selection_filter_default_targets_unclassified_or_stale():
    query = build_selection_filter()
    assert query == {
        "$or": [
            {"classification": {"$exists": False}},
            {"classification.engine_version": {"$lt": ENGINE_VERSION}},
        ]
    }


def test_selection_filter_with_patient_id():
    query = build_selection_filter(patient_id="p123")
    assert query["patient_id"] == "p123"
    assert "$or" in query


def test_selection_filter_force_ignores_existing_classification():
    assert build_selection_filter(force=True) == {}
    assert build_selection_filter(patient_id="p123", force=True) == {
        "patient_id": "p123"
    }


def test_report_aggregation():
    report = Report()
    cases = [
        ("cbc.pdf", fx.CBC_TEXT),
        ("lipid.pdf", fx.LIPID_TEXT),
        ("chest.jpg", fx.XRAY_TEXT),
        ("noise.jpg", fx.GARBAGE_OCR_TEXT),
    ]
    for name, text in cases:
        result = classify_document(text, file_name=name)
        report.add({"file": {"name": name}}, result)

    assert report.doc_types["lab_report"] == 2
    assert report.doc_types["radiology"] == 1
    assert report.doc_types["unclassified"] == 1
    assert report.panels["cbc"] == 1
    assert report.panels["lipid"] == 1
    assert len(report.unclassified_names) == 1
    assert report.unclassified_names[0].startswith("noise.jpg")
    assert set(report.samples) == {"lab_report", "radiology", "unclassified"}
