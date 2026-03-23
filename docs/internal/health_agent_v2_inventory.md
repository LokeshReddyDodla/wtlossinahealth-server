# Health Agent V2 Inventory

## Purpose
This document freezes the currently discoverable data surface for the health query agent so V2 can be implemented against real system capabilities instead of meal-only assumptions.

## Data Inventory Matrix
| Domain | Canonical internal domain | Primary stores | Runtime access pattern | Notes |
| --- | --- | --- | --- | --- |
| Meals | `meal` | Mongo `meal_reports`, Qdrant `meal` | Daily report fetch, Qdrant semantic search | Includes meal-level macros, micros, tags, items, meal time/type |
| CGM | `cgm` | Mongo `cgm_reports`, Qdrant CGM stat/event/window payloads | Daily/custom report fetch, Qdrant semantic search | Supports summary, range, event, time-period, AGP, semantic windows |
| SMBG | `smbg` | Qdrant `smbg`, SMBG schemas/processors | Qdrant semantic search, report processors | Supports individual readings, by-date views, meal-window stats |
| Fitness | `fitness` | Mongo `fitness_reports`, Qdrant `fitness_overview`, `fitness_activity_distribution`, `fitness_inactive_periods` | Daily/weekly/monthly report fetch, Qdrant search | Steps, active duration, peak activity, inactivity, day-part distribution |
| Profile | `profile` | Postgres profile services, Qdrant `profile` | Profile service + Qdrant semantic search | Demographics, body metrics, allergies, habits, diabetes and family history |
| Documents | `documents` | Mongo `patient_documents`, S3 blobs, Qdrant `patient_document` | Mongo fetch + Qdrant search | Summaries and embeddings already exist for uploaded documents |
| Sleep | `sleep` | Mongo `sleep_reports`, patient summaries | Daily report fetch and summary service | Not yet exposed by health query agent intent taxonomy |
| Vitals | `vitals` | Postgres `PatientVital`, patient summaries | SQL aggregation via summary service | Weight, BP, HR, SpO2, temperature, RR, ketones, A1c |
| Patient summary | `patient_summary` | Mongo `patient_summaries` | Daily summary snapshot fetch | Cross-domain aggregate snapshot |

## Collections and Sources of Truth
- Mongo
  - `meal_reports`
  - `cgm_reports`
  - `fitness_reports`
  - `sleep_reports`
  - `patient_summaries`
  - `patient_documents`
  - `patient_document_summary_interactions`
  - `health_query_conversations`
- Redis
  - LangGraph checkpoint state under health-query-agent namespace
- Qdrant
  - `patient_data` collection for meal, CGM, SMBG, fitness, profile, and document vectors
- Postgres
  - patient profile data and `PatientVital`
- S3
  - uploaded patient documents and export artifacts

## Supported Task Matrix
| Task type | Meal | CGM | SMBG | Fitness | Profile | Documents | Sleep | Vitals | Patient summary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `list` | Yes | Partial | Partial | Partial | Yes | Yes | Partial | Partial | No |
| `summarize` | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `evaluate` | Yes | Yes | Yes | Yes | Partial | Partial | Partial | Partial | Yes |
| `compare` | Yes | Yes | Yes | Yes | Limited | Limited | Partial | Partial | Partial |
| `recommend` | Goal-framed only | Goal-framed only | Goal-framed only | Goal-framed only | Context only | Limited | Limited | Limited | Overview only |
| `clarify` | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

## Gaps Between Data Surface and Current Agent
1. The current intent taxonomy still mainly originates from legacy `HealthDataType` coverage, so `sleep`, `vitals`, and `patient_summary` rely partly on planner/context routing rather than fully explicit intent labels.
2. Cross-domain reasoning quality still depends on expanding analyzer coverage for more domains and mixed-domain cases.
3. Conversation compaction is now modeled and queued, but long-horizon summary reuse should be hardened with worker-level observability and retention policy.
4. Profile and vitals remain partly dependent on upstream materialization into patient summaries for the health-agent request path.

## Canonical Domain Names for V2
- `meal`
- `cgm`
- `smbg`
- `fitness`
- `profile`
- `documents`
- `sleep`
- `vitals`
- `patient_summary`

## V2 Source-of-Truth Map
- Use Mongo for canonical raw reports and durable memory.
- Use Redis for active thread state.
- Use Qdrant for semantic retrieval over already indexed payloads and compacted summaries.
- Use Postgres for structured patient profile and vitals source data.
- Use S3 only for artifacts and document blobs.
