# Day Timeline — `resolve(patient, date)`

One screen, one day: glucose spine + every domain on a shared 24h clock, for
patients and care providers. This doc is the build contract for the **read-only
resolver** that powers it.

## Principle

**Compose on read. Do not materialize a day document.**

The day view embeds high-frequency raw series (CGM syncs ~288×/day, steps, HR).
Materializing an assembled day doc would rebuild it on every sync — real write
amplification, staleness, shared-doc write ordering — to speed up a read that
isn't slow. The expensive math is *already* materialized at the right grain: the
per-domain reports (meal `glucose_response`, cgm events, sleep stages, fitness
`inactive_periods`) update in place, only when their own domain logs. The day
view **composes** those + the raw series at request time.

**Hub-and-spoke.** The day endpoint returns a lean overview — the chart payload
plus one rollup number per domain. Full per-domain detail is *not* in this
payload; it loads on demand from the existing domain report, addressed by its
deterministic ID (see [Drill-down](#drill-down)). The overview is the map; the
reports are the territory, fetched when the provider walks into one.

## Endpoints

```
GET /v1/patients/{patient_id}/day?date=YYYY-MM-DD     → lean day payload (below)
GET /v1/patients/{patient_id}/day/{domain}?date=...   → full domain report (drill-down)
      domain ∈ glucose | meal | sleep | fitness        (checkins/care are Postgres, see below)
```

`date` is interpreted in the **patient's local timezone**. All day boundaries
(`day_start`, `day_end`) and the deterministic report IDs are computed from that
local day, then converted to naive datetimes for the Postgres `TIMESTAMP WITHOUT
TIME ZONE` columns and to the ISO bounds the report IDs hash over.

## Spine selection (degradation)

The resolver picks the highest-fidelity spine the patient has data for, in order:

| `spine.source` | Condition | Points from |
|---|---|---|
| `cgm` | day has CGM readings | CGM daily report `cgm_readings[]` |
| `smbg` | no CGM, ≥1 finger-stick | Postgres `PatientSMBG` (`_query_smbg`) — dots, **never** interpolated |
| `hr` | no glucose, ≥1 intraday HR sample | ClickHouse `vitals_data` type=`heart_rate`, downsampled |
| `none` | none of the above | omit the plot; render behavioral lanes only |

`hr` is a distinct physiological axis (resting band 60–100 bpm), **not** a glucose
surrogate — label it as heart rate; exercise peaks are expected, not flagged.

## Lean day payload

```jsonc
{
  "date": "2026-08-06",
  "tz": "Asia/Kolkata",
  "spine": {
    "source": "cgm",                       // cgm | smbg | hr | none
    "unit": "mg/dL",                        // "bpm" when source=hr
    "points": [[0.0, 86], [0.12, 84], ...], // [hour_float, value]; dots (not a line) when source=smbg
    "band": [70, 180],                      // resting [60,100] when source=hr
    "events": [                             // CGM excursion spans (source=cgm only)
      {"type": "hypo",  "start": 2.30, "end": 3.70, "peak": 66},
      {"type": "hyper", "start": 20.40, "end": 22.30, "peak": 205}
    ]
  },
  "onCurve": {                              // markers that share the spine's y-axis
    "meals": [
      {"t": 20.70, "name": "Dinner · rice & dal", "type": "dinner",
       "delta_mgdl": 54, "score": 0.45, "comparison": "above",
       "predicted": [30, 48], "carbs_g": 68}
    ],
    "symptoms": [{"t": 14.40, "name": "Headache", "severity": 3}],
    "workouts": [{"t": 17.30, "type": "walk", "minutes": 25, "kcal": 110}]
  },
  "lanes": {
    "steps":  {"hourly": [[6,0.16],[7,0.34], ...], "inactive": [[12.70,15.50],[19.60,24.0]]},
    "sleep":  {"stages": [[0.0,0.40,"light"],[0.40,1.05,"deep"], ...],
               "asleep_h": 6.2, "efficiency": 88},
    "doses":  [{"t": 7.90, "slot": "morning", "label": "M", "taken": true,  "at": "07:54"},
               {"t": 22.0, "slot": "night",   "label": "S", "taken": false, "at": null}],
    "mood":   [{"t": 8.0, "level": 3, "emoji": "neutral"}, ...],   // discrete; NEVER a connecting line
    "vitals": [{"t": 8.0, "systolic": 128, "diastolic": 82}, ...]
  },
  "header": {
    "glucose":  {"tir_pct": 78, "avg": 132, "gri": 42},
    "nutrition":{"kcal": 1840, "kcal_target": 2000, "meals": 4},
    "sleep":    {"asleep_h": 6.2, "efficiency": 88},
    "activity": {"steps": 6240, "steps_goal": 8000},
    "vitals":   {"bp_latest": "122/79", "hr_avg": 72},
    "care":     {"doses_taken": 2, "doses_total": 3, "tasks_done": 4, "tasks_total": 6}
  },
  "reports": {                              // deterministic IDs for drill-down (derived, not stored)
    "glucose": "sha256(patient·cgm·2026-08-06)",
    "meal":    "sha256(patient·meal·2026-08-06)",
    "sleep":   "sha256(patient·sleep·2026-08-06)",
    "fitness": "sha256(patient·fitness·2026-08-06)"
  }
}
```

## Source of truth per block

| Payload block | Source | Read via |
|---|---|---|
| `spine.points` (cgm) | Mongo CGM daily report `cgm_readings[]` | `$lookup` by cgm report ID |
| `spine.points` (smbg) | Postgres `PatientSMBG` | `PatientTimelineService._query_smbg` |
| `spine.points` (hr) | ClickHouse `vitals_data` type=heart_rate | day-slice query, downsample |
| `spine.events` | Mongo CGM report `hypo_events` / `hyper_events` | project spans (**wiring #1**) |
| `onCurve.meals` | Mongo meal report, per-meal | `glucose_response.delta_mgdl`, `score`, `glucose_comparison` |
| `onCurve.symptoms` | Postgres `symptom_entry` | `_query_symptoms` |
| `onCurve.workouts` | Postgres/ClickHouse fitness | `_query_workouts` / per-session query (**wiring #2**) |
| `lanes.steps` | Mongo fitness report | `hourly_stats[]`, `inactive_periods[]` |
| `lanes.sleep` | ClickHouse `sleep_data` spans + sleep report | stage intervals + `efficiency` |
| `lanes.doses` | Postgres `daily_tasks` (MEDICATION) | `_query_medications` |
| `lanes.mood` | Postgres `mood_entry` | `_query_moods` |
| `lanes.vitals` | ClickHouse `vitals_data` | `_query_*` / summary |
| `header.*` | the four domain reports | one field each (TIR, kcal, asleep_h, steps…) |

## Query plan

The report-derived blocks resolve by deterministic ID; the behavioral/raw blocks
reuse `PatientTimelineService`. Everything independent runs under a single
`asyncio.gather`.

```python
async def resolve(patient_id: str, date: date) -> DayPayload:
    day_start, day_end = local_day_bounds(patient_id, date)   # patient-local tz → naive
    ids = {d: report_id(patient_id, d, day_start, day_end)    # sha256, derived not stored
           for d in ("cgm", "meal", "sleep", "fitness")}

    cgm_rep, meal_rep, sleep_rep, fit_rep, moods, symptoms, vitals, doses = await asyncio.gather(
        lookup_report(ids["cgm"]),        # Mongo $lookup — curve + events + TIR/avg/GRI
        lookup_report(ids["meal"]),       # per-meal response + daily macro totals
        lookup_report(ids["sleep"]),      # efficiency/quality rollups
        lookup_report(ids["fitness"]),    # hourly_stats + inactive_periods + workouts
        tl._query_moods(patient_id, day_start, day_end),
        tl._query_symptoms(patient_id, day_start, day_end),
        tl._query_vitals(patient_id, day_start, day_end),
        tl._query_medications(patient_id, day_start, day_end),
    )

    spine = pick_spine(cgm_rep, patient_id, day_start, day_end)   # cgm→smbg→hr→none
    return assemble(spine, meal_rep, sleep_rep, fit_rep, moods, symptoms, vitals, doses)
```

- `report_id(...)` mirrors `CGMStatsProcessor._generate_report_id` /
  `_compute_report_id_from_metadata` (`lib/services/reports/cgm/service.py:380,395`)
  — `sha256(f"{patient}_{type}_{start_iso}_{end_iso}")`. It is **deterministic**, so we
  derive it at read and never store it.
- `lookup_report` is an `_id` fetch; project to the handful of fields the payload needs
  rather than returning the document.
- Behavioral blocks reuse `PatientTimelineService._query_*`
  (`lib/services/patient_timeline_service.py`) — don't re-query the models directly.
- For **today** (in-progress day): the report may lag the latest sync by minutes. Lean on
  the event-driven report refresh, or compute the few missing enrichments inline. Past days
  are always final.

## Wiring needed (read-side only)

1. **CGM event spans** — surface `hypo_events` / `hyper_events` (start/end/peak) in the
   resolver output. Already computed by the CGM report; just project them.
2. **Per-session workouts** — `generate_daily_detected_workouts_query`
   (`lib/services/reports/fitness/queries.py:252`) returns per-session `day/type/
   duration/calories` but has **zero callers** (dead code). Wire it so `onCurve.workouts`
   gets real start/end + kcal instead of per-type sums.

## Drill-down

`GET /v1/patients/{id}/day/{domain}?date=…` returns the **full** domain report — the
same Mongo doc, fetched by the deterministic ID the lean payload already carries in
`reports.{domain}`. No new report type, no duplication. `checkins` (mood/symptoms/
vitals) and `care` (meds/tasks) have no Mongo report; their "full" view is the same
`PatientTimelineService` queries, unpaginated.

## Not in the day payload

Deliberately excluded — they mislead on a single day or belong to a period view:

- **GMI / eA1c** and **AGP percentiles** — multi-day by construction.
- **Sleep consistency, bedtime/wake variability** — need ≥3 nights (null on one day).
- **All `trend.*` deltas** (every domain) — comparative; belong in the weekly report.
- **Micronutrients, per-food items, XP** — drill-down detail only.
- **A1c / creatinine labs, weight** — sparse/slow; a labs/trend view, not a daily clock.

## Caching (future, not now)

If the endpoint becomes a hot path (a provider scanning 100 patients' days), add a
read-through cache of the assembled payload keyed `(patient, date, last_write_version)`,
invalidated on any log for that date. A cache, **not** a source of truth — distinct from
materializing. Add when measured.

## Honesty invariants (carried from the design)

- SMBG spine is **dots, never a connecting line** — we don't draw glucose we didn't measure.
- `mood` is discrete markers, **no connector** — a line implies a trajectory we never measured.
- `steps.inactive` = "no steps logged" windows, not "sedentary" — a sample gap can be a
  device that was off; we don't assert behavior we can't distinguish.
- HR spine is heart rate, never relabeled as glucose.
- Any narrative ("headache on the glucose dip") is Phase-2 `HealthQueryAgent`, temporal
  association only, and **not** part of this MVP payload.
