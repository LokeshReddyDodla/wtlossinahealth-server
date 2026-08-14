"""Synthetic text_raw fixtures — realistic OCR-ish Indian lab report
text, one per subtype, plus radiology/prescription/noise negatives."""

CBC_TEXT = """
COMPLETE BLOOD COUNT (CBC)
Specimen: EDTA Whole Blood        Method: Automated Cell Counter
Haemoglobin              14.2   g/dL       13.0 - 17.0
Total Leucocyte Count    7800   /cumm      4000 - 11000
RBC Count                5.1    mill/cmm   4.5 - 5.5
Haematocrit (PCV)        42.1   %          40 - 50
MCV                      86.5   fL         83 - 101
MCH                      28.4   pg         27 - 32
MCHC                     32.8   g/dL       31.5 - 34.5
RDW-CV                   13.1   %          11.6 - 14.0
Platelet Count           2.4    lakhs/cmm  1.5 - 4.1
Neutrophils              62     %          40 - 80
Lymphocytes              28     %          20 - 40
Eosinophils              3      %          1 - 6
Bio. Ref. Interval as per laboratory standards
"""

CMP_TEXT = """
COMPREHENSIVE METABOLIC PANEL (CMP)
Specimen: Serum          Method: Ion Selective Electrode
Glucose                  92    mg/dL    70 - 99
Calcium                  9.4   mg/dL    8.6 - 10.2
Sodium                   139   mEq/L    136 - 145
Potassium                4.2   mEq/L    3.5 - 5.1
Chloride                 103   mEq/L    98 - 107
Carbon Dioxide           26    mEq/L    21 - 32
Blood Urea Nitrogen (BUN) 14   mg/dL    6 - 20
Creatinine               0.9   mg/dL    0.7 - 1.3
Albumin                  4.3   g/dL     3.5 - 5.0
Total Protein            7.1   g/dL     6.4 - 8.3
Total Bilirubin          0.7   mg/dL    0.2 - 1.2
ALT (SGPT)               28    U/L      7 - 56
AST (SGOT)               24    U/L      10 - 40
Alkaline Phosphatase     76    U/L      44 - 147
"""

BMP_TEXT = """
BASIC METABOLIC PANEL (BMP)
Specimen: Serum          Method: Ion Selective Electrode
Glucose                  95    mg/dL    70 - 99
Calcium                  9.2   mg/dL    8.6 - 10.2
Sodium                   140   mEq/L    136 - 145
Potassium                4.0   mEq/L    3.5 - 5.1
Chloride                 102   mEq/L    98 - 107
Carbon Dioxide           25    mEq/L    21 - 32
Blood Urea Nitrogen (BUN) 15   mg/dL    6 - 20
Creatinine               1.0   mg/dL    0.7 - 1.3
"""

LFT_TEXT = """
LIVER FUNCTION TEST (LFT)
Specimen: Serum
Bilirubin Total          0.8   mg/dL    0.2 - 1.2
Bilirubin Direct         0.2   mg/dL    0.0 - 0.3
SGPT (ALT)               32    U/L      7 - 56
SGOT (AST)               28    U/L      10 - 40
Alkaline Phosphatase     84    U/L      44 - 147
GGT                      24    U/L      8 - 61
Total Protein            7.2   g/dL     6.4 - 8.3
Albumin                  4.4   g/dL     3.5 - 5.0
Globulin                 2.8   g/dL     2.0 - 3.5
"""

KFT_TEXT = """
KIDNEY FUNCTION TEST (KFT / RFT)
Specimen: Serum
Blood Urea               26    mg/dL    15 - 40
Serum Creatinine         0.9   mg/dL    0.6 - 1.2
Uric Acid                5.1   mg/dL    3.5 - 7.2
eGFR                     98    mL/min   Up to 120
"""

LIPID_TEXT = """
LIPID PROFILE
Specimen: Serum (Fasting)   Method: CHOD-PAP
Total Cholesterol        182   mg/dL    125 - 200
Triglycerides            140   mg/dL    25 - 150
HDL Cholesterol          46    mg/dL    40 - 60
LDL Cholesterol          108   mg/dL    Up to 130
VLDL Cholesterol         28    mg/dL    5 - 40
"""

HBA1C_TEXT = """
GLYCATED HAEMOGLOBIN (HbA1c)
Specimen: EDTA Whole Blood     Method: HPLC
HbA1c                    6.1   %        4.0 - 5.6
Estimated Average Glucose (eAG) 128 mg/dL 90 - 140
"""

THYROID_TEXT = """
THYROID PROFILE (TFT)
Specimen: Serum          Method: ECLIA
Total T3                 102   ng/dL    80 - 200
Total T4                 8.4   ug/dL    5.1 - 14.1
TSH (Ultrasensitive)     2.8   uIU/mL   0.27 - 4.2
"""

COAG_TEXT = """
COAGULATION PROFILE
Specimen: Citrated Plasma
Prothrombin Time         13.2  sec      11.0 - 14.5
INR                      1.02           0.8 - 1.2
APTT                     29.5  sec      26 - 38
"""

CARDIAC_TEXT = """
CARDIAC MARKERS PANEL
Specimen: Serum
Troponin I               <0.01 ng/mL    Ref: <0.04
CK-MB                    18    U/L      5 - 25
NT-proBNP                62    pg/mL    < 125
"""

SEROLOGY_TEXT = """
DENGUE SEROLOGY REPORT
Specimen: Serum          Method: ELISA
Dengue NS1 Antigen  : Negative
Dengue IgM Antibody : Reactive
Dengue IgG Antibody : Non-Reactive
"""

URINALYSIS_TEXT = """
URINE ROUTINE AND MICROSCOPY
Sample Type: Mid-stream urine
Colour                   Pale Yellow
Appearance               Clear
Specific Gravity         1.020          1.005 - 1.030
Albumin                  Trace          Nil
Pus Cells                2-4   /hpf     0 - 5
Epithelial Cells         1-2   /hpf     0 - 2
Casts                    Nil
Crystals                 Nil
"""

URINE_CULTURE_TEXT = """
URINE CULTURE AND SENSITIVITY REPORT
Specimen: Mid-stream Urine
Culture: Significant growth of Escherichia coli
Colony Count: more than 100,000 CFU/mL
Antibiotic Susceptibility:
Nitrofurantoin  - Sensitive
Amikacin        - Sensitive
Ciprofloxacin   - Resistant
Ampicillin      - Resistant
"""

HISTOPATH_TEXT = """
HISTOPATHOLOGY REPORT
Specimen: Gall bladder
Gross Description: Received gall bladder measuring 7 x 3 cm.
Wall thickness 0.4 cm. Mucosa unremarkable.
Microscopy: Sections show mucosal ulceration with dense chronic
inflammatory infiltrate in the lamina propria.
Impression: Chronic cholecystitis. No evidence of malignancy.
Margins are free.
"""

CYTOPATH_TEXT = """
CYTOPATHOLOGY REPORT - PAP SMEAR
Specimen: Cervical smear
Adequacy: Satisfactory for evaluation
Reporting as per The Bethesda System
Result: Negative for Intraepithelial Lesion or Malignancy (NILM)
"""

PCR_TEXT = """
SARS-CoV-2 RT-PCR REPORT
Specimen: Nasopharyngeal swab
Method: Real Time Reverse Transcriptase PCR
E gene       : Not Detected
RdRp gene    : Not Detected
Ct Value     : Not Applicable
Result: SARS-CoV-2 RNA NOT DETECTED
"""

VITAMIN_IRON_TEXT = """
VITAMIN AND IRON STUDIES
Specimen: Serum
Vitamin D (25-OH)        22.4  ng/mL    30 - 100
Vitamin B12              342   pg/mL    211 - 946
Serum Iron               82    ug/dL    65 - 175
TIBC                     340   ug/dL    250 - 450
Ferritin                 96    ng/mL    30 - 400
Transferrin Saturation   24    %        20 - 50
"""

INBODY_TEXT = """
InBody
ID 9820958051  Height 168cm  Age 66  Male
[InBody380]  Test Date / Time 16.10.2025 12:24
Body Composition Analysis
Total Body Water 43.4 (34.9 - 42.7)
Protein 11.7 (9.4 - 11.4)
Minerals 4.1
Body Fat Mass 20.5
Muscle-Fat Analysis
"""

HORMONE_TEXT = """
MANIPAL HOSPITALS
Biochemistry
Cortisol 8 AM
Specimen No: 2501513030-1; Collection Date & Time: 20/11/2025 11:38
Cortisol (Serum)         14.2  ug/dL    4.3 - 22.4
Method: CLIA
Authorised on 20/11/2025 12:08
"""

XRAY_TEXT = """
X-RAY CHEST PA VIEW
Both lung fields are clear.
Cardiac silhouette is within normal limits.
Costophrenic angles are free.
IMPRESSION: No active pleuro-parenchymal pathology.
"""

CT_TEXT = """
CT SCAN BRAIN (PLAIN)
Axial sections of the brain were obtained.
No evidence of acute infarct or intracranial bleed.
Ventricular system is normal in size and configuration.
IMPRESSION: Normal study of the brain.
"""

PRESCRIPTION_TEXT = """
City Care Clinic
Dr. Sharma, MD (Medicine)
Diagnosis: Type 2 Diabetes Mellitus
Rx
Tab. Metformin 500 mg 1-0-1 after food
Tab. Telmisartan 40 mg OD
Advised: review with reports after 3 months
Follow-up after 3 months
"""

GARBAGE_OCR_TEXT = """
iii lll 111 ;;; ::: --- ~~~ %%% jjj kkk qqq www eee rrr yyy uuu
"""

EMPTY_TEXT = ""

FULL_BODY_PACKAGE_TEXT = "\n".join(
    [CBC_TEXT, LFT_TEXT, LIPID_TEXT, THYROID_TEXT]
)

COMBINED_URINE_TEXT = "\n".join([URINALYSIS_TEXT, URINE_CULTURE_TEXT])
