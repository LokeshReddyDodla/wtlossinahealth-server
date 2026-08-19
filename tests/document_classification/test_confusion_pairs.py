"""The classifier's hard cases: panels whose vocabularies overlap.
Each test pins both directions — the right panel fires, the
confusable one does not."""

from lib.services.document_classification import classify_document

from . import fixtures as fx


def test_cmp_is_multilabel_metabolic_plus_lft():
    result = classify_document(fx.CMP_TEXT)
    assert set(result.panels) == {"metabolic_bmp_cmp", "lft"}


def test_bmp_does_not_fire_lft():
    result = classify_document(fx.BMP_TEXT)
    assert set(result.panels) == {"metabolic_bmp_cmp"}


def test_bun_creatinine_in_metabolic_panel_do_not_fire_kft():
    for text in (fx.CMP_TEXT, fx.BMP_TEXT):
        assert "kft" not in classify_document(text).panels


def test_shared_weak_analytes_alone_fire_no_panel():
    text = """
    BLOOD TEST REPORT
    Specimen: Serum      Method: GOD-POD
    Fasting Blood Sugar (FBS)  92   mg/dL   70 - 99
    Serum Creatinine           0.9  mg/dL   0.6 - 1.2
    """
    result = classify_document(text)
    assert result.doc_type == "lab_report"
    assert "kft" not in result.panels
    assert "metabolic_bmp_cmp" not in result.panels


def test_glucose_alone_never_fires_diabetes_panel():
    text = """
    BLOOD TEST REPORT
    Specimen: Plasma     Method: GOD-POD
    Random Blood Glucose       104  mg/dL   70 - 140
    """
    result = classify_document(text)
    assert "hba1c_glucose" not in result.panels


def test_urinalysis_vs_urine_culture():
    routine = classify_document(fx.URINALYSIS_TEXT)
    culture = classify_document(fx.URINE_CULTURE_TEXT)
    assert "urinalysis" in routine.panels
    assert "micro_culture_sensitivity" not in routine.panels
    assert "micro_culture_sensitivity" in culture.panels
    assert "urinalysis" not in culture.panels


def test_combined_urine_report_fires_both():
    result = classify_document(fx.COMBINED_URINE_TEXT)
    assert "urinalysis" in result.panels
    assert "micro_culture_sensitivity" in result.panels


def test_serology_vs_pcr():
    serology = classify_document(fx.SEROLOGY_TEXT)
    pcr = classify_document(fx.PCR_TEXT)
    assert "immunology_serology" in serology.panels
    assert "molecular_pcr" not in serology.panels
    assert "molecular_pcr" in pcr.panels
    assert "immunology_serology" not in pcr.panels


def test_histopathology_vs_cytopathology():
    histo = classify_document(fx.HISTOPATH_TEXT)
    cyto = classify_document(fx.CYTOPATH_TEXT)
    assert "surgical_pathology" in histo.panels
    assert "cytopathology" not in histo.panels
    assert "cytopathology" in cyto.panels
    assert "surgical_pathology" not in cyto.panels


def test_cbc_platelets_do_not_fire_coagulation():
    result = classify_document(fx.CBC_TEXT)
    assert set(result.panels) == {"cbc"}


def test_hba1c_glycated_haemoglobin_does_not_fire_cbc():
    result = classify_document(fx.HBA1C_TEXT)
    assert set(result.panels) == {"hba1c_glucose"}


def test_single_panel_fixtures_do_not_overfire():
    expectations = {
        fx.LFT_TEXT: {"lft"},
        fx.KFT_TEXT: {"kft"},
        fx.LIPID_TEXT: {"lipid"},
        fx.THYROID_TEXT: {"thyroid"},
        fx.COAG_TEXT: {"coagulation"},
        fx.CARDIAC_TEXT: {"cardiac"},
        fx.SEROLOGY_TEXT: {"immunology_serology"},
        fx.PCR_TEXT: {"molecular_pcr"},
        fx.HISTOPATH_TEXT: {"surgical_pathology"},
        fx.CYTOPATH_TEXT: {"cytopathology"},
    }
    for text, expected in expectations.items():
        assert set(classify_document(text).panels) == expected
