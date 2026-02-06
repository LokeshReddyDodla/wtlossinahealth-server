# CGM Vector Point Structure

This document describes the structure of CGM data points stored in the Qdrant vector database.

## Overview

CGM (Continuous Glucose Monitoring) points represent glucose data from CGM devices, including statistics, events, and time-based aggregations.

## Base Payload Structure

All CGM points include these common fields:

```json
{
  "patient_id": "uuid-string",
  "patient_age": 45,
  "patient_gender": "male",
  "report_id": "report_123",
  "data_type": "cgm_range_stats",
  "text_repr": "CGM range stats from 2024-01-15T00:00:00 to 2024-01-16T00:00:00: ...",
  "start_time": 1705276800000,
  "end_time": 1705363200000,
  "date": "2024-01-15",
  "day_of_week": 0,
  "is_weekend": false,
  "week_number": 3,
  "month": 1,
  "time_of_day_bucket": ["morning", "afternoon"]
}
```

## Data Types

### Statistics Types

- `cgm_range_stats` - Time in range statistics
- `cgm_summary_stats` - Summary statistics (average, GMI, variability)
- `hyper_stats` - Hyperglycemia statistics
- `hypo_stats` - Hypoglycemia statistics
- `rapid_spike_stats` - Rapid glucose spike statistics
- `rapid_drop_stats` - Rapid glucose drop statistics
- `time_period_stats` - Time period specific statistics

### Event Types

- `hyper_event` - Individual hyperglycemia events
- `hypo_event` - Individual hypoglycemia events
- `rapid_spike_event` - Individual rapid spike events
- `rapid_drop_event` - Individual rapid drop events

### Aggregation Types

- `agp_point` - Ambulatory Glucose Profile points (hourly)
- `cgm_semantic_window` - 30-minute aggregated reading windows

## Examples

### CGM Range Stats Point

```json
{
  "id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "vector": [0.123, -0.456, 0.789, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "report_123",
    "data_type": "cgm_range_stats",
    "text_repr": "CGM range stats from 2024-01-15T00:00:00 to 2024-01-16T00:00:00: time_in_range_70_180_percent: 75.50%, time_above_180_250_percent: 15.20%, time_above_250_percent: 1.80%, time_below_70_54_percent: 5.00%, time_below_54_percent: 2.50%.",
    "start_time": 1705276800000,
    "end_time": 1705363200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["all_day"],
    "data": {
      "below_54_percent": 2.5,
      "below_70_above_54_percent": 5.0,
      "in_target_70_180_percent": 75.5,
      "above_180_below_250_percent": 15.2,
      "above_250_percent": 1.8
    }
  }
}
```

### Hyper Event Point

```json
{
  "id": "b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7",
  "vector": [0.234, -0.567, 0.890, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "report_123",
    "data_type": "hyper_event",
    "text_repr": "Hyper event: start_time: 2024-01-15T14:30:00, end_time: 2024-01-15T16:45:00, duration_minutes: 135, peak_glucose_mgdl: 245.",
    "start_time": 1705329000000,
    "end_time": 1705335900000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "duration_minutes": 135,
    "peak_glucose_mgdl": 245
  }
}
```

### AGP Point

```json
{
  "id": "c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8",
  "vector": [0.345, -0.678, 0.901, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "report_123",
    "data_type": "agp_point",
    "text_repr": "AGP point for hour: 2:00 PM, median_mgdl: 140, percentile_10_mgdl: 110, percentile_25_mgdl: 125, percentile_75_mgdl: 155, percentile_90_mgdl: 170, report_period: 2024-01-15T00:00:00 to 2024-01-16T00:00:00.",
    "start_time": 1705276800000,
    "end_time": 1705363200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "hour": 14,
    "data": {
      "hour": "2:00 PM",
      "median_mgdl": 140,
      "percentile_10_mgdl": 110,
      "percentile_25_mgdl": 125,
      "percentile_75_mgdl": 155,
      "percentile_90_mgdl": 170
    }
  }
}
```

### CGM Semantic Window (30-minute bucket)

```json
{
  "id": "d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9",
  "vector": [0.456, -0.789, 0.012, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "report_id": "report_123",
    "data_type": "cgm_semantic_window",
    "text_repr": "CGM semantic window from 2024-01-15T14:00:00 to 2024-01-15T14:30:00: readings_count: 12, min_glucose_mgdl: 125, avg_glucose_mgdl: 142.5, max_glucose_mgdl: 165.",
    "start_time": 1705327200000,
    "end_time": 1705329000000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "readings_count": 12,
    "min_glucose_mgdl": 125,
    "avg_glucose_mgdl": 142.5,
    "max_glucose_mgdl": 165
  }
}
```

## Point ID Generation

CGM point IDs are generated using MD5 hashing:

- **Stats/Summary**: `MD5(patient_id-report_id-data_type-start_time-end_time)`
- **Events**: `MD5(patient_id-report_id-data_type-start_time-end_time-event_hash)`
- **AGP Points**: `MD5(patient_id-report_id-data_type-start_time-end_time-hour_14)`
- **Time Period Stats**: `MD5(patient_id-report_id-data_type-start_time-end_time-period_morning)`
- **Semantic Windows**: `MD5(patient_id-report_id-data_type-start_time-end_time-bucket_2024-01-15T14:00:00)`
