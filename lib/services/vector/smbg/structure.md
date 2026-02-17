# SMBG Vector Point Structure

This document describes the structure of SMBG (Self-Monitoring Blood Glucose) data points stored in the Qdrant vector database.

## Overview

SMBG points represent individual fingerstick blood glucose readings with metadata about the reading type, timing, and context.

## Base Payload Structure

All SMBG points include these common fields:

```json
{
  "patient_id": "uuid-string",
  "patient_age": 45,
  "patient_gender": "male",
  "data_type": "smbg",
  "text_repr": "Blood glucose reading (pre-meal). ...",
  "start_time": 1705321800000,
  "end_time": 1705321800000,
  "date": "2024-01-15",
  "day_of_week": 0,
  "is_weekend": false,
  "week_number": 3,
  "month": 1,
  "time_of_day_bucket": ["afternoon"]
}
```

## Data Type

- `smbg` - Individual SMBG reading

## Example: SMBG Point

```json
{
  "id": "i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4",
  "vector": [0.901, -0.234, 0.567, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "data_type": "smbg",
    "text_repr": "Blood glucose reading (pre-meal). Glucose level: 125 mg/dL. Recorded on 2024-01-15 at 12:30. Source: app. The glucose reading is within normal range for a pre-meal reading.",
    "start_time": 1705321800000,
    "end_time": 1705321800000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "reading_id": "smbg_123",
    "hour": 12,
    "glucose_mgdl": 125,
    "reading_type": "pre-meal",
    "reading_time": 1705321800000,
    "notes": "Before lunch",
    "source": "app",
    "uploaded_at": 1705321900000
  }
}
```

## Field Descriptions

### SMBG-Specific Fields

- **reading_id**: Unique reading identifier
- **hour**: Hour of day (0-23) when reading was taken
- **glucose_mgdl**: Glucose value in mg/dL
- **reading_type**: Type of reading:
  - `pre-meal` - Before a meal
  - `post-meal` - After a meal
  - `fasting` - Fasting reading
  - `bedtime` - Before bed
  - `unspecified` - Unknown type
- **reading_time**: Timestamp of reading (milliseconds)
- **notes**: Optional notes about the reading
- **source**: Source of reading (e.g., "app", "device")
- **uploaded_at**: Timestamp when reading was uploaded (milliseconds)

## Text Representation

The text representation includes:
- Reading type context
- Glucose value with units
- Date and time of reading
- Source information
- Health interpretation (low, normal, high)

## Point ID Generation

SMBG point IDs are generated using MD5 hashing:

- **SMBG Reading**: `MD5(reading_id)`

The reading_id is hashed directly to create a unique identifier for each reading.
