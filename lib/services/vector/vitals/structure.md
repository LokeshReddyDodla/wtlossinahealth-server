# Patient Vitals Vector Point Structure

This document describes the structure of Patient Vitals data points stored in the Qdrant vector database.

## Overview

Vitals points represent individual vital sign readings including blood pressure, heart rate, temperature, oxygen saturation, and other clinical measurements.

## Base Payload Structure

All Vitals points include these common fields:

```json
{
  "patient_id": "uuid-string",
  "patient_age": 45,
  "patient_gender": "male",
  "data_type": "vital",
  "text_repr": "Vital signs recorded on 2024-01-15 at 14:30. ...",
  "start_time": 1705324200000,
  "end_time": 1705324200000,
  "date": "2024-01-15",
  "day_of_week": 0,
  "is_weekend": false,
  "week_number": 3,
  "month": 1,
  "time_of_day_bucket": ["afternoon"]
}
```

## Data Type

- `vital` - Individual vital sign reading

## Example: Vitals Point

```json
{
  "id": "k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
  "vector": [0.123, -0.456, 0.789, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "data_type": "vital",
    "text_repr": "Vital signs recorded on 2024-01-15 at 14:30. Measurements: Blood pressure: 120/80 mmHg, Heart rate: 72 bpm, Temperature: 36.5°C, Oxygen saturation (SpO2): 98%, Respiratory rate: 16 breaths/min, Weight: 75 kg, HbA1c: 6.2%, Creatinine: 0.9 mg/dL. Recorded via source: Health App, platform: iOS. Health status: normal blood pressure, normal heart rate, normal oxygen saturation, normal temperature, elevated HbA1c (prediabetes range).",
    "start_time": 1705324200000,
    "end_time": 1705324200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "vital_id": "vital_456",
    "hour": 14,
    "a1c": 6.2,
    "creatinine": 0.9,
    "diastolic_bp": 80,
    "systolic_bp": 120,
    "heart_rate": 72,
    "ketones": null,
    "respiratory_rate": 16,
    "spo2": 98,
    "temperature": 36.5,
    "weight": 75,
    "test_time": 1705324200000,
    "source_name": "Health App",
    "source_platform": "iOS",
    "uploaded_at": 1705324300000
  }
}
```

## Field Descriptions

### Vital-Specific Fields

- **vital_id**: Unique vital reading identifier
- **hour**: Hour of day (0-23) when reading was taken
- **a1c**: HbA1c (glycated hemoglobin) percentage
- **creatinine**: Creatinine level in mg/dL
- **diastolic_bp**: Diastolic blood pressure in mmHg
- **systolic_bp**: Systolic blood pressure in mmHg
- **heart_rate**: Heart rate in beats per minute (bpm)
- **ketones**: Ketone level in mmol/L
- **respiratory_rate**: Respiratory rate in breaths per minute
- **spo2**: Oxygen saturation (SpO2) percentage
- **temperature**: Body temperature in Celsius
- **weight**: Weight in kilograms
- **test_time**: Timestamp of vital reading (milliseconds)
- **source_name**: Name of the source device/app
- **source_platform**: Platform of the source (e.g., "iOS", "Android", "Web")
- **uploaded_at**: Timestamp when vital was uploaded (milliseconds)

## Vital Measurements

### Blood Pressure

- **Normal**: Systolic < 120 and Diastolic < 80
- **Elevated**: Systolic 120-129 and Diastolic < 80
- **High Stage 1**: Systolic 130-139 or Diastolic 80-89
- **High Stage 2**: Systolic ≥ 140 or Diastolic ≥ 90
- **Low**: Systolic < 90 or Diastolic < 60

### Heart Rate

- **Normal**: 60-100 bpm (resting)
- **Tachycardia**: > 100 bpm
- **Bradycardia**: < 60 bpm

### Temperature

- **Normal**: 36.0-37.5°C
- **Fever**: > 37.5°C
- **Hypothermia**: < 36.0°C

### SpO2 (Oxygen Saturation)

- **Normal**: ≥ 95%
- **Low**: < 95%

### HbA1c

- **Normal**: < 5.7%
- **Prediabetes**: 5.7-6.4%
- **Diabetes**: ≥ 6.5%

## Text Representation

The text representation includes:

- Date and time of recording
- All available vital measurements with units
- Source information
- Health status interpretation (normal, elevated, low, etc.)

## Point ID Generation

Vitals point IDs are generated using MD5 hashing:

- **Vital Reading**: `MD5(vital_id)`

The vital_id is hashed directly to create a unique identifier for each vital reading.
