"""Pattern catalog for rule-based document classification.

Pure data: compiled regexes only, no logic. Panel detection is
evidence-weighted — anchors (weight 1.0+) are analytes unique to a
panel; weak entries (< 1.0) are shared across panels (creatinine,
glucose, platelets) and can never fire a panel on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


@dataclass(frozen=True)
class AnchorPattern:
    key: str
    pattern: re.Pattern
    weight: float = 1.0


@dataclass(frozen=True)
class PanelRule:
    panel: str
    family: str
    anchors: tuple[AnchorPattern, ...]
    weak: tuple[AnchorPattern, ...] = ()
    section_headers: tuple[re.Pattern, ...] = ()
    # Fire thresholds compare against the summed weights of matched
    # anchors + weak entries.
    min_score: float = 3.0
    min_score_with_header: float = 1.0


def _a(key: str, pattern: str, weight: float = 1.0) -> AnchorPattern:
    return AnchorPattern(key=key, pattern=_p(pattern), weight=weight)


# Shared analytes, defined once and referenced by the panels that
# share them. Weights < 1.0 so none of them can fire a panel alone.
CREATININE = _a("creatinine", r"\bcreatinine\b", 0.5)
GLUCOSE = _a("glucose", r"\bglucose\b|blood\s+sugar", 0.25)
PLATELETS = _a("platelets", r"\bplatelets?\b", 0.5)
CALCIUM = _a("calcium", r"\bcalcium\b", 0.25)
ALBUMIN = _a("albumin", r"\balbumin\b", 0.5)

PANEL_RULES: tuple[PanelRule, ...] = (
    PanelRule(
        panel="cbc",
        family="quantitative",
        anchors=(
            # Lookbehinds exclude "Glycated/Glycosylated Haemoglobin"
            # (HbA1c) and "Mean Corpuscular Haemoglobin" (MCH).
            _a(
                "hemoglobin",
                r"(?<!glycated\s)(?<!glycosylated\s)(?<!corpuscular\s)"
                r"\bha?emoglobin\b",
            ),
            _a("hematocrit", r"\bha?ematocrit\b|\bHCT\b|\bPCV\b"),
            _a("mcv", r"\bMCV\b|mean\s+corpuscular\s+volume"),
            _a("mch", r"\bMCH\b"),
            _a("mchc", r"\bMCHC\b"),
            _a("rdw", r"\bRDW(?:-CV|-SD)?\b"),
            _a(
                "rbc_count",
                r"\brbc\s+count\b|total\s+rbc|red\s+blood\s+cells?",
            ),
            _a(
                "wbc_count",
                r"total\s+leu[ck]ocyte\s+count|\bTLC\b|\bWBC\b"
                r"|white\s+blood\s+cells?",
            ),
            _a("neutrophils", r"\bneutrophils?\b", 0.5),
            _a("lymphocytes", r"\blymphocytes?\b", 0.5),
            _a("eosinophils", r"\beosinophils?\b", 0.5),
            _a("monocytes", r"\bmonocytes?\b", 0.5),
            _a("basophils", r"\bbasophils?\b", 0.5),
        ),
        weak=(PLATELETS,),
        section_headers=(
            _p(
                r"complete\s+blood\s+count|\bCBC\b|ha?emogram"
                r"|complete\s+ha?ematology"
            ),
        ),
        min_score=3.0,
    ),
    PanelRule(
        panel="metabolic_bmp_cmp",
        family="quantitative",
        # Electrolytes are the anchor cluster: they are what makes a
        # metabolic panel rather than a plain LFT/KFT.
        anchors=(
            _a("sodium", r"\bsodium\b|\bna\s*\+"),
            _a("potassium", r"\bpotassium\b|\bk\s*\+"),
            _a("chloride", r"\bchloride\b|\bcl\s*-"),
            _a(
                "bicarbonate",
                r"\bbicarbonate\b|\bHCO3\b|carbon\s+dioxide",
            ),
        ),
        weak=(GLUCOSE, CREATININE, CALCIUM),
        section_headers=(
            _p(
                r"basic\s+metabolic|comprehensive\s+metabolic"
                r"|\bBMP\b|\bCMP\b|\belectrolytes?\b"
            ),
        ),
        min_score=3.0,
    ),
    PanelRule(
        panel="lft",
        family="quantitative",
        anchors=(
            _a("bilirubin", r"\bbilirubin\b"),
            _a(
                "alt",
                r"\bALT\b|\bSGPT\b|alanine\s+(?:amino)?transferase"
                r"|alanine\s+transaminase",
            ),
            _a(
                "ast",
                r"\bAST\b|\bSGOT\b|aspartate\s+(?:amino)?transferase"
                r"|aspartate\s+transaminase",
            ),
            _a("alp", r"\bALP\b|alkaline\s+phosphatase"),
            _a("ggt", r"\bGGTP?\b|gamma[\s-]*glutamyl"),
            _a("total_protein", r"total\s+proteins?\b", 0.5),
            _a("globulin", r"\bglobulin\b|a\s*/\s*g\s+ratio", 0.5),
        ),
        weak=(ALBUMIN,),
        section_headers=(_p(r"liver\s+function|\bLFT\b|hepatic\s+panel"),),
        min_score=2.5,
    ),
    PanelRule(
        panel="kft",
        family="quantitative",
        anchors=(
            _a("urea", r"\burea\b|\bBUN\b"),
            _a("uric_acid", r"\buric\s+acid\b"),
            _a(
                "egfr",
                r"\beGFR\b|glomerular\s+filtration",
            ),
        ),
        weak=(CREATININE,),
        section_headers=(
            _p(
                r"kidney\s+function|renal\s+function|renal\s+profile"
                r"|\bKFT\b|\bRFT\b"
            ),
        ),
        min_score=2.0,
    ),
    PanelRule(
        panel="lipid",
        family="quantitative",
        anchors=(
            _a("total_cholesterol", r"total\s+cholesterol|\bcholesterol\b"),
            _a("ldl", r"\bLDL\b|low\s+density\s+lipoprotein"),
            _a("hdl", r"\bHDL\b|high\s+density\s+lipoprotein"),
            _a("vldl", r"\bVLDL\b"),
            _a("triglycerides", r"\btriglycerides?\b"),
        ),
        section_headers=(_p(r"lipid\s+profile|lipid\s+panel"),),
        min_score=2.5,
    ),
    PanelRule(
        panel="hba1c_glucose",
        family="quantitative",
        anchors=(
            # HbA1c alone defines the report; plain glucose never
            # fires this panel (it is a weak/shared analyte).
            _a(
                "hba1c",
                r"\bHbA1c\b|glyca?ted\s+ha?emoglobin"
                r"|glycosylated\s+ha?emoglobin",
                2.0,
            ),
            _a("eag", r"\beAG\b|estimated\s+average\s+glucose"),
            _a(
                "fasting_glucose",
                r"fasting\s+(?:blood\s+)?(?:sugar|glucose)|\bFBS\b",
            ),
            _a(
                "pp_glucose",
                r"post\s*-?\s*prandial|\bPPBS\b|\bPP2BS\b",
            ),
            _a(
                "glucose_tolerance",
                r"glucose\s+tolerance|\bOGTT\b|\bGTT\b",
                2.0,
            ),
        ),
        weak=(GLUCOSE,),
        section_headers=(
            _p(r"glyca?ted\s+ha?emoglobin|diabet\w*\s+(profile|panel)"),
        ),
        min_score=2.0,
    ),
    PanelRule(
        panel="thyroid",
        family="quantitative",
        anchors=(
            _a(
                "tsh",
                r"\bTSH\b|thyroid\s+stimulating\s+hormone",
                2.0,
            ),
            _a("t3", r"\bT3\b|tri-?iodothyronine"),
            _a("t4", r"\bT4\b|\bthyroxine\b"),
            _a("ft3", r"\bFT3\b|free\s+t3"),
            _a("ft4", r"\bFT4\b|free\s+t4"),
            _a("anti_tpo", r"anti[\s-]*TPO|thyroid\s+peroxidase"),
        ),
        section_headers=(_p(r"thyroid\s+(function|profile|panel)|\bTFT\b"),),
        min_score=2.0,
    ),
    PanelRule(
        panel="coagulation",
        family="quantitative",
        anchors=(
            _a("prothrombin", r"\bprothrombin\b"),
            _a("inr", r"\bINR\b"),
            _a(
                "aptt",
                r"\ba?PTT\b|partial\s+thromboplastin",
            ),
            _a("fibrinogen", r"\bfibrinogen\b"),
            _a("d_dimer", r"\bD-?dimer\b"),
        ),
        weak=(PLATELETS,),
        section_headers=(_p(r"coagulation\s+(profile|panel|studies)"),),
        min_score=2.0,
    ),
    PanelRule(
        panel="cardiac",
        family="quantitative",
        anchors=(
            _a("troponin", r"\btroponin\b|\bcTnI\b|\bcTnT\b", 2.0),
            _a("ck_mb", r"\bCK-?MB\b|creatine\s+kinase\s*-?\s*MB"),
            _a("bnp", r"\bBNP\b|NT-?proBNP", 1.5),
            _a("cpk", r"\bCPK\b|creatine\s+phosphokinase", 0.5),
        ),
        section_headers=(_p(r"cardiac\s+(markers?|panel|profile|enzymes?)"),),
        min_score=2.0,
    ),
    PanelRule(
        panel="immunology_serology",
        family="quantitative",
        anchors=(
            _a("immunoglobulin", r"\bIg[GMAE]\b"),
            _a("titre", r"\btit(?:re|er)s?\b|\b1\s*:\s*\d{2,}\b"),
            _a("ana", r"\bANA\b|anti-?nuclear\s+antibod"),
            _a("rheumatoid_factor", r"rheumatoid\s+factor"),
            # Lookbehind excludes "C-Reactive Protein" (CRP).
            _a("reactive", r"(?<!c-)\b(?:non\s*-?\s*)?reactive\b"),
            _a("widal", r"\bwidal\b"),
            _a(
                "serology_target",
                r"(?:dengue|typhoid|hiv|hbsag|hcv|vdrl|toxoplasma"
                r"|rubella|cmv)\b[^\n]{0,40}"
                r"(?:antigen|antibod|igg|igm|ns1)",
            ),
            _a("antibody", r"\bantibod(?:y|ies)\b", 0.5),
            _a("assay_method", r"\bELISA\b|\bCLIA\b|\bECLIA\b", 0.5),
        ),
        section_headers=(_p(r"serolog|immunolog|autoimmune"),),
        min_score=2.0,
    ),
    PanelRule(
        panel="urinalysis",
        family="semi_quantitative",
        anchors=(
            _a("pus_cells", r"pus\s+cells?"),
            _a("epithelial_cells", r"epithelial\s+cells?"),
            _a("casts", r"\bcasts?\b"),
            _a("crystals", r"\bcrystals?\b"),
            _a("specific_gravity", r"specific\s+gravity"),
            _a("hpf", r"/\s*hpf\b|\bhpf\b|\blpf\b"),
            _a("urine_appearance", r"\bappearance\b|\bturbid\b", 0.5),
        ),
        section_headers=(
            _p(
                r"urine\s+(routine|analysis|examination)|urinalysis"
                r"|complete\s+urine"
            ),
        ),
        min_score=2.5,
    ),
    PanelRule(
        panel="micro_culture_sensitivity",
        family="narrative",
        anchors=(
            _a("culture", r"\bcultures?\b"),
            _a("sensitivity", r"\bsensitiv(?:e|ity)\b"),
            _a("resistant", r"\bresistant\b"),
            _a("colony_count", r"colony\s+count|\bCFU\b"),
            _a("growth", r"\bno\s+growth\b|growth\s+of\b", 0.5),
            _a(
                "organism",
                r"\borganism\b|\bisolated?\b|e\.?\s*coli"
                r"|escherichia|klebsiella|staphylococcus"
                r"|streptococcus|pseudomonas|enterococcus"
                r"|acinetobacter|proteus|candida",
            ),
            _a(
                "antibiotic",
                r"amoxicillin|ampicillin|ciprofloxacin|levofloxacin"
                r"|gentamicin|amikacin|ceftriaxone|cefixime"
                r"|meropenem|imipenem|vancomycin|linezolid"
                r"|nitrofurantoin|piperacillin|cotrimoxazole",
            ),
        ),
        section_headers=(
            _p(
                r"culture\s+(?:and|&)\s+sensitivity|\bc\s*/\s*s\b"
                r"|bacteriolog|microbiolog"
            ),
        ),
        min_score=2.5,
    ),
    PanelRule(
        panel="surgical_pathology",
        family="narrative",
        anchors=(
            _a("gross", r"gross\s+(?:description|examination)", 1.5),
            _a("histopathology", r"histopatholog", 1.5),
            _a("biopsy", r"\bbiops(?:y|ies)\b"),
            _a("microscopy", r"\bmicroscop(?:y|ic)\b"),
            _a("ihc", r"immunohistochem|\bIHC\b"),
            _a(
                "malignancy_terms",
                r"carcinoma|malignan|neoplas|margins?\s+"
                r"(?:are\s+)?(?:free|involved|uninvolved)",
                0.5,
            ),
        ),
        section_headers=(_p(r"surgical\s+pathology|histopathology\s+report"),),
        min_score=2.5,
    ),
    PanelRule(
        panel="cytopathology",
        family="narrative",
        anchors=(
            _a("pap", r"pap\s+smear|papanicolaou", 1.5),
            _a("bethesda", r"\bbethesda\b", 1.5),
            _a(
                "fnac",
                r"\bFNAC?\b|fine\s+needle\s+aspiration",
                1.5,
            ),
            _a("cytology", r"\bcytolog(?:y|ic|ical)\b"),
            _a(
                "cyto_findings",
                r"\bNILM\b|\bLSIL\b|\bHSIL\b|\bASC-?US\b"
                r"|intraepithelial\s+lesion"
                r"|satisfactory\s+for\s+evaluation",
            ),
        ),
        section_headers=(_p(r"cytopatholog|cytology\s+report"),),
        min_score=2.0,
    ),
    PanelRule(
        panel="molecular_pcr",
        family="narrative",
        anchors=(
            _a(
                "pcr",
                r"\bRT-?PCR\b|\bPCR\b|polymerase\s+chain",
                1.5,
            ),
            _a("ct_value", r"\bct\s+value\b|cycle\s+threshold", 1.5),
            _a("detected", r"\b(?:not\s+)?detected\b"),
            _a("viral_load", r"viral\s+load|copies\s*/\s*ml", 1.5),
            _a(
                "genetic",
                r"karyotype|\bmutation\b|genomic|\bNGS\b"
                r"|next\s+generation\s+sequencing|\bgene\s+panel\b",
            ),
        ),
        section_headers=(
            _p(r"molecular\s+(?:diagnostics?|pathology)|genetic\s+test"),
        ),
        min_score=2.0,
    ),
)

# ---------------------------------------------------------------------------
# Stage-1 (doc type) vocabularies. Tuples of (name, pattern, weight);
# names are recorded as evidence.


@dataclass(frozen=True)
class VocabPattern:
    key: str
    pattern: re.Pattern
    weight: float = 1.0


def _v(key: str, pattern: str, weight: float = 1.0) -> VocabPattern:
    return VocabPattern(key=key, pattern=_p(pattern), weight=weight)


LAB_HEADER_PATTERNS: tuple[VocabPattern, ...] = (
    _v("bio_ref", r"bio\.?\s*ref", 1.0),
    _v("reference_range", r"reference\s+(?:range|interval|value)", 1.0),
    _v("specimen", r"\bspecimen\b", 0.75),
    _v("method", r"\bmethod\s*:", 0.75),
    _v("sample", r"sample\s+(?:type|collected|received)", 0.75),
    _v("serum_plasma", r"\bserum\b|\bplasma\b|\bEDTA\b", 0.5),
    _v("lab_name", r"laboratory|pathology\s+lab|diagnostics", 0.5),
    _v("test_report", r"test\s+report|lab\s+report", 0.75),
    _v(
        "lab_department",
        r"\bbio-?chemistry\b|\bha?ematology\b|clinical\s+pathology"
        r"|immunoassay",
        1.0,
    ),
    _v(
        "collection_stamp",
        r"collection\s+date|collected\s+on|received?\s+date"
        r"|reported?\s+(?:date|on)",
        0.75,
    ),
    _v("authorised", r"authori[sz]ed|verified\s+by", 0.5),
)

# Analytes that belong to no panel in the taxonomy (hormones,
# vitamins, iron studies, tumour markers...). They count toward
# Stage-1 analyte evidence so single-assay reports still classify as
# lab_report (landing in other_lab), but fire no panel.
EXTRA_ANALYTE_PATTERNS: tuple[VocabPattern, ...] = (
    _v("cortisol", r"\bcortisol\b"),
    _v("vitamin_d", r"vitamin\s*-?\s*d\b|25\s*-?\s*oh\b"),
    _v("vitamin_b12", r"vitamin\s*-?\s*b\s*-?\s*12|cyanocobalamin"),
    _v("folate", r"\bfolate\b|folic\s+acid"),
    _v("ferritin", r"\bferritin\b"),
    _v("iron_studies", r"serum\s+iron|\bTIBC\b|transferrin"),
    _v("esr", r"\bESR\b|erythrocyte\s+sedimentation"),
    _v("crp", r"c\s*-?\s*reactive\s+protein|\bCRP\b"),
    _v("testosterone", r"\btestosterone\b"),
    _v("prolactin", r"\bprolactin\b"),
    _v("fsh_lh", r"\bFSH\b|\bLH\b|luteini[sz]ing"),
    _v("estradiol", r"\bo?estradiol\b|\bprogesterone\b"),
    _v("psa", r"\bPSA\b|prostate\s+specific\s+antigen"),
    _v("amylase_lipase", r"\bamylase\b|\blipase\b"),
    _v("magnesium_phosphorus", r"\bmagnesium\b|\bphosphorus\b"),
)

RADIOLOGY_PATTERNS: tuple[VocabPattern, ...] = (
    _v("xray", r"x\s*-?\s*ray|radiograph", 1.5),
    _v(
        "ct",
        r"\bCT\s+(?:scan|brain|chest|abdomen|head|kub)"
        r"|computed\s+tomography",
        1.5,
    ),
    _v("mri", r"\bMRI\b|magnetic\s+resonance", 1.5),
    _v(
        "ultrasound",
        r"ultra\s*-?\s*sound|ultrasonograph|\bUSG\b" r"|\bdoppler\b",
        1.5,
    ),
    _v("echo", r"echocardiograph|2d\s*echo", 1.5),
    _v("mammography", r"mammogra", 1.5),
    _v("dexa", r"\bDEXA\b|bone\s+densitometry", 1.5),
    _v("radiology_dept", r"\bradiolog(?:y|ist)\b", 1.5),
    # PACS-style headers on hospital imaging reports.
    _v("modality", r"modality\s+(?:US|CT|MRI?|CR|DX|MG)\b", 1.5),
    _v("study_date", r"study\s*date", 0.75),
    _v("views", r"\b(?:AP|PA|lateral|oblique)\s+view|\bviews?\b", 0.75),
    _v("impression", r"\bimpression\s*:", 0.5),
    _v("findings", r"\bfindings?\s*:", 0.5),
)

# Vocabulary for the "other" bucket: prescriptions, discharge
# summaries, and InBody body-composition scans (which have their own
# ingestion pipeline and are neither lab nor radiology).
OTHER_DOC_PATTERNS: tuple[VocabPattern, ...] = (
    _v("rx", r"(?<![a-z])rx(?![a-z])", 1.5),
    _v("discharge", r"discharge\s+summary", 1.5),
    # No trailing \b on "inbody" — device model strings like
    # "InBody380" must match.
    _v(
        "inbody",
        r"\binbody|body\s+composition\s+analysis"
        r"|skeletal\s+muscle\s+mass|body\s+fat\s+mass"
        r"|muscle\s*-?\s*fat\s+analysis",
        2.5,
    ),
    _v(
        "ophthalmology",
        r"retinopathy|glaucoma|\bfundus\b|ophthalmolog"
        r"|intraocular\s+pressure",
        1.5,
    ),
    # Clinic letterheads on (often handwritten) consult notes.
    # Pathologist/microbiologist excluded — they sign lab reports.
    _v(
        "consultant_letterhead",
        r"consultant\s+(?!patho|microbio)\w+olog?ist" r"|outpatient\s+record",
        1.5,
    ),
    _v("clinic", r"\bclinic\b", 0.5),
    _v("tablet", r"\btab\.?\b|\btablets?\b|\bcap\.?\b|\bcapsules?\b", 0.75),
    _v("frequency", r"\b(?:od|bd|tds|qid|hs|sos)\b|\b[01]-[01]-[01]\b", 1.0),
    _v("dosage_mg", r"\b\d+\s*mg\b", 0.5),
    _v("clinical_advice", r"\badvi[cs]ed?\b|follow\s*-?\s*up", 0.5),
    _v("diagnosis", r"\bdiagnosis\b|chief\s+complaints?", 0.5),
)

# Units that only appear in lab result tables.
UNIT_HINT_RE = _p(
    r"g/dl|mg/dl|mmol/l|meq/l|iu/l|u/l|ng/ml|pg/ml|ng/dl|µ?g/dl"
    r"|µ?iu/ml|/cumm|/cmm|mill?/cmm|lakhs?/cmm|thou\w*/|10\^|\bfL\b"
    r"|/hpf|/lpf|sec(?:onds)?\b"
)

# Result-line building blocks (see engine._count_result_lines).
NUM_RE = _p(r"\d+(?:\.\d+)?")
RANGE_RE = _p(r"\d[\d,]*(?:\.\d+)?\s*[-–—]\s*\d[\d,]*(?:\.\d+)?")
COMPARATOR_RE = _p(r"[<>≤≥]\s*=?\s*\d")
UPTO_RE = _p(r"\bup\s*to\s+\d")
DATE_RE = _p(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}")
