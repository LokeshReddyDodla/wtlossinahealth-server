import pytest

from lib.services.document_classification import (
    ENGINE_VERSION,
    classify_document,
)

from . import fixtures as fx

LAB_FIXTURES = [
    fx.CBC_TEXT,
    fx.CMP_TEXT,
    fx.BMP_TEXT,
    fx.LFT_TEXT,
    fx.KFT_TEXT,
    fx.LIPID_TEXT,
    fx.HBA1C_TEXT,
    fx.THYROID_TEXT,
    fx.COAG_TEXT,
    fx.CARDIAC_TEXT,
    fx.SEROLOGY_TEXT,
    fx.URINALYSIS_TEXT,
    fx.URINE_CULTURE_TEXT,
    fx.HISTOPATH_TEXT,
    fx.CYTOPATH_TEXT,
    fx.PCR_TEXT,
    fx.VITAMIN_IRON_TEXT,
    fx.FULL_BODY_PACKAGE_TEXT,
]


@pytest.mark.parametrize("text", LAB_FIXTURES)
def test_lab_fixtures_are_lab_reports(text):
    result = classify_document(text)
    assert result.doc_type == "lab_report"
    assert result.panels


@pytest.mark.parametrize("text", [fx.XRAY_TEXT, fx.CT_TEXT])
def test_radiology_fixtures(text):
    result = classify_document(text)
    assert result.doc_type == "radiology"
    assert result.panels == []
    assert result.family is None


def test_prescription_is_other():
    result = classify_document(fx.PRESCRIPTION_TEXT)
    assert result.doc_type == "other"
    assert result.panels == []


def test_inbody_scan_is_other():
    result = classify_document(fx.INBODY_TEXT)
    assert result.doc_type == "other"
    assert "inbody" in result.evidence.doc_type.other_hits


def test_garbled_inbody_ocr_rescued_by_filename():
    noise = "ae 43.4 gn 54 sou bis amy cay qqq www eee rrr"
    result = classify_document(noise, file_name="9845_InBody.jpg")
    assert result.doc_type == "other"
    assert "filename_inbody" in result.evidence.doc_type.file_signals


def test_single_assay_hormone_report_is_lab():
    result = classify_document(fx.HORMONE_TEXT)
    assert result.doc_type == "lab_report"
    assert result.panels == ["other_lab"]


def test_garbage_ocr_is_unclassified():
    result = classify_document(fx.GARBAGE_OCR_TEXT)
    assert result.doc_type == "unclassified"
    assert result.evidence.doc_type.reason == "insufficient_signals"
    assert result.confidence == 0.0


@pytest.mark.parametrize("text", [fx.EMPTY_TEXT, None, "   ", "short"])
def test_empty_text_is_unclassified(text):
    result = classify_document(text)
    assert result.doc_type == "unclassified"
    assert result.evidence.doc_type.reason == "empty_text"


def test_filename_never_overrides_text():
    result = classify_document(fx.CBC_TEXT, file_name="xray_chest.jpg")
    assert result.doc_type == "lab_report"


def test_image_with_near_empty_ocr_leans_radiology():
    noise = "scanned image artefact noise qqq www eee rrr"
    result = classify_document(noise, mime_type="image/jpeg")
    assert result.doc_type == "radiology"
    assert "image_short_text" in result.evidence.doc_type.file_signals


def test_confidence_bounds_and_engine_version():
    for text in [*LAB_FIXTURES, fx.XRAY_TEXT, fx.PRESCRIPTION_TEXT]:
        result = classify_document(text)
        assert 0.0 <= result.confidence <= 0.99
        assert result.confidence > 0.5
        assert result.engine_version == ENGINE_VERSION
        assert result.classified_at.tzinfo is not None


def test_evidence_is_populated_for_lab_reports():
    result = classify_document(fx.CBC_TEXT)
    assert result.evidence.doc_type.result_lines >= 5
    assert result.evidence.doc_type.analyte_hits >= 4
