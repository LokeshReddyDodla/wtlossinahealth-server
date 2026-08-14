import pytest

from lib.services.document_classification import classify_document

from . import fixtures as fx

# fixture text, expected panel, anchors that must appear in evidence
PANEL_CASES = [
    (fx.CBC_TEXT, "cbc", {"hemoglobin", "mcv", "mchc", "rdw"}),
    (
        fx.BMP_TEXT,
        "metabolic_bmp_cmp",
        {"sodium", "potassium", "chloride", "bicarbonate"},
    ),
    (fx.LFT_TEXT, "lft", {"bilirubin", "alt", "ast", "alp", "ggt"}),
    (fx.KFT_TEXT, "kft", {"urea", "uric_acid", "egfr"}),
    (
        fx.LIPID_TEXT,
        "lipid",
        {"total_cholesterol", "hdl", "ldl", "triglycerides"},
    ),
    (fx.HBA1C_TEXT, "hba1c_glucose", {"hba1c", "eag"}),
    (fx.THYROID_TEXT, "thyroid", {"tsh", "t3", "t4"}),
    (fx.COAG_TEXT, "coagulation", {"prothrombin", "inr", "aptt"}),
    (fx.CARDIAC_TEXT, "cardiac", {"troponin", "ck_mb", "bnp"}),
    (
        fx.SEROLOGY_TEXT,
        "immunology_serology",
        {"immunoglobulin", "reactive", "serology_target"},
    ),
    (
        fx.URINALYSIS_TEXT,
        "urinalysis",
        {"pus_cells", "epithelial_cells", "casts", "crystals"},
    ),
    (
        fx.URINE_CULTURE_TEXT,
        "micro_culture_sensitivity",
        {"culture", "sensitivity", "organism", "antibiotic"},
    ),
    (
        fx.HISTOPATH_TEXT,
        "surgical_pathology",
        {"gross", "histopathology", "microscopy"},
    ),
    (fx.CYTOPATH_TEXT, "cytopathology", {"pap", "bethesda"}),
    (fx.PCR_TEXT, "molecular_pcr", {"pcr", "ct_value", "detected"}),
]


@pytest.mark.parametrize(
    "text,panel,expected_anchors",
    PANEL_CASES,
    ids=[case[1] for case in PANEL_CASES],
)
def test_each_subtype_fires_with_expected_anchors(
    text, panel, expected_anchors
):
    result = classify_document(text)
    assert panel in result.panels
    assert expected_anchors <= set(result.evidence.panels[panel].anchors)


def test_uncatalogued_lab_report_falls_back_to_other_lab():
    result = classify_document(fx.VITAMIN_IRON_TEXT)
    assert result.doc_type == "lab_report"
    assert result.panels == ["other_lab"]
    assert result.family is None


def test_section_header_relaxes_anchor_threshold():
    text = """
    LIPID PROFILE
    Specimen: Serum      Method: CHOD-PAP
    Total Cholesterol    182   mg/dL    125 - 200
    """
    result = classify_document(text)
    assert "lipid" in result.panels
    assert result.evidence.panels["lipid"].section_header is not None


def test_panels_are_in_canonical_order():
    result = classify_document(fx.FULL_BODY_PACKAGE_TEXT)
    assert result.panels == ["cbc", "lft", "lipid", "thyroid"]


def test_family_quantitative_vs_narrative():
    assert classify_document(fx.LFT_TEXT).family == "quantitative"
    assert classify_document(fx.URINALYSIS_TEXT).family == "semi_quantitative"
    assert classify_document(fx.HISTOPATH_TEXT).family == "narrative"
    assert classify_document(fx.COMBINED_URINE_TEXT).family == "mixed"
