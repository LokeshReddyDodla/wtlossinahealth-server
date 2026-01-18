# Data Definitions

> IMPORTANT
>
> This file is the single source of truth for:
>
> - HealthDataType enum values
> - Qdrant payload field names
>
> Field names MUST be used exactly as written here.
> Never invent, rename, paraphrase, or infer field names.

This file contains shared data type and field definitions used across prompts.
All planners, classifiers, and executors MUST follow these definitions.

---

## Available Data Types

- CGM / Glucose data:
  CGM_RANGE, CGM_SUMMARY, AGP, SMBG

- Glucose events:
  HYPER_STATS, HYPO_STATS,
  RAPID_SPIKE_STATS, RAPID_DROP_STATS,
  HYPER_EVENT, HYPO_EVENT,
  RAPID_SPIKE_EVENT, RAPID_DROP_EVENT

- Meals:
  MEAL

- Fitness / Activity:
  FITNESS_OVERVIEW, FITNESS_DIST, FITNESS_INACTIVE  
  (Keywords like "sports", "exercise", "workout" map to fitness data types)

- Time periods:
  TIME_PERIOD_STATS

- Profile:
  PROFILE

- Documents:
  DOCUMENTS

---

## Data Fields Available in Qdrant

### MEAL

Fields:

- `nutrition.proteins`
- `nutrition.carbohydrates`
- `nutrition.fats`
- `nutrition.calories`
- `nutrition.fiber`
- `nutrition.calcium`
- `nutrition.iron`
- `nutrition.zinc`
- `nutrition.magnesium`
- `meal_type`
- `meal_date`
- `meal_time`

Maps to:
Questions about protein intake, carbohydrate intake, calories, macronutrients,
meal patterns, eating habits, or diet analysis.

---

### CGM_SUMMARY

Fields:

- `data.average_glucose_mgdl`
- `data.gmi`
- `data.glucose_variability_percent`
- `data.highest_glucose_mgdl`
- `data.lowest_glucose_mgdl`
- `data.coefficient_of_variation_percent`

Maps to:
Questions about average glucose, glucose variability, GMI, highs/lows, summaries.

---

### CGM_RANGE

Fields:

- `data.in_target_70_180_percent`
- `data.below_54_percent`
- `data.below_70_above_54_percent`
- `data.above_180_below_250_percent`
- `data.above_250_percent`

Maps to:
Questions about time-in-range, glucose ranges, and target percentages.

---

### SMBG

Fields:

- `glucose_mgdl`
- `reading_type`
- `reading_time`
- `uploaded_at`
- `reading_id`
- `notes`
- `source`

Maps to:
Fingerstick glucose readings, SMBG history, last reading, uploads, timing.

---

### FITNESS_OVERVIEW

Fields:

- `steps`
- `active_duration`
- `active_energy`
- `average_active_session_duration`
- `peak_hour`
- `peak_steps`
- `peak_active_energy`

Maps to:
Questions about activity, steps, workouts, exercise, and active time.

---

### FITNESS_DIST (fitness_activity_distribution)

Fields:

- `morning_steps`
- `afternoon_steps`
- `evening_steps`
- `night_steps`
- `morning_duration`
- `afternoon_duration`
- `evening_duration`
- `night_duration`

Maps to:
Questions about activity distribution by time of day.

---

### HYPER_STATS / HYPO_STATS

Fields:

- `total_hyper_duration_minutes`
- `hyper_events_count`
- `total_hypo_duration_minutes`
- `hypo_events_count`

Maps to:
Questions about hyperglycemia or hypoglycemia frequency and duration.

---

### PROFILE

Fields:

- `patient_id`
- `first_name`
- `last_name`
- `age`
- `gender`
- `height`
- `weight`
- `waist`
- `bmi`

Maps to:
Patient demographics, identity, physical attributes, BMI, age, etc.

---

### DOCUMENTS (patient_document)

Fields:

- `document_type`

Maps to:
Reports, prescriptions, lab results, scans, medical records, test results.

Keywords include:
"reports", "prescriptions", "prescription", "documents", "lab results",
"blood test", "x-ray", "MRI", "CT scan", "ultrasound", "medical records"

---

## Numeric Filterable Fields

Rules:

- NEVER paraphrase field names in numeric_filters
- Use ONLY exact payload keys listed in this file

Example:

- ❌ "average glucose"
- ✅ `data.average_glucose_mgdl`

---

### MEAL (Numeric Fields)

`nutrition.proteins`, `nutrition.carbohydrates`, `nutrition.fats`,
`nutrition.calories`, `nutrition.fiber`, `nutrition.calcium`,
`nutrition.iron`, `nutrition.zinc`, `nutrition.magnesium`

---

### CGM_SUMMARY (Numeric Fields)

`data.average_glucose_mgdl`, `data.gmi`,
`data.glucose_variability_percent`,
`data.highest_glucose_mgdl`,
`data.lowest_glucose_mgdl`,
`data.coefficient_of_variation_percent`

---

### SMBG (Numeric Fields)

`glucose_mgdl`

---

### FITNESS_OVERVIEW (Numeric Fields)

`steps`, `active_duration`, `active_energy`,
`peak_steps`, `peak_active_energy`

---

### PROFILE (Numeric Fields)

`age`, `height`, `weight`, `waist`, `bmi`
