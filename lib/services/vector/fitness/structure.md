# Fitness Vector Point Structure

This document describes the structure of Fitness data points stored in the Qdrant vector database.

## Overview

Fitness points represent physical activity data including steps, active duration, energy expenditure, and inactive periods.

## Base Payload Structure

All Fitness points include these common fields:

```json
{
  "patient_id": "uuid-string",
  "patient_age": 45,
  "patient_gender": "male",
  "report_id": "fitness_report_456",
  "data_type": "fitness_overview",
  "text_repr": "Fitness summary from 2024-01-15T00:00:00 to 2024-01-16T00:00:00: ...",
  "start_time": 1705276800000,
  "end_time": 1705363200000,
  "date": "2024-01-15",
  "day_of_week": 0,
  "is_weekend": false,
  "week_number": 3,
  "month": 1,
  "time_of_day_bucket": ["all_day"]
}
```

## Data Types

- `fitness_overview` - Daily fitness summary
- `fitness_activity_distribution` - Activity distribution across time periods
- `fitness_inactive_periods` - Periods of inactivity

## Examples

### Fitness Overview Point

```json
{
  "id": "e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
  "vector": [0.567, -0.890, 0.123, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "fitness_report_456",
    "data_type": "fitness_overview",
    "text_repr": "Fitness summary from 2024-01-15T00:00:00 to 2024-01-16T00:00:00: steps: 8500, active_duration: 120 min, active_energy: 450, average_active_session_duration: 30.5, peak activity hour: 18 with 2500 steps.",
    "start_time": 1705276800000,
    "end_time": 1705363200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["all_day"],
    "steps": 8500,
    "active_duration": 120,
    "active_energy": 450,
    "average_active_session_duration": 30.5,
    "peak_hour": 18,
    "peak_steps": 2500,
    "peak_active_energy": 150
  }
}
```

### Fitness Activity Distribution Point

```json
{
  "id": "f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1",
  "vector": [0.678, -0.901, 0.234, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "fitness_report_456",
    "data_type": "fitness_activity_distribution",
    "text_repr": "Activity distribution from 2024-01-15T00:00:00 to 2024-01-16T00:00:00: morning: 2000 steps, 30 min active; afternoon: 3000 steps, 45 min active; evening: 3500 steps, 45 min active.",
    "start_time": 1705276800000,
    "end_time": 1705363200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["all_day"],
    "morning_steps": 2000,
    "afternoon_steps": 3000,
    "evening_steps": 3500,
    "night_steps": 0,
    "morning_duration": 30,
    "afternoon_duration": 45,
    "evening_duration": 45,
    "night_duration": 0,
    "morning_energy": 100,
    "afternoon_energy": 150,
    "evening_energy": 200,
    "night_energy": 0
  }
}
```

### Fitness Inactive Period Point

```json
{
  "id": "g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2",
  "vector": [0.789, -0.012, 0.345, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "fitness_report_456",
    "data_type": "fitness_inactive_periods",
    "text_repr": "Inactive period: 180 minutes from 2024-01-15T22:00:00 to 2024-01-16T01:00:00.",
    "start_time": 1705356000000,
    "end_time": 1705366800000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["night"],
    "inactive_duration": 180
  }
}
```

## Point ID Generation

Fitness point IDs are generated using MD5 hashing:

- **Overview/Distribution**: `MD5(patient_id-report_id-data_type-start_time-end_time)`
- **Inactive Periods**: `MD5(patient_id-report_id-data_type-start_time-end_time)`
